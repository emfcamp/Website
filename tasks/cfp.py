# coding=utf-8
from unicodecsv import DictReader

from faker import Faker
from flask import current_app as app
from flask_script import Command, Option

from main import db
from models.cfp import (
    Proposal, TalkProposal, WorkshopProposal, InstallationProposal, ROUGH_LENGTHS
)
from models.user import User
from apps.cfp_review.base import send_email_for_proposal

class ImportCFP(Command):
    option_list = [Option('-f', '--file', dest='filename',
                          help='The .csv file to load',
                          default='tests/2014_proposals.csv'),
                   Option('-s', '--state', dest='state', default='locked',
                          help='The state to import the proposals as')]

    def run(self, filename, state):
        faker = Faker()
        with open(filename) as csvfile:
            # id, title, description, length, need_finance,
            # one_day, type, experience, attendees, size
            reader = DictReader(csvfile)
            count = 0
            for row in reader:
                if Proposal.query.filter_by(title=row['title']).first():
                    continue

                user = User('cfp_%s@test.invalid' % count, faker.name())
                db.session.add(user)

                proposal = TalkProposal() if row['type'] == u'talk' else\
                    WorkshopProposal() if row['type'] == u'workshop' else\
                    InstallationProposal()

                proposal.state = state
                proposal.title = row['title']
                proposal.description = row['description']

                proposal.one_day = True if row.get('one_day') == 't' else False
                proposal.needs_money = True if row.get('need_finance') == 't' else False

                if row['type'] == 'talk':
                    proposal.length = row['length']

                elif row['type'] == 'workshop':
                    proposal.length = row['length']
                    proposal.attendees = row['attendees']

                else:
                    proposal.size = row['size']

                proposal.user = user
                db.session.add(proposal)

                db.session.commit()
                count += 1

        app.logger.info('Imported %s proposals' % count)


# Slot confirmation
class EmailSpeakersAboutSlot(Command):

    def run(self):
        proposals = Proposal.query.filter(Proposal.scheduled_duration.isnot(None)).\
            filter(Proposal.state.in_(['accepted', 'finished'])).\
            filter(Proposal.type.in_(['talk', 'workshop', 'youthworkshop', 'performance'])).all()

        for proposal in proposals:
            send_email_for_proposal(proposal, reason="check-your-slot", from_address=app.config['SPEAKERS_EMAIL'])

# Gathering information
class EmailSpeakersAboutFinalising(Command):

    def run(self):
        proposals = Proposal.query.filter(Proposal.scheduled_duration.isnot(None)).\
            filter(Proposal.state.in_(['accepted'])).\
            filter(Proposal.type.in_(['talk', 'workshop', 'youthworkshop', 'performance'])).all()

        for proposal in proposals:
            send_email_for_proposal(proposal, reason="please-finalise", from_address=app.config['SPEAKERS_EMAIL'])

class EmailSpeakersAboutReserveList(Command):

    def run(self):
        proposals = Proposal.query.\
            filter(Proposal.state.in_(['reviewed'])).\
            filter(Proposal.type.in_(['talk', 'workshop', 'youthworkshop'])).all()

        for proposal in proposals:
            send_email_for_proposal(proposal, reason="reserve-list", from_address=app.config['SPEAKERS_EMAIL'])

class SetRoughDurations(Command):
    def run(self):
        proposals = Proposal.query.filter_by(scheduled_duration=None, type='talk').\
            filter(Proposal.state.in_(['accepted', 'finished'])).all()

        for proposal in proposals:
            proposal.scheduled_duration = ROUGH_LENGTHS[proposal.length]
            app.logger.info('Setting duration for talk "%s" to "%s"' % (proposal.title, proposal.scheduled_duration))

        db.session.commit()
