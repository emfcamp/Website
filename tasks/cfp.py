# coding=utf-8
from unicodecsv import DictReader

from faker import Faker
from flask import render_template, current_app as app
from flask_mail import Message
from flask_script import Command, Option

from main import db, mail
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
            filter(Proposal.type.in_(['talk', 'workshop'])).all()

        for proposal in proposals:
            user = proposal.user

            msg = Message("We need information about your EMF %s '%s'" % (proposal.type, proposal.title),
                          sender=app.config['SPEAKERS_EMAIL'],
                          recipients=[user.email])

            msg.body = render_template("emails/cfp-check-your-slot.txt", user=user, proposal=proposal)

            app.logger.info('Emailing %s about proposal %s', user.email, proposal.title)
            mail.send(msg)
            db.session.commit()

# Gathering information
class EmailSpeakersAboutFinalising(Command):

    def run(self):
        proposals = Proposal.query.filter(Proposal.scheduled_duration.isnot(None)).\
            filter(Proposal.state.in_(['accepted'])).\
            filter(Proposal.type.in_(['talk', 'workshop'])).all()

        for proposal in proposals:
            user = proposal.user

            msg = Message("We need more information about your EMF %s '%s'!" % (proposal.type, proposal.title),
                          sender=app.config['SPEAKERS_EMAIL'],
                          recipients=[user.email])

            msg.body = render_template("emails/cfp-please-finalise.txt", user=user, proposal=proposal)

            app.logger.info('Emailing %s about proposal %s', user.email, proposal.title)
            mail.send(msg)
            db.session.commit()


class SetRoughDurations(Command):
    def run(self):
        proposals = Proposal.query.filter_by(scheduled_duration=None, type='talk').\
            filter(Proposal.state.in_(['accepted', 'finished'])).all()

        for proposal in proposals:
            proposal.scheduled_duration = ROUGH_LENGTHS[proposal.length]
            app.logger.info('Setting duration for talk "%s" to "%s"' % (proposal.title, proposal.scheduled_duration))

        db.session.commit()


class RejectUnacceptedProposals(Command):

    def run(self):
        proposals = Proposal.query.filter(Proposal.state.in_(['reviewed'])).all()

        for proposal in proposals:
            proposal.set_state('rejected')
            proposal.has_rejected_email = True

            user = proposal.user

            app.logger.info('Emailing %s about rejecting proposal %s', user.email, proposal.title)
            send_email_for_proposal(proposal, reason="rejected")
            db.session.commit()
