"""Scheduling views"""

from collections import Counter, defaultdict
from datetime import timedelta
from itertools import combinations
from typing import Any, get_args

from flask import current_app as app
from flask import flash, redirect, render_template, request, url_for
from flask.typing import ResponseReturnValue
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

    estimates = {
        schedule_item_type.type: get_cfp_estimate(schedule_item_type.type, "automatic")
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
        estimates=estimates,
        schedule_state=schedule_state,
        schedule_state_by_type=schedule_state_by_type,
        potential_schedules=potential_schedules,
        schedule_item_types=schedule_item_types,
        to_finalise=to_finalise,
    )


@cfp_review.route("/schedule/run-scheduler", methods=["GET", "POST"])
@schedule_required
def run_scheduler():

    if request.method == "POST" and request.form.get("run"):
        scheduler = Scheduler()
        # FIXME: maybe configure the content types here
        result = scheduler.run(["talk", "workshop"])
        db.session.add(result)
        db.session.commit()

        return redirect(url_for(".potential_schedule", schedule_id=result.id))

    return render_template("cfp_review/schedule/schedule_run.html")


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

    popularity: Counter[tuple[Occurrence, Occurrence]] = Counter()
    for occurrences in user_faves.values():
        popularity.update((o1, o2) for o1, o2 in combinations(sorted(occurrences, key=lambda o: o.id), 2))

    clashes = []
    offset = 0
    for (o1, o2), count in popularity.most_common()[:1000]:
        offset += 1
        p1 = o1.schedule_item.proposal
        p2 = o2.schedule_item.proposal
        if not p1 or not p2:
            # TODO: this should be rare, do we flag it up?
            continue

        if p1.state not in {"accepted", "finalised"} or p2.state not in {"accepted", "finalised"}:
            # TODO: this also should be rare, do we flag it up?
            continue

        if o1.overlaps_with(o2):
            clashes.append(
                {
                    "occurrence_1": o1,
                    "occurrence_2": o2,
                    "favourite_count": count,
                    "number": offset,
                }
            )

    return render_template("cfp_review/schedule/clashfinder.html", clashes=clashes)


def scheduleitems_to_finalise():
    return [
        si
        for si in db.session.query(ScheduleItem).where(
            ScheduleItem.has_availability != True, ScheduleItem.proposal_id.is_not(None)
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
