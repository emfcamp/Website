"""Scheduling views"""

import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from io import BytesIO
from itertools import combinations
from typing import Any, cast, get_args

import slotmachine
from flask import current_app as app
from flask import flash, jsonify, redirect, render_template, request, send_file, url_for
from flask.typing import ResponseReturnValue
from scipy.stats import false_discovery_control, hypergeom
from sqlalchemy import and_, not_, select
from sqlalchemy.orm import joinedload
from sqlalchemy.sql import desc

from apps.cfp.scheduler import DEFAULT_CONFLICT_TYPES, Scheduler
from apps.cfp_review.email import send_email_for_proposal
from apps.cfp_review.estimation import get_cfp_estimate
from apps.config import config
from main import db, get_or_404
from models.content import (
    Occurrence,
    ScheduleItem,
    Venue,
)
from models.content.potential_schedule import PotentialSchedule, PotentialScheduleOccurrence
from models.content.schedule import SCHEDULE_ITEM_INFOS, ScheduleItemInfo, ScheduleItemState, ScheduleItemType

from . import cfp_review, schedule_required

# Content types that are ticked by default for auto-scheduling
DEFAULT_AUTO_SCHEDULE_TYPES: list[ScheduleItemType] = ["talk", "workshop", "familyworkshop"]


@cfp_review.route("/schedule")
@schedule_required
def schedule() -> ResponseReturnValue:
    counts_by_state: dict[ScheduleItemState, Counter[Any]] = {
        s: Counter() for s in get_args(ScheduleItemState)
    }
    counts_by_type: Counter[ScheduleItemType] = Counter()

    for schedule_item in db.session.query(ScheduleItem).filter(ScheduleItem.official_content).all():
        counts_by_type[schedule_item.type] += 1
        counts_by_state[schedule_item.state]["total"] += 1
        counts_by_state[schedule_item.state][schedule_item.type] += 1

    schedule_item_types: list[ScheduleItemInfo] = [i for i in SCHEDULE_ITEM_INFOS.values()]

    estimates_auto = {
        schedule_item_type.type: get_cfp_estimate(schedule_item_type.type, "automatic")
        for schedule_item_type in schedule_item_types
    }

    estimates_manual = {
        schedule_item_type.type: get_cfp_estimate(schedule_item_type.type, "manual")
        for schedule_item_type in schedule_item_types
    }

    schedule_state: Counter[str] = Counter()
    schedule_state_by_type: dict[ScheduleItemType, Counter[str]] = {
        s: Counter() for s in get_args(ScheduleItemType)
    }

    for occurrence in (
        db.session.query(Occurrence).join(Occurrence.schedule_item).where(ScheduleItem.official_content).all()
    ):
        if occurrence.manually_scheduled:
            if occurrence.scheduled:
                schedule_state["manual_scheduled"] += 1
            else:
                schedule_state["manual_unscheduled"] += 1
        else:
            if occurrence.scheduled:
                schedule_state["auto_scheduled"] += 1
            else:
                if len(occurrence.schedule_item.availability) == 0:
                    schedule_state["auto_missing_availability"] += 1
                else:
                    schedule_state["auto_unscheduled"] += 1

        if occurrence.scheduled:
            schedule_state_by_type[occurrence.schedule_item.type]["scheduled"] += 1
        elif len(occurrence.schedule_item.availability) == 0:
            schedule_state_by_type[occurrence.schedule_item.type]["missing_availability"] += 1
        else:
            schedule_state_by_type[occurrence.schedule_item.type]["unscheduled"] += 1

    potential_schedules = list(
        db.session.query(PotentialSchedule)
        .order_by(desc(PotentialSchedule.created))
        .filter(PotentialSchedule.state.in_(["new", "applied"]))
        .limit(10)
    )

    to_finalise = len(scheduleitems_to_finalise())

    return render_template(
        "cfp_review/schedule/schedule.html",
        counts_by_type=counts_by_type,
        counts_by_state=counts_by_state,
        estimates_auto=estimates_auto,
        estimates_manual=estimates_manual,
        schedule_state=schedule_state,
        schedule_state_by_type=schedule_state_by_type,
        potential_schedules=potential_schedules,
        schedule_item_types=schedule_item_types,
        to_finalise=to_finalise,
    )


