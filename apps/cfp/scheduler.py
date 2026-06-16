from collections import defaultdict
from datetime import timedelta
from itertools import chain

from flask import current_app as app
from slotmachine import SchedulingProblem, SchedulingSolution, SlotMachine, Talk
from sqlalchemy import and_, select
from sqlalchemy.orm import joinedload

from main import db
from models.content import (
    Occurrence,
    ScheduleItem,
    ScheduleItemType,
    Venue,
)
from models.content.potential_schedule import PotentialSchedule, PotentialScheduleOccurrence
from models.content.schedule import SLOT_DURATION


def total_minutes(delta: timedelta) -> int:
    return int(delta.total_seconds() / 60)


class Scheduler:
    """Automatic Scheduler

    This class handles scheduling operations by using the SlotMachine constraint solving scheduler.
    """

    def __init__(self):
        self.occurrences = {}
        self.venues = {}

    def get_schedulable_occurrences(self, types: list[ScheduleItemType]) -> list[Occurrence]:
        """Fetch a list of Occurrences that the automatic scheduler should consider"""
        return list(
            db.session.scalars(
                select(Occurrence)
                .where(
                    Occurrence.cancelled != True,
                    Occurrence.schedule_item.has(
                        and_(
                            ScheduleItem.type.in_(types),
                            # We only check this here so things should work if we decide to extend it to attendee content
                            ScheduleItem.official_content,
                        )
                    ),
                    Occurrence.scheduled_duration.isnot(None),
                    # Used when we manually schedule things into slots and we want the scheduler to ignore them
                    Occurrence.manually_scheduled.isnot(True),
                )
                .options(joinedload(Occurrence.schedule_item).joinedload(ScheduleItem.proposal))
                .order_by(ScheduleItem.favourite_count.desc())
            )
        )

    def get_schedule_problem(self, types: list[ScheduleItemType] | None = None) -> SchedulingProblem:
        if types is None:
            types = ["talk", "workshop", "familyworkshop"]
        occurrences = self.get_schedulable_occurrences(types)

        occurrences_by_type: dict[ScheduleItemType, list[Occurrence]] = defaultdict(list)
        for occurrence in occurrences:
            occurrences_by_type[occurrence.schedule_item.type].append(occurrence)

        capacity_by_type: dict[ScheduleItemType, dict[int, int]] = defaultdict(dict)
        venues: list[Venue] = list(db.session.scalars(select(Venue)))
        for venue in venues:
            self.venues[venue.id] = venue
            for block in venue.time_blocks:
                if not venue.capacity:
                    raise Exception(f"Official venue has no capacity defined: {venue}")
                capacity_by_type[block.type][venue.id] = venue.capacity or 0

        scheduler_talks = []
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
                assert occurrence.scheduled_duration

                # Save the occurrence by ID so we can quickly look it up from the result
                self.occurrences[occurrence.id] = occurrence

                preferred_venues = set()
                if ordered_venues:
                    # This supports a list, but we only want one for now
                    preferred_venues = {ordered_venues[0]}

                speakers = {occurrence.schedule_item.user.id}

                if not occurrence.availability:
                    app.logger.warning(f"Skipping scheduling occurrence {occurrence} - no availability.")
                    continue

                # Mapping of venues to allowed time ranges
                allowed_times = occurrence.allowed_times(True)
                allowed_venues = set(v.id for v in allowed_times)

                # FIXME: SlotMachine doesn't support per-venue allowed time ranges yet, it will soon.
                # This will emit an inaccurate scheduling problem until fixed!
                allowed_time_ranges = list(chain.from_iterable(allowed_times.values()))

                if len(allowed_time_ranges) == 0:
                    app.logger.warning(f"Skipping scheduling occurrence {occurrence} - no allowed times.")
                    continue

                talk = Talk(
                    id=occurrence.id,
                    duration=occurrence.scheduled_duration,
                    speakers=speakers,
                    allowed_venues=allowed_venues,
                    allowed_times=allowed_time_ranges,
                    preferred_venues=preferred_venues,
                    minutes_after=total_minutes(occurrence.changeover_time),
                )

                if occurrence.scheduled_venue:
                    talk.venue = occurrence.scheduled_venue.id

                if occurrence.scheduled_time:
                    talk.start_time = occurrence.scheduled_time

                scheduler_talks.append(talk)

                # Shift to the next venue when we hit the division
                if count > split_count:
                    count = 0
                    ordered_venues.pop(0)
                else:
                    count += 1

        return SchedulingProblem(talks=scheduler_talks, slot_duration=total_minutes(SLOT_DURATION))

    def generate_potential_schedule(self, solution: SchedulingSolution) -> PotentialSchedule:
        potential_schedule = PotentialSchedule()

        potential_schedule.scheduler_stats = {
            "solution_type": solution.solution_type,
            "timings": {name: td.total_seconds() for name, td in solution.timings.items()},
            "variables": solution.variables,
        }

        potential_schedule.scheduled_occurrences = [
            PotentialScheduleOccurrence(
                occurrence=self.occurrences[talk.id],
                start_time=talk.start_time,
                venue=self.venues[talk.venue],
            )
            for talk in solution.talks
        ]
        return potential_schedule

    def run(self, types: list[ScheduleItemType]) -> PotentialSchedule:
        problem = self.get_schedule_problem(types)
        if len(problem.talks) == 0:
            raise Exception("No talks to schedule")

        sm = SlotMachine(problem)
        solution = sm.solve()

        return self.generate_potential_schedule(solution)
