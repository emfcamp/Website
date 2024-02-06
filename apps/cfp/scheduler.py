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
    DEFAULT_VENUES,
    VENUE_CAPACITY,
)


class Scheduler(object):
    """Automatic Scheduler

    This class handles scheduling operations by using the SlotMachine constraint solving scheduler.
    """

    def set_rough_durations(self):
        proposals = (
            Proposal.query.filter_by(scheduled_duration=None, type="talk")
            .filter(Proposal.is_accepted)
            .all()
        )

        for proposal in proposals:
            try:
                proposal.scheduled_duration = ROUGH_LENGTHS[proposal.length]
            except KeyError:
                app.logger.warn(
                    f"Invalid proposal length {repr(proposal.length)} for {proposal}, ignoring"
                )
                continue

            app.logger.info(
                'Set duration for talk "%s" to "%s"'
                % (proposal.title, proposal.scheduled_duration)
            )

        db.session.commit()

    def get_scheduler_data(
        self, ignore_potential, type=["talk", "workshop", "youthworkshop"]
    ):
        proposals = (
            Proposal.query.filter(Proposal.scheduled_duration.isnot(None))
            .filter(Proposal.is_accepted)
            .filter(Proposal.type.in_(type))
            .order_by(Proposal.favourite_count.desc())
            .all()
        )

        proposals_by_type = defaultdict(list)
        for proposal in proposals:
            proposals_by_type[proposal.type].append(proposal)

        capacity_by_type = defaultdict(dict)
        for type, venues in DEFAULT_VENUES.items():
            for venue in venues:
                venue_id = Venue.query.filter(Venue.name == venue).one().id
                capacity_by_type[type][venue_id] = VENUE_CAPACITY[venue]

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
            split_count = int(
                len(proposals_by_type[type]) / len(capacity_by_type[type])
            )

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

    def handle_schedule_change(self, proposal, venue, time):
        # Keep history of the venue while updating
        current_scheduled_venue = None
        previous_potential_venue = None
        if proposal.scheduled_venue:
            current_scheduled_venue = proposal.scheduled_venue
        if proposal.potential_venue:
            previous_potential_venue = proposal.potential_venue

        proposal.potential_venue = venue
        if str(proposal.potential_venue) == str(current_scheduled_venue):
            proposal.potential_venue = None

        # Same for time
        previous_potential_time = proposal.potential_time
        proposal.potential_time = parser.parse(time)
        if proposal.potential_time == proposal.scheduled_time:
            proposal.potential_time = None

        if (
            str(proposal.potential_venue) == str(previous_potential_venue)
            and proposal.potential_time == previous_potential_time
        ):
            # Nothing changed
            return False

        previous_venue_name = new_venue_name = None
        if previous_potential_venue:
            previous_venue_name = previous_potential_venue.name
        if proposal.potential_venue:
            new_venue_name = proposal.potential_venue.name

        # And we want to try and make sure both are populated
        if proposal.potential_venue and not proposal.potential_time:
            proposal.potential_time = proposal.scheduled_time
        if proposal.potential_time and not proposal.potential_venue:
            proposal.potential_venue = proposal.scheduled_venue
        app.logger.info(
            'Moved "%s": "%s" at "%s" -> "%s" at "%s"'
            % (
                proposal.title,
                previous_venue_name,
                previous_potential_time,
                new_venue_name,
                proposal.potential_time,
            )
        )
        return True

    def apply_changes(self, schedule):
        changes = False
        for event in schedule:
            if "time" not in event or not event["time"]:
                continue
            if "venue" not in event or not event["venue"]:
                continue

            proposal = Proposal.query.filter_by(id=event["id"]).one()
            venue = Venue.query.get(event["venue"])
            changes |= self.handle_schedule_change(proposal, venue, event["time"])

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
        self.apply_changes(new_schedule)

        if persist:
            db.session.commit()
        else:
            app.logger.info("DRY RUN: Pass the `-p` flag to persist these changes")
            db.session.rollback()
