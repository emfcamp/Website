# coding=utf-8
from datetime import datetime, timedelta
from unicodecsv import DictReader

from faker import Faker
from flask import render_template, current_app as app
from flask_mail import Message
from flask_script import Command, Option

from main import db, mail
from models.cfp import (
    Proposal, TalkProposal, WorkshopProposal, InstallationProposal
)
from models.user import User

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


class LockProposals(Command):

    def run(self):
        edit_window = timedelta(days=app.config.get('EDIT_WINDOW', 2))
        app.logger.info('Locking proposals older than %s', edit_window)
        new_proposals = Proposal.query.filter_by(state='new').all()
        lock_count = 0
        for proposal in new_proposals:
            deadline = proposal.created + edit_window

            if datetime.utcnow() > deadline:
                proposal.set_state('locked')

                app.logger.debug('Locking proposal %s', proposal.id)
                db.session.commit()
                lock_count += 1

        app.logger.info('Locked %s proposals', lock_count)


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


class EmailSpeakersAboutFinalising(Command):

    def run(self):
        proposals = Proposal.query.filter(Proposal.scheduled_duration.isnot(None)).\
            filter(Proposal.state.in_(['accepted'])).\
            filter(Proposal.type.in_(['talk', 'workshop'])).all()

        for proposal in proposals:
            user = proposal.user

            msg = Message("We really need information about your EMF %s '%s'!" % (proposal.type, proposal.title),
                          sender=app.config['SPEAKERS_EMAIL'],
                          recipients=[user.email])

            msg.body = render_template("emails/cfp-please-finalise.txt", user=user, proposal=proposal)

            app.logger.info('Emailing %s about proposal %s', user.email, proposal.title)
            mail.send(msg)
            db.session.commit()


class RejectUnacceptedTalks(Command):

    def run(self):
        proposals = Proposal.query.filter(Proposal.state.in_(['reviewed'])).all()

        for proposal in proposals:
            proposal.set_state('rejected')
            proposal.has_rejected_email = True

            user = proposal.user

            msg = Message("Your EMF %s proposal '%s' was not accepted." % (proposal.type, proposal.title),
                          sender=app.config['SPEAKERS_EMAIL'],
                          recipients=[user.email])

            msg.body = render_template("emails/cfp-rejected.txt", user=user, proposal=proposal)

            app.logger.info('Emailing %s about rejecting proposal %s', user.email, proposal.title)
            mail.send(msg)
            db.session.commit()