@cfp_review.route("/schedule/run-scheduler", methods=["GET", "POST"])
@schedule_required
def run_scheduler():
    type_options = [
        {
            "type": t,
            "label": SCHEDULE_ITEM_INFOS[t].human_type if t in SCHEDULE_ITEM_INFOS else t,
            "checked": t in DEFAULT_AUTO_SCHEDULE_TYPES,
        }
        for t in get_args(ScheduleItemType)
    ]

    conflict_type_options = [
        {
            "type": t,
            "label": SCHEDULE_ITEM_INFOS[t].human_type if t in SCHEDULE_ITEM_INFOS else t,
            "checked": t in DEFAULT_CONFLICT_TYPES,
        }
        for t in get_args(ScheduleItemType)
    ]

    if request.method == "POST" and request.form.get("run"):
        types = request.form.getlist("auto_type")
        conflict_types = request.form.getlist("conflict_type")
        scheduler = Scheduler()
        result = None
        try:
            result = scheduler.run(types, conflict_types)
        except slotmachine.Unsatisfiable as e:
            app.logger.exception("Unsatisfiable schedule")
            flash(f"Schedule was unsatisfiable :( {e}")
        except Exception as e:
            app.logger.exception("Scheduler failed")
            flash(f"Scheduler failed: {e}")

        if scheduler.unschedulable:
            ids = ", ".join(str(o.id) for o in scheduler.unschedulable)
            flash(
                f"{len(scheduler.unschedulable)} occurrences unschedulable due to lack of times. May be manually scheduled outside a timeblock, or there are no automatic timeblocks of that type. Occurrence IDs: {ids}"
            )

        if result is not None:
            db.session.add(result)
            db.session.commit()
            return redirect(url_for(".potential_schedule", schedule_id=result.id))

    return render_template(
        "cfp_review/schedule/schedule_run.html",
        type_options=type_options,
        conflict_type_options=conflict_type_options,
    )


@cfp_review.route("/schedule/run-scheduler/export.json")
@schedule_required
def run_scheduler_export() -> ResponseReturnValue:
    # Export the scheduling problem as JSON for debugging with slotmachine
    types = cast("list[ScheduleItemType]", request.args.getlist("auto_type")) or DEFAULT_AUTO_SCHEDULE_TYPES
    conflict_types = (
        cast("list[ScheduleItemType]", request.args.getlist("conflict_type")) or DEFAULT_CONFLICT_TYPES
    )
    problem = Scheduler().get_schedule_problem(types, conflict_types)
    json_str = json.dumps(problem.to_dict(), sort_keys=True, indent=4, separators=(",", ": "))

    now = datetime.now().isoformat()
    return send_file(
        BytesIO(json_str.encode()),
        mimetype="application/json",
        as_attachment=True,
        download_name=f"slotmachine-problem-{now}.json",
    )


@cfp_review.route("/schedule/potential_schedule/<int:schedule_id>", methods=["GET", "POST"])
@schedule_required
def potential_schedule(schedule_id: int) -> ResponseReturnValue:
    potential_schedule = get_or_404(db, PotentialSchedule, schedule_id)

    # We don't allow you to apply a potential schedule older than the most
    # recent one
    latest = db.session.scalars(
        select(PotentialSchedule)
        .where(PotentialSchedule.state != "discarded")
        .order_by(desc(PotentialSchedule.created))
        .limit(1)
    ).first()

    can_apply = (
        potential_schedule.state == "new" and latest is not None and latest.id == potential_schedule.id
    )

    if request.method == "POST":
        if request.form.get("apply") == "true":
            if not can_apply:
                flash("Only the most recent potential schedule can be applied!")
                return redirect(url_for(".potential_schedule", schedule_id=schedule_id))

            potential_schedule.apply()

            # Potential schedules are derived from each other, so if we have
            # older ones when we apply a schedule we should mark them as
            # applied
            others = db.session.scalars(
                select(PotentialSchedule).where(
                    PotentialSchedule.state == "new",
                    PotentialSchedule.id != potential_schedule.id,
                )
            )
            for other in others:
                other.state = "applied"

            flash("Potential schedule applied")

        if request.form.get("discard") == "true":
            potential_schedule.state = "discarded"

        db.session.commit()
        return redirect(url_for(".schedule"))

    return render_template(
        "cfp_review/schedule/potential_schedule.html",
        potential_schedule=potential_schedule,
        can_apply=can_apply,
    )


