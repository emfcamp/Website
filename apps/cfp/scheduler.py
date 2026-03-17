from collections import defaultdict
from dateutil import parser
from flask import current_app as app

from slotmachine import SlotMachine

from main import db
from models.cfp import (
    Proposal,
    Venue,
    ROUGH_LENGTHS,
    EVENT_SPACING,
)


class Scheduler(object):
    """Automatic Scheduler

    This class handles scheduling operations by using the SlotMachine constraint solving scheduler.
    """

    def set_rough_durations(self):
        proposals = (
            Proposal.query.filter_by(scheduled_duration=None)
            .filter(Proposal.type.in_(["talk", "workshop", "youthworkshop", "performance"]))
            .filter(Proposal.is_accepted)
            .all()
        )

        for proposal in proposals:
            try:
                proposal.scheduled_duration = ROUGH_LENGTHS[proposal.length]
            except KeyError:
                app.logger.warn(f"Invalid proposal length {repr(proposal.length)} for {proposal}, ignoring")
                continue

            app.logger.info(
                'Set duration for talk "%s" (%s) to %s'
                % (proposal.title, proposal.id, proposal.scheduled_duration)
            )

        db.session.commit()

    def get_scheduler_data(self, ignore_potential, type=["talk", "workshop", "youthworkshop"]):
        proposals = (
            Proposal.query.filter(Proposal.scheduled_duration.isnot(None))
            .filter(Proposal.is_accepted)
            .filter(Proposal.type.in_(type))
            .filter(Proposal.user_scheduled.is_(False))  # NOTE: This ignores all village-scheduled content
            .filter(
                Proposal.manually_scheduled.isnot(True)
            )  # Used when we manually schedule things into slots and we want the scheduler to ignore them
            .order_by(Proposal.favourite_count.desc())
            .all()
        )

        proposals_by_type = defaultdict(list)
        for proposal in proposals:
            proposals_by_type[proposal.type].append(proposal)

        capacity_by_type = defaultdict(dict)
        for venue in Venue.query.all():
            for type in venue.default_for_types:
                capacity_by_type[type][venue.id] = venue.capacity

        proposal_data = []
        for type, proposals in proposals_by_type.items():
            # We assign the largest venues as being preferred for the most popular talks
            # Proposals are already sorted into popularity, so we just shift through the list
            # of venues in order of size, equally split
            ordered_venues = sorted(
                capacity_by_type[type],
                key=lambda k: capacity_by_type[type][k],
                reverse=True,
            )
            split_count = int(len(proposals_by_type[type]) / len(capacity_by_type[type]))

            count = 0
            for proposal in proposals:
                preferred_venues = []
                if ordered_venues:
                    preferred_venues = [ordered_venues[0]]

                # This is a terrible hack and needs removing
                # If a talk is allowed to happen outside main content hours,
                # don't require it to be spaced from other things - we often
                # have talks and related performances back-to-back
                spacing_slots = EVENT_SPACING.get(proposal.type, 1)
                if proposal.type == "talk":
                    for p in proposal.get_allowed_time_periods_with_default():
                        if p.start.hour < 9 or p.start.hour >= 20:
                            spacing_slots = 0

                export = {
                    "id": proposal.id,
                    "duration": proposal.scheduled_duration,
                    "speakers": [proposal.user.id],
                    "title": proposal.title,
                    "valid_venues": [v.id for v in proposal.get_allowed_venues()],
                    "preferred_venues": preferred_venues,  # This supports a list, but we only want one for now
                    "time_ranges": [
                        {"start": str(p.start), "end": str(p.end)}
                        for p in proposal.get_allowed_time_periods_with_default()
                    ],
                    "preferred_time_ranges": [
                        {"start": str(p.start), "end": str(p.end)}
                        for p in proposal.get_preferred_time_periods_with_default()
                    ],
                    "spacing_slots": spacing_slots,
                }

                if proposal.scheduled_venue:
                    export["venue"] = proposal.scheduled_venue.id
                if not ignore_potential and proposal.potential_venue:
                    export["venue"] = proposal.potential_venue.id

                if proposal.scheduled_time:
                    export["time"] = str(proposal.scheduled_time)
                if not ignore_potential and proposal.potential_time:
                    export["time"] = str(proposal.potential_time)

                proposal_data.append(export)

                # Shift to the next venue when we hit the division
                if count > split_count:
                    count = 0
                    ordered_venues.pop(0)
                else:
                    count += 1

        return proposal_data

    def handle_schedule_change(self, proposal, venue, time, ignore_potential=False):
        # If the existing proposal is identical to the scheduled, clear proposed
        if (
            str(proposal.scheduled_venue) == str(proposal.potential_venue)
            and proposal.scheduled_time == proposal.potential_time
        ):
            proposal.potential_venue = None
            proposal.potential_time = None

        if not ignore_potential:
            previous_venue = proposal.potential_venue or proposal.scheduled_venue
            previous_time = proposal.potential_time or proposal.scheduled_time
        else:
            previous_venue = proposal.scheduled_venue
            previous_time = proposal.scheduled_time

        previous_venue_name = None
        if previous_venue:
            previous_venue_name = previous_venue.name

        parsed_time = parser.parse(time)

        # Nothing changed
        if str(venue) == str(previous_venue) and parsed_time == previous_time:
            return False

        proposal.potential_venue = venue
        proposal.potential_time = parsed_time

        app.logger.info(
            'Moved "%s": "%s" at "%s" -> "%s" at "%s"'
            % (
                proposal.title,
                previous_venue_name,
                previous_time,
                proposal.potential_venue.name,
                proposal.potential_time,
            )
        )

        return True

    def apply_changes(self, schedule, ignore_potential=False):
        changes = False
        for event in schedule:
            if "time" not in event or not event["time"]:
                continue
            if "venue" not in event or not event["venue"]:
                continue

            proposal = Proposal.query.filter_by(id=event["id"]).one()
            venue = Venue.query.get(event["venue"])
            changes |= self.handle_schedule_change(proposal, venue, event["time"], ignore_potential)

        if not changes:
            app.logger.info("No schedule changes generated")

    def run(self, persist, ignore_potential, type):
        self.set_rough_durations()

        sm = SlotMachine()
        data = self.get_scheduler_data(ignore_potential, type)
        if len(data) == 0:
            app.logger.error("No talks to schedule!")
            return

        new_schedule = sm.schedule(data)
        self.apply_changes(new_schedule, ignore_potential)

        if persist:
            db.session.commit()
        else:
            app.logger.info("DRY RUN: Pass the `-p` flag to persist these changes")
            db.session.rollback()
