from collections import Counter, defaultdict
from datetime import timedelta
from itertools import combinations

from flask import current_app as app
from scipy.stats import false_discovery_control, hypergeom
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

# Default types considered to use for speaker/slot conflict detection, even if
# they are not being auto-scheduled
DEFAULT_CONFLICT_TYPES: list[ScheduleItemType] = [
    "talk",
    "workshop",
    "familyworkshop",
    "performance",
    "music",
    "djset",
]


def total_minutes(delta: timedelta) -> int:
    return int(delta.total_seconds() / 60)


def compute_clashes(
    user_faves: dict[int, list[Occurrence]],
) -> list[tuple[Occurrence, Occurrence, int, int]]:
    """Identify pairs of occurrences that are favourited together more than chance.

    Given a mapping of user id to the occurrences they've favourited, this finds
    pairs of talks that are statistically more commonly co-favourited than noise.

    Because some people just favourite everything, a pure pairwise count flags up
    pairs as common clashes when people are really just loving everything we do. We
    correct for this by identifying pairs that are statistically more common than
    noise, and apply a correction to handle people who love too much.
    """
    # ignore pairs co-favourited by fewer people than this
    MIN_PEOPLE = 5
    # only consider clashes that are 1.5x higher than noise
    MIN_LIFT = 1.5
    # and have a q-value no larger than this
    MAX_QVALUE = 0.05

    population = len(user_faves)
    fans: Counter[Occurrence] = Counter()
    popularity: Counter[tuple[Occurrence, Occurrence]] = Counter()
    for occurrences in user_faves.values():
        unique = set(occurrences)
        fans.update(unique)
        for o1, o2 in combinations(sorted(unique, key=lambda o: o.id), 2):
            # We don't care about clashes with other occurrences of the same
            # proposal, we have a hard constraint preventing them clashing
            if o1.proposal == o2.proposal:
                continue
            popularity[(o1, o2)] += 1

    candidates: list[tuple[tuple[Occurrence, Occurrence], int]] = []
    a_fans = []
    b_fans = []
    for (a, b), count in popularity.items():
        if count < MIN_PEOPLE:
            continue
        candidates.append(((a, b), count))
        a_fans.append(fans[a])
        b_fans.append(fans[b])

    ranked: list[tuple[Occurrence, Occurrence, int, int]] = []
    if candidates:
        expected = [na * nb / population for na, nb in zip(a_fans, b_fans, strict=True)]
        pvalues = hypergeom.sf([count - 1 for _, count in candidates], population, a_fans, b_fans)
        qvalues = false_discovery_control(pvalues, method="bh")

        for ((o1, o2), count), mean, qvalue in zip(candidates, expected, qvalues, strict=True):
            if count < MIN_LIFT * mean or qvalue > MAX_QVALUE:
                continue
            ranked.append((o1, o2, count, max(1, round(count - mean))))
        ranked.sort(key=lambda r: r[3], reverse=True)

    return ranked


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
            .join(Occurrence.schedule_item)
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

    def get_schedule_problem(
        self,
        types: list[ScheduleItemType],
        conflict_types: list[ScheduleItemType] | None = None,
        max_clashes: int = 1000,
    ) -> SchedulingProblem:
        # "types" are the content types to auto-schedule. All other types are
        # fixed in place as if manually scheduled and present only for speaker
        # conflict avoidance.
        #
        # "conflict_types" are the content types to consider when they are not
        # being auto-scheduled but we want to consider them for speaker and
        # slot conflict detection
        if conflict_types is None:
            conflict_types = DEFAULT_CONFLICT_TYPES
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
            # Skip types which are neither being auto-scheduled nor checked for
            # conflicting slots or speakers
            if type not in types and type not in conflict_types:
                continue

            ranked_capacities = sorted(set(capacity_by_type[type].values()))
            capacity_rank = {capacity: rank for rank, capacity in enumerate(ranked_capacities, start=1)}

            # Distinct venue capacities, largest first. Tthe window slides from
            # largest to smallest as we work down the occurrences in popularity
            # order, so more popular talks prefer the larger venues, with each
            # venue getting two preferences except the lowest ranked venues
            # which get one.
            tiers = sorted(set(capacity_by_type[type].values()), reverse=True)

            for i, occurrence in enumerate(occurrences):
                assert occurrence.scheduled_duration

                # Save the occurrence by ID so we can quickly look it up from the result
                self.occurrences[occurrence.id] = occurrence

                # Per-venue allowed time ranges: the intersection of the speaker's availability
                # and each venue's TimeBlocks for this content type.
                #
                # Weight only the talk's first and second preference venue,
                # scaled by the talk's favourites and capacity rank. Every
                # other venue gets 0.
                if type in types:
                    favourites = max(1, len(occurrence.schedule_item.favourited_by))
                    allowed_times = occurrence.allowed_times(True)

                    # Slides the window from largest to smallest, assigning
                    # first and second preference venues
                    first = min(i * len(tiers) // len(occurrences), len(tiers) - 1) if tiers else 0
                    preferred = set(tiers[first : first + 2])

                    # If none of the allowed venues are in the windows, fall
                    # back to the talks own smallest available venue so we
                    # always weight one of them
                    allowed_capacities = {venue.capacity or 0 for venue in allowed_times}
                    if allowed_capacities and preferred.isdisjoint(allowed_capacities):
                        preferred = {min(allowed_capacities)}

                    venue_times = [
                        VenueTimes(
                            venue=venue.id,
                            times=times,
                            venue_weight=favourites * capacity_rank[venue.capacity or 1]
                            if venue.capacity in preferred
                            else 0,
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

        # Avoid statistically-significant co-favourited pairs as conflicts
        # weighted by the number of people who would likely be forced to choose
        # between them. Uses the same model as the clashfinder.
        conflicts = [
            Conflict(talks={o1.id, o2.id}, weight=weight)
            for o1, o2, _count, weight in compute_clashes(user_faves)[:max_clashes]
        ]

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

    def run(
        self,
        types: list[ScheduleItemType],
        conflict_types: list[ScheduleItemType] | None = None,
        max_clashes: int = 1000,
        runtime: int = 30,
    ) -> PotentialSchedule:
        problem = self.get_schedule_problem(types, conflict_types, max_clashes)
        if len(problem.talks) == 0:
            raise Exception("No talks to schedule")

        sm = SlotMachine(problem)
        solution = sm.solve(max_time_in_seconds=runtime)

        return self.generate_potential_schedule(solution)