def latest_new_schedules() -> tuple[PotentialSchedule | None, PotentialSchedule | None]:
    draft = None
    automatic = None
    for candidate in db.session.scalars(
        select(PotentialSchedule)
        .where(PotentialSchedule.state == "new")
        .order_by(desc(PotentialSchedule.created))
    ):
        is_manual = candidate.scheduler_stats.get("source") == "schedule_tweaker"
        if is_manual and draft is None:
            draft = candidate
        elif not is_manual and automatic is None:
            automatic = candidate
        if draft is not None and automatic is not None:
            break

    return draft, automatic


def staged_occurrence(schedule: PotentialSchedule, occurrence_id: int) -> PotentialScheduleOccurrence | None:
    return next((so for so in schedule.scheduled_occurrences if so.occurrence_id == occurrence_id), None)


def get_or_create_tweaker_schedule() -> PotentialSchedule:
    """Return the current Schedule Tweaker draft, creating one if none exists.

    If the previous draft is an automatic schedule, we copy that for tweaking
    rather than directly changing it.
    """
    draft, automatic = latest_new_schedules()
    if draft is not None:
        return draft

    draft = PotentialSchedule(scheduler_stats={"source": "schedule_tweaker"})
    db.session.add(draft)

    if automatic:
        for so in automatic.scheduled_occurrences:
            db.session.add(
                PotentialScheduleOccurrence(
                    potential_schedule=draft,
                    occurrence=so.occurrence,
                    venue=so.venue,
                    start_time=so.start_time,
                )
            )

    db.session.flush()
    return draft


