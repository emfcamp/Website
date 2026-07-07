"""Scheduling views"""

import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from io import BytesIO
from itertools import combinations
from typing import Any, cast, get_args

import slotmachine
from flask import current_app as app
from flask import flash, redirect, render_template, request, send_file, url_for
from flask.typing import ResponseReturnValue
from scipy.stats import false_discovery_control, hypergeom
from sqlalchemy import and_, select
from sqlalchemy.orm import joinedload
from sqlalchemy.sql import desc

from apps.cfp.scheduler import Scheduler
from apps.cfp_review.email import send_email_for_proposal
from apps.cfp_review.estimation import get_cfp_estimate
from main import db, get_or_404
from models.content import (
    Occurrence,
    Proposal,
    ScheduleItem,
    Venue,
)
from models.content.potential_schedule import PotentialSchedule
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

    if request.method == "POST" and request.form.get("run"):
        types = request.form.getlist("auto_type")
        scheduler = Scheduler()
        result = None
        try:
            result = scheduler.run(types)
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

    return render_template("cfp_review/schedule/schedule_run.html", type_options=type_options)


@cfp_review.route("/schedule/run-scheduler/export.json")
@schedule_required
def run_scheduler_export() -> ResponseReturnValue:
    # Export the scheduling problem as JSON for debugging with slotmachine
    types = cast("list[ScheduleItemType]", request.args.getlist("auto_type")) or DEFAULT_AUTO_SCHEDULE_TYPES
    problem = Scheduler().get_schedule_problem(types)
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

    if request.method == "POST":
        if request.form.get("apply") == "true":
            potential_schedule.apply()
            flash("Potential schedule applied")
        if request.form.get("discard") == "true":
            potential_schedule.state = "discarded"

        db.session.commit()
        return redirect(url_for(".schedule"))

    return render_template(
        "cfp_review/schedule/potential_schedule.html", potential_schedule=potential_schedule
    )


@cfp_review.route("/scheduler")
@schedule_required
def scheduler() -> ResponseReturnValue:
    occurrences: list[Occurrence] = list(
        db.session.scalars(
            select(Occurrence)
            .where(Occurrence.scheduled_duration.isnot(None))
            .where(
                Occurrence.proposal.has(
                    and_(
                        # FIXME: are these needed?
                        Proposal.state.in_({"accepted", "finalised"}),
                        Proposal.type.in_({"talk", "workshop", "familyworkshop", "performance"}),
                    )
                )
            )
            .options(joinedload(Occurrence.schedule_item).joinedload(ScheduleItem.proposal))
        )
    )

    shown_venues = [
        {"key": v.id, "label": v.name}
        for v in db.session.scalars(select(Venue).order_by(Venue.priority.desc()))
    ]

    venues_to_show = request.args.getlist("venue")
    if venues_to_show:
        shown_venues = [venue for venue in shown_venues if venue["label"] in venues_to_show]

    venue_ids = [venue["key"] for venue in shown_venues]

    occurrence_data = []
    for occurrence in occurrences:
        if occurrence.schedule_item.proposal:
            speakers = [occurrence.schedule_item.proposal.user.id]
        else:
            app.logger.warning(f"Occurrence {occurrence.id} has no associated speakers")
            speakers = []

        # FIXME rename these fields, they're all out of date,
        # and maybe add some proper typing
        # See also cfp.scheduler.Scheduler.get_schedule_data

        export: dict[str, Any] = {
            "id": occurrence.id,
            "duration": occurrence.scheduled_duration,
            "is_potential": False,
            "is_attendee": not occurrence.schedule_item.official_content,
            "speakers": speakers,
            "text": occurrence.schedule_item.title,
            "valid_venues": [v.id for v in occurrence.allowed_venues or occurrence.valid_allowed_venues],
            # "valid_time_ranges": [
            #    {"start": str(p.start), "end": str(p.end)}
            #    for p in occurrence.get_allowed_time_periods_with_default()
            # ],
        }

        if occurrence.scheduled_venue:
            export["venue"] = occurrence.scheduled_venue_id
        if occurrence.potential_venue:
            export["venue"] = occurrence.potential_venue.id
            export["is_potential"] = True

        if occurrence.scheduled_time:
            export["start_date"] = occurrence.scheduled_time
        if occurrence.potential_time:
            export["start_date"] = occurrence.potential_time
            export["is_potential"] = True

        if "start_date" in export:
            # We filter on Occurrence.scheduled_duration.isnot(None)) above
            assert occurrence.scheduled_duration is not None
            export["end_date"] = export["start_date"] + timedelta(minutes=occurrence.scheduled_duration)
            export["start_date"] = str(export["start_date"])
            export["end_date"] = str(export["end_date"])

        # We can't show things that are not yet in a slot!
        # FIXME: Show them somewhere
        if "venue" not in export or "start_date" not in export:
            continue

        # Skip this event if we're filtering out the venue it's currently scheduled in
        if export["venue"] not in venue_ids:
            continue

        occurrence_data.append(export)

    ## FIXME: TimeBlock migration
    # venue_names_by_type = Venue.emf_venue_names_by_type()

    return render_template(
        "cfp_review/schedule/scheduler.html",
        shown_venues=shown_venues,
        occurrence_data=occurrence_data,
        default_venues={},
    )


# AJAX update endpoint for JS-based scheduler
# @cfp_review.route("/scheduler-update", methods=["GET", "POST"])
# @admin_required
# def scheduler_update() -> ResponseReturnValue:
#    occurrence = get_or_404(db, Occurrence, int(request.form["id"]))
#    occurrence.potential_time = dateutil.parser.parse(request.form["time"]).replace(tzinfo=None)
#    occurrence.potential_venue_id = int(request.form["venue"])
#
#    changed = True
#    if occurrence.potential_time == occurrence.scheduled_time and str(occurrence.potential_venue_id) == str(
#        occurrence.scheduled_venue_id
#    ):
#        occurrence.potential_time = None
#        occurrence.potential_venue = None
#        changed = False
#
#    db.session.commit()
#    return jsonify({"changed": changed})


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
