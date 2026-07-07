from collections import Counter, defaultdict
from datetime import timedelta
from itertools import combinations

from flask import current_app as app
from slotmachine import Conflict, SchedulingProblem, SchedulingSolution, SlotMachine, Talk, VenueTimes
from sqlalchemy import and_, not_, select
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
        # Occurrences that we couldn't feed to the scheduler because they're lacking information
        self.unschedulable: list[Occurrence] = []

    def get_schedulable_occurrences(self) -> list[Occurrence]:
        """Fetch a list of Occurrences that the automatic scheduler should consider

        The scheduler needs to consider all official content, even content which is manually scheduled,
        in order to prevent speaker clashes.
        """
        occurrences = db.session.scalars(
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
            .options(joinedload(Occurrence.schedule_item).selectinload(ScheduleItem.favourited_by))
            .order_by(ScheduleItem.favourite_count.desc())
        ).all()

        return list(occurrences)

    def get_schedule_problem(self, types: list[ScheduleItemType]) -> SchedulingProblem:
        # "types" are the content types to auto-schedule. All other types are
        # fixed in place as if manually scheduled and present only for speaker
        # conflict avoidance
        occurrences = self.get_schedulable_occurrences()

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

        user_faves: dict[int, list[Occurrence]] = defaultdict(list)
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
            split_count = (
                int(len(occurrences_by_type[type]) / len(capacity_by_type[type]))
                if capacity_by_type[type]
                else 0
            )

            count = 0
            for occurrence in occurrences:
                assert occurrence.scheduled_duration

                # Save the occurrence by ID so we can quickly look it up from the result
                self.occurrences[occurrence.id] = occurrence

                # Per-venue allowed time ranges: the intersection of the speaker's availability
                # and each venue's TimeBlocks for this content type.
                #
                # We add the same weight to all venues of the current max
                # capacity venue, because variable venue weightings cause
                # serious performance degredation in slotmachine at this scale

                if type in types:
                    current_venues = [
                        v
                        for v in ordered_venues
                        if self.venues[v].capacity == self.venues[ordered_venues[0]].capacity
                    ]
                    allowed_times = occurrence.allowed_times(True)
                    venue_times = [
                        VenueTimes(
                            venue=venue.id,
                            times=times,
                            venue_weight=5 if venue.id in current_venues else 0,
                        )
                        for venue, times in allowed_times.items()
                    ]
                elif (
                    occurrence.scheduled_venue and occurrence.scheduled_time and occurrence.scheduled_end_time
                ):
                    # Not being auto-scheduled: pin to its current venue and time.
                    venue_times = [
                        VenueTimes(
                            venue=occurrence.scheduled_venue.id,
                            times=[(occurrence.scheduled_time, occurrence.scheduled_end_time)],
                        )
                    ]
                else:
                    venue_times = []

                if len(venue_times) == 0:
                    if type in types:
                        # This happens when things are manually scheduled outside
                        # of a timeblock, or when we have no timeblocks of this
                        # type set to be automatically schedulable.
                        app.logger.warning(f"Skipping scheduling occurrence {occurrence} - no allowed times.")
                        self.unschedulable.append(occurrence)
                    continue

                ## tag diversity currently disabled due to performance degredation
                # proposal = occurrence.schedule_item.proposal
                # tags = set(proposal.tags) if proposal else set()

                # Manually scheduled content in a non-automatically scheduled timeblock
                # doesn't need changeover time because we placed it there
                if occurrence.manually_scheduled and any(
                    not block.automatic for block in occurrence.time_blocks()
                ):
                    minutes_after = 0
                else:
                    minutes_after = total_minutes(occurrence.changeover_time)

                talk = Talk(
                    id=occurrence.id,
                    duration=occurrence.scheduled_duration,
                    speakers={speaker.id for speaker in occurrence.schedule_item.presenters},
                    venue_times=venue_times,
                    # tags=tags, # tag diversity currently disabled due to performance degredation
                    minutes_after=minutes_after,
                )

                if occurrence.scheduled_venue:
                    talk.venue = occurrence.scheduled_venue.id

                if occurrence.scheduled_time:
                    talk.start_time = occurrence.scheduled_time

                scheduler_talks.append(talk)

                # For conflict detection
                for user in occurrence.schedule_item.favourited_by:
                    user_faves[user.id].append(occurrence)

                # Shift to the next venue when we hit the division
                if ordered_venues and count > split_count:
                    count = 0
                    ordered_venues.pop(0)
                else:
                    count += 1

        # Calculate the top 1000 most commonly co-starred occurrences
        # and flag them as conflicts
        popularity: Counter[tuple[Occurrence, Occurrence]] = Counter()
        for occurrences in user_faves.values():
            for o1, o2 in combinations(sorted(occurrences, key=lambda o: o.id), 2):
                # We don't care about clashes with other occurrences of the
                # same proposal, we have a hard constraint preventing them
                # clashing
                if o1.proposal == o2.proposal:
                    continue
                popularity.update([(o1, o2)])

        conflicts = []
        for (o1, o2), count in popularity.most_common()[:1000]:
            conflicts.append(Conflict(talks={o1.id, o2.id}, weight=max(1, count)))

        return SchedulingProblem(
            talks=scheduler_talks, conflicts=conflicts, slot_duration=total_minutes(SLOT_DURATION)
        )

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