@cfp_review.route("/scheduler")
@schedule_required
def scheduler() -> ResponseReturnValue:
    occurrences: list[Occurrence] = list(
        db.session.scalars(
            select(Occurrence)
            .where(
                not_(Occurrence.cancelled),
                Occurrence.schedule_item.has(
                    and_(
                        ScheduleItem.official_content,
                        ScheduleItem.state != "cancelled",
                    )
                ),
                Occurrence.scheduled_duration.isnot(None),
            )
            .options(joinedload(Occurrence.schedule_item).joinedload(ScheduleItem.proposal))
        )
    )

    venues = list(db.session.scalars(select(Venue).order_by(Venue.priority.desc())))
    shown_venues = [{"key": v.id, "label": v.name} for v in venues]

    venues_to_show = request.args.getlist("venue")
    if venues_to_show:
        shown_venues = [venue for venue in shown_venues if venue["label"] in venues_to_show]

    venue_ids = [venue["key"] for venue in shown_venues]

    timeblock_ranges: dict[str, dict[int, list[dict[str, str]]]] = defaultdict(lambda: defaultdict(list))
    for venue in venues:
        for time_block in venue.time_blocks:
            timeblock_ranges[time_block.type][venue.id].append(
                {"start": str(time_block.start), "end": str(time_block.end)}
            )

    venue_name_by_id = {venue.id: venue.name for venue in venues}
    venues_by_type = {
        content_type: [venue_name_by_id[venue_id] for venue_id in venue_ids]
        for content_type, venue_ids in timeblock_ranges.items()
    }

    # Overlay positions from the current draft if one exists
    draft, automatic = latest_new_schedules()
    source_schedule = draft or automatic
    source_positions: dict[int, PotentialScheduleOccurrence] = (
        {so.occurrence_id: so for so in source_schedule.scheduled_occurrences} if source_schedule else {}
    )

    occurrence_data = []
    for occurrence in occurrences:
        export: dict[str, Any] = {
            "id": occurrence.id,
            "is_potential": False,
            "is_attendee": not occurrence.schedule_item.official_content,
            "text": occurrence.schedule_item.title,
            "valid_venue_times": timeblock_ranges.get(occurrence.schedule_item.type, {}),
        }

        slot_venue = occurrence.scheduled_venue
        start_time = occurrence.scheduled_time

        if occurrence.id in source_positions:
            staged = source_positions[occurrence.id]
            slot_venue = staged.venue
            start_time = staged.start_time
            export["is_potential"] = staged.has_changed()

        if slot_venue:
            export["venue"] = slot_venue.id
        if start_time:
            # We filter on Occurrence.scheduled_duration.isnot(None)) above
            assert occurrence.scheduled_duration is not None
            export["start_date"] = str(start_time)
            export["end_date"] = str(start_time + timedelta(minutes=occurrence.scheduled_duration))

        # We can't show things that are not yet in a slot!
        # FIXME: Show them somewhere
        if "venue" not in export or "start_date" not in export:
            continue

        # Skip this event if we're filtering out the venue it's currently scheduled in
        if export["venue"] not in venue_ids:
            continue

        occurrence_data.append(export)

    return render_template(
        "cfp_review/schedule/scheduler.html",
        shown_venues=shown_venues,
        venues_by_type=venues_by_type,
        occurrence_data=occurrence_data,
        draft=draft,
        auto_schedule=automatic,
        event_start=config.event_start,
        event_end=config.event_end,
    )


@cfp_review.route("/scheduler-update", methods=["POST"])
@schedule_required
def scheduler_update() -> ResponseReturnValue:
    occurrence = get_or_404(db, Occurrence, int(request.form["id"]))
    venue = get_or_404(db, Venue, int(request.form["venue"]))
    start_time = datetime.fromisoformat(request.form["time"]).replace(tzinfo=None)

    if not occurrence.is_valid_slot(start_time, venue):
        return jsonify({"error": "Invalid slot"}), 400

    changed = start_time != occurrence.scheduled_time or venue != occurrence.scheduled_venue

    draft: PotentialSchedule | None
    if changed:
        draft = get_or_create_tweaker_schedule()
        existing = staged_occurrence(draft, occurrence.id)
        if existing:
            existing.start_time = start_time
            existing.venue = venue
        else:
            db.session.add(
                PotentialScheduleOccurrence(
                    potential_schedule=draft,
                    occurrence=occurrence,
                    venue=venue,
                    start_time=start_time,
                )
            )
    else:
        # Dragged back to its current slot
        draft, _ = latest_new_schedules()
        if draft:
            existing = staged_occurrence(draft, occurrence.id)
            if existing:
                db.session.delete(existing)

            # And if the draft is now empty, nuke it
            changes_remaining = [x for x in draft.changed_occurrences() if x != existing]
            if not changes_remaining:
                db.session.delete(draft)

    db.session.commit()
    return jsonify({"changed": changed})


