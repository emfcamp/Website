from collections import defaultdict
from typing import Any, cast

from dateutil import parser
from flask import current_app as app
from slotmachine import SlotMachine
from sqlalchemy import and_, select
from sqlalchemy.orm import joinedload

from main import db
from models.cfp import (
    EVENT_SPACING,
    ROUGH_DURATIONS,
    Occurrence,
    Proposal,
    ScheduleItem,
    ScheduleItemType,
    Venue,
)


class Scheduler:
    """Automatic Scheduler

    This class handles scheduling operations by using the SlotMachine constraint solving scheduler.
    """

    def set_rough_durations(self):
        """
        Use the Proposal.duration field to set Occurrence.scheduled_duration
        """
        # TODO: should we check for manually_scheduled here?
        proposals = list(
            db.session.scalars(
                select(Proposal)
                .where(Proposal.type.in_({"talk", "workshop", "youthworkshop", "performance"}))
                .where(Proposal.state.in_({"accepted", "finalised"}))
            )
        )

        for proposal in proposals:
            schedule_item = proposal.schedule_item
            if not schedule_item.occurrences:
                app.logger.warning(f"Schedule item {schedule_item.id} has no occurrences, ignoring")
                continue

            if not schedule_item.official_content:
                app.logger.warning(f"Schedule item {schedule_item.id} is not official, ignoring")
                continue

            try:
                scheduled_duration = ROUGH_DURATIONS[proposal.duration]
            except KeyError:
                app.logger.warning(
                    f"Invalid proposal duration {repr(proposal.duration)} for {proposal}, ignoring"
                )
                continue

            for occurrence in schedule_item.occurrences:
                if occurrence.scheduled_duration is None:
                    occurrence.scheduled_duration = scheduled_duration

                    app.logger.info(
                        f"""Set duration for occurrence {occurrence.occurrence_num} of {schedule_item.human_type}"""
                        f"""{schedule_item.id} "{schedule_item.title}" to {scheduled_duration}"""
                    )

        db.session.commit()

    def get_scheduler_data(
        self, ignore_potential: bool, types: list[ScheduleItemType] | None = None
    ) -> list[dict[str, Any]]:
        if types is None:
            types = ["talk", "workshop", "youthworkshop"]
        occurrences = list(
            db.session.scalars(
                select(Occurrence)
                .where(
                    Occurrence.schedule_item.has(
                        and_(
                            ScheduleItem.type.in_(types),
                            # We only check this here so things should work if we decide to extend it to attendee content
                            ScheduleItem.official_content,
                        )
                    )
                )
                .where(Occurrence.scheduled_duration.isnot(None))
                # Used when we manually schedule things into slots and we want the scheduler to ignore them
                .where(Occurrence.manually_scheduled.isnot(True))
                .options(joinedload(Occurrence.schedule_item).joinedload(ScheduleItem.proposal))
                .order_by(ScheduleItem.favourite_count.desc())
            )
        )

        occurrences_by_type: dict[ScheduleItemType, list[Occurrence]] = defaultdict(list)
        for occurrence in occurrences:
            occurrences_by_type[occurrence.schedule_item.type].append(occurrence)

        capacity_by_type: dict[ScheduleItemType, dict[int, int]] = defaultdict(dict)
        venues: list[Venue] = list(db.session.scalars(select(Venue)))
        for venue in venues:
            for type in venue.default_for_types:
                # FIXME: is it right to treat an unknown capacity as 0?
                capacity_by_type[type][venue.id] = venue.capacity or 0

        occurrence_data = []
        for type, occurrences in occurrences_by_type.items():
            # We assign the largest venues as being preferred for the most popular talks
            # Occurrences are already sorted into popularity, so we just shift through the list
            # of venues in order of size, equally split
            ordered_venues = sorted(
                capacity_by_type[type],
                key=lambda k: capacity_by_type[type][k],
                reverse=True,
            )
            split_count = int(len(occurrences_by_type[type]) / len(capacity_by_type[type]))

            count = 0
            for occurrence in occurrences:
                preferred_venues = []
                if ordered_venues:
                    # This supports a list, but we only want one for now
                    preferred_venues = [ordered_venues[0]]

                # This is a terrible hack and needs removing
                # If a talk is allowed to happen outside main content hours,
                # don't require it to be spaced from other things - we often
                # have talks and related performances back-to-back
                spacing_slots = EVENT_SPACING.get(occurrence.schedule_item.type, 1)
                if occurrence.schedule_item.type == "talk":
                    for p in occurrence.get_allowed_time_periods_with_default():
                        if p.start.hour < 9 or p.start.hour >= 20:
                            spacing_slots = 0

                if occurrence.schedule_item.proposal:
                    speakers = [occurrence.schedule_item.proposal.user.id]
                else:
                    app.logger.warning(f"Occurrence {occurrence.id} has no associated speakers")
                    speakers = []

                # See also cfp_review.base.scheduler

                export = {
                    "id": occurrence.id,
                    "duration": occurrence.scheduled_duration,
                    "speakers": speakers,
                    "title": occurrence.schedule_item.title,
                    "valid_venues": [
                        v.id for v in occurrence.allowed_venues or occurrence.valid_allowed_venues
                    ],
                    "preferred_venues": preferred_venues,
                    "time_ranges": [
                        {"start": str(p.start), "end": str(p.end)}
                        for p in occurrence.get_allowed_time_periods_with_default()
                    ],
                    "preferred_time_ranges": [
                        {"start": str(p.start), "end": str(p.end)}
                        for p in occurrence.get_preferred_time_periods_with_default()
                    ],
                    "spacing_slots": spacing_slots,
                }

                if occurrence.scheduled_venue:
                    export["venue"] = occurrence.scheduled_venue.id
                if not ignore_potential and occurrence.potential_venue:
                    export["venue"] = occurrence.potential_venue.id

                if occurrence.scheduled_time:
                    export["time"] = str(occurrence.scheduled_time)
                if not ignore_potential and occurrence.potential_time:
                    export["time"] = str(occurrence.potential_time)

                occurrence_data.append(export)

                # Shift to the next venue when we hit the division
                if count > split_count:
                    count = 0
                    ordered_venues.pop(0)
                else:
                    count += 1

        return occurrence_data

    def handle_schedule_change(self, occurrence, venue, time, ignore_potential=False):
        # If the existing proposal is identical to the scheduled, clear proposed
        if (
            str(occurrence.scheduled_venue) == str(occurrence.potential_venue)
            and occurrence.scheduled_time == occurrence.potential_time
        ):
            occurrence.potential_venue = None
            occurrence.potential_time = None

        if not ignore_potential:
            previous_venue = occurrence.potential_venue or occurrence.scheduled_venue
            previous_time = occurrence.potential_time or occurrence.scheduled_time
        else:
            previous_venue = occurrence.scheduled_venue
            previous_time = occurrence.scheduled_time

        previous_venue_name = None
        if previous_venue:
            previous_venue_name = previous_venue.name

        parsed_time = parser.parse(time)

        # Nothing changed
        if str(venue) == str(previous_venue) and parsed_time == previous_time:
            return False

        occurrence.potential_venue = venue
        occurrence.potential_time = parsed_time

        app.logger.info(
            f'Moved "{occurrence.schedule_item.title}": '
            f'"{previous_venue_name}" at "{previous_time}" -> '
            f'"{occurrence.potential_venue.name}" at "{occurrence.potential_time}"'
        )

        return True

    def apply_changes(self, schedule, ignore_potential=False):
        changes = False
        for event in schedule:
            if "time" not in event or not event["time"]:
                continue
            if "venue" not in event or not event["venue"]:
                continue

            occurrence = Occurrence.query.filter_by(id=event["id"]).one()
            venue = Venue.query.get(event["venue"])
            changes |= self.handle_schedule_change(occurrence, venue, event["time"], ignore_potential)

        if not changes:
            app.logger.info("No schedule changes generated")

    def run(self, persist: bool, ignore_potential: bool, types: list[ScheduleItemType]) -> None:
        self.set_rough_durations()

        sm = SlotMachine()
        data = self.get_scheduler_data(ignore_potential, types)
        if len(data) == 0:
            app.logger.error("No talks to schedule!")
            return

        new_schedule = sm.schedule(cast(dict[Any, Any], data))
        self.apply_changes(new_schedule, ignore_potential)

        if persist:
            db.session.commit()
        else:
            app.logger.info("DRY RUN: Pass the `-p` flag to persist these changes")
            db.session.rollback()
