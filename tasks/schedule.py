# coding=utf-8
import json

from dateutil import parser
from flask import render_template, current_app as app
from flask_script import Command, Option
from flask_mail import Message

from slotmachine import SlotMachine

from main import db, mail
from models.cfp import Proposal, Venue

class ImportVenues(Command):
    venues = [
        ('Stage A', ['talk', 'performance'], 100),
        ('Stage B', ['talk'], 99),
        ('Stage C', ['talk'], 98),
        ('Workshop 1', ['workshop'], 97),
        ('Workshop 2', ['workshop'], 96),
        ('Workshop 3', ['youthworkshop'], 95),
    ]

    def run(self):
        for name, type, priority in self.venues:
            type_str = ','.join(type)
            if (Venue.query.filter_by(name=name, type=type_str).all()):
                continue

            venue = Venue()
            venue.name = name
            venue.type = type_str
            venue.priority = priority
            db.session.add(venue)
            app.logger.info('Adding venue "%s" as type "%s"' % (name, type))

        db.session.commit()


class SetRoughDurations(Command):
    def run(self):
        length_map = {
            '> 45 mins': 60,
            '25-45 mins': 30,
            '10-25 mins': 20,
            '< 10 mins': 10
        }

        proposals = Proposal.query.filter_by(scheduled_duration=None, type='talk').\
            filter(Proposal.state.in_(['accepted', 'finished'])).all()

        for proposal in proposals:
            proposal.scheduled_duration = length_map[proposal.length]
            app.logger.info('Setting duration for talk "%s" to "%s"' % (proposal.title, proposal.scheduled_duration))

        db.session.commit()

class OutputSchedulerData(Command):
    def run(self):
        proposals = Proposal.query.filter(Proposal.scheduled_duration.isnot(None)).\
            filter(Proposal.state.in_(['finished', 'accepted'])).\
            filter(Proposal.type.in_(['talk', 'workshop'])).all()

        proposal_data = []
        for proposal in proposals:
            export = {
                'id': proposal.id,
                'duration': proposal.scheduled_duration,
                'speakers': [ proposal.user.id ],
                'title': proposal.title,
                'valid_venues': [ v.id for v in proposal.get_allowed_venues() ],
                'time_ranges': [
                    {"start": str(p.start), "end": str(p.end)} for p in proposal.get_allowed_time_periods_with_default()
                ],
            }

            if proposal.scheduled_venue:
                export['venue'] = proposal.scheduled_venue
            if proposal.potential_venue:
                export['venue'] = proposal.potential_venue

            if proposal.scheduled_time:
                export['time'] = str(proposal.scheduled_time)
            if proposal.potential_time:
                export['time'] = str(proposal.potential_time)

            proposal_data.append(export)

        with open('schedule.json', 'w') as outfile:
            json.dump(proposal_data, outfile, sort_keys=True, indent=4, separators=(',', ': '))

        db.session.commit()

class ImportSchedulerData(Command):
    option_list = [
        Option('-f', '--file', dest='filename',
            help='The .json file to load',
            default='schedule.json'),
        Option('-p', '--persist', dest='persist', action='store_true',
            help='Persist the changes rather than doing a dry run')
    ]

    def run(self, filename, persist):
        schedule = json.load(open(filename))

        for event in schedule:
            if 'time' not in event or not event['time']:
                continue
            if 'venue' not in event or not event['venue']:
                continue

            proposal = Proposal.query.filter_by(id=event['id']).one()

            # Keep history of the venue while updating
            current_scheduled_venue = None
            previous_potential_venue = None
            if proposal.scheduled_venue:
                current_scheduled_venue = proposal.scheduled_venue
            if proposal.potential_venue:
                previous_potential_venue = proposal.potential_venue

            proposal.potential_venue = event['venue']
            if str(proposal.potential_venue) == str(current_scheduled_venue):
                proposal.potential_venue = None

            # Same for time
            previous_potential_time = proposal.potential_time
            proposal.potential_time = parser.parse(event['time'])
            if proposal.potential_time == proposal.scheduled_time:
                proposal.potential_time = None

            # Then say what changed
            if str(proposal.potential_venue) != str(previous_potential_venue) or proposal.potential_time != previous_potential_time:
                previous_venue_name = new_venue_name = None
                if previous_potential_venue:
                    previous_venue_name = Venue.query.filter_by(id=previous_potential_venue).one().name
                if proposal.potential_venue:
                    new_venue_name = Venue.query.filter_by(id=proposal.potential_venue).one().name

                # And we want to try and make sure both are populated
                if proposal.potential_venue and not proposal.potential_time:
                    proposal.potential_time = proposal.scheduled_time
                if proposal.potential_time and not proposal.potential_venue:
                    proposal.potential_venue = proposal.scheduled_venue
                app.logger.info('Moved "%s": "%s" on "%s" -> "%s" on "%s"' % (proposal.title, previous_venue_name, previous_potential_time, new_venue_name, proposal.potential_time))

        if persist:
            db.session.commit()
        else:
            app.logger.info("DRY RUN: `make importschedulerdata` to persist these")
            db.session.rollback()

class RunScheduler(Command):
    def run(self):
        sm = SlotMachine()
        sm.schedule(app.config['EVENT_START'], 'schedule.json', 'schedule.json')

class ApplyPotentialSchedule(Command):
    def run(self):
        proposals = Proposal.query.filter(
            (Proposal.potential_venue.isnot(None) | Proposal.potential_time.isnot(None))).\
            filter(Proposal.scheduled_duration.isnot(None)).\
            filter(Proposal.state.in_(['accepted', 'finished'])).\
            all()

        for proposal in proposals:
            user = proposal.user

            previously_unscheduled = True
            if proposal.scheduled_venue or proposal.scheduled_time:
                previously_unscheduled = False

            if proposal.potential_venue:
                proposal.scheduled_venue = proposal.potential_venue
                proposal.potential_venue = None

            if proposal.potential_time:
                proposal.scheduled_time = proposal.potential_time
                proposal.potential_time = None

            venue_name = Venue.query.filter_by(id=proposal.scheduled_venue).one().name

            if previously_unscheduled:
                msg = Message("Your EMF %s has been scheduled ('%s')" % (proposal.type, proposal.title),
                              sender=app.config['SPEAKERS_EMAIL'],
                              recipients=[user.email])

                msg.body = render_template("emails/cfp-slot-scheduled.txt", user=user, proposal=proposal, venue_name=venue_name)
                app.logger.info('Emailing %s about proposal %s being scheduled', user.email, proposal.title)
            else:
                msg = Message("Your EMF %s slot has been moved ('%s')" % (proposal.type, proposal.title),
                              sender=app.config['SPEAKERS_EMAIL'],
                              recipients=[user.email])

                msg.body = render_template("emails/cfp-slot-moved.txt", user=user, proposal=proposal, venue_name=venue_name)
                app.logger.info('Emailing %s about proposal %s moving', user.email, proposal.title)

            mail.send(msg)
            db.session.commit()