@cfp_review.route("/clashfinder")
@schedule_required
def clashfinder() -> ResponseReturnValue:
    schedule_items = list(
        db.session.scalars(
            select(ScheduleItem)
            .options(joinedload(ScheduleItem.occurrences))
            .options(joinedload(ScheduleItem.proposal))
            .options(joinedload(ScheduleItem.favourited_by))
        ).unique()
    )

    user_faves: dict[int, list[Occurrence]] = defaultdict(list)
    for schedule_item in schedule_items:
        for user in schedule_item.favourited_by:
            # Don't check state because we want to include potential times/venues
            user_faves[user.id] += schedule_item.occurrences

    population = len(user_faves)
    fans: Counter[Occurrence] = Counter()
    popularity: Counter[tuple[Occurrence, Occurrence]] = Counter()
    for occurrences in user_faves.values():
        unique = set(occurrences)
        fans.update(unique)
        popularity.update(combinations(sorted(unique, key=lambda o: o.id), 2))

    # Because some people just favourite everything a pure pairwise count can
    # flag up things as being common clashes when people are really just loving
    # everything we do. We correct for this by identifying pairs of talks that
    # are statistically more common than noise, and apply a correction to
    # handle people who love too much. This can be tuned using the following
    # params, which are currently based entirely on vibes and can be
    # played with via undocumented query params.

    # ignore pairs co-favourited by fewer people than this
    MIN_PEOPLE = request.args.get("min_people", 5, type=int)
    # only consider clashes that are 1.5x higher than noise
    MIN_LIFT = request.args.get("min_lift", 1.5, type=float)
    # and have a q-value no larger than this
    MAX_QVALUE = request.args.get("max_qvalue", 0.05, type=float)

    ranked: list[tuple[Occurrence, Occurrence, int, int]] = []

    if request.args.get("old_scoring") == "true":
        for (a, b), count in popularity.most_common():
            ranked.append((a, b, count, 0))
    else:
        candidates: list[tuple[tuple[Occurrence, Occurrence], int]] = []
        a_fans = []
        b_fans = []
        for (a, b), count in popularity.items():
            if count < MIN_PEOPLE:
                continue
            candidates.append(((a, b), count))
            a_fans.append(fans[a])
            b_fans.append(fans[b])

        if candidates:
            expected = [na * nb / population for na, nb in zip(a_fans, b_fans, strict=True)]
            pvalues = hypergeom.sf([count - 1 for _, count in candidates], population, a_fans, b_fans)
            qvalues = false_discovery_control(pvalues, method="bh")

            for ((o1, o2), count), mean, qvalue in zip(candidates, expected, qvalues, strict=True):
                if count < MIN_LIFT * mean or qvalue > MAX_QVALUE:
                    continue

                ranked.append((o1, o2, count, max(1, round(count - mean))))
            ranked.sort(key=lambda r: r[3], reverse=True)

    show_all = request.args.get("show_all") == "true"
    max_clashes = request.args.get("max_clashes", 1000, type=int)

    clashes = []
    number = 0
    for o1, o2, favourite_count, weight in ranked:
        # We don't care about clashes with other occurrences of the same
        # proposal, we have a hard constraint preventing them clashing
        if o1.proposal == o2.proposal:
            continue

        if o1.cancelled or o2.cancelled:
            continue

        number += 1
        if number > max_clashes:
            break

        overlaps = o1.overlaps_with(o2)
        if not overlaps and not show_all:
            continue

        # favourite_count is how many people actually favourited both talks,
        # weight is approximately how many people would be forced to choose
        # between one of them after correction has been applied
        clashes.append(
            {
                "occurrence_1": o1,
                "occurrence_2": o2,
                "favourite_count": favourite_count,
                "number": number,
                "weight": weight,
                "overlaps": overlaps,
            }
        )

    return render_template(
        "cfp_review/schedule/clashfinder.html", clashes=clashes, show_all=show_all, population=population
    )


def scheduleitems_to_finalise():
    return [
        si
        for si in db.session.query(ScheduleItem).where(
            ScheduleItem.has_availability != True,
            ScheduleItem.proposal.has(),
            ScheduleItem.state != "cancelled",
        )
        if len(si.occurrences) > 0 and si.occurrences[0].scheduled_duration is not None
    ]


@cfp_review.route("/send_finalise", methods=["GET", "POST"])
@schedule_required
def send_finalise() -> ResponseReturnValue:
    items = scheduleitems_to_finalise()

    if request.method == "POST" and request.form.get("send"):
        for item in items:
            assert item.proposal
            send_email_for_proposal(item.proposal, reason="please-finalise")

        db.session.commit()
        flash("Schedule email sent")
        return redirect(url_for(".schedule"))

    return render_template("cfp_review/schedule/finalise.html", items=items)
