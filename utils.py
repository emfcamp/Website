#!/usr/bin/env python
# coding=utf-8
import json
from collections import OrderedDict

from flask_script import Command, Manager, Option
from flask_migrate import MigrateCommand
from flask import current_app as app
from flask_mail import Message

from main import create_app, mail, db
from models import User
from models.permission import Permission
from models.ical import CalendarSource

from utils.banking import (
    CreateBankAccounts, LoadOfx, Reconcile,
)
from utils.cfp import (
    ImportCFP, LockProposals, EmailSpeakersAboutSlot,
    EmailSpeakersAboutFinalising, RejectUnacceptedTalks
)
from utils.dev import CreateDB, MakeFakeUsers, MakeFakeTickets
from utils.schedule import (
    ImportVenues, SetRoughDurations, OutputSchedulerData, ImportSchedulerData,
    RunScheduler, ApplyPotentialSchedule
)
from utils.tickets import (
    CreateTickets, CreateParkingTickets, SendTickets, SendTransferReminder
)


class MakeAdmin(Command):
    """
    Make the first user in the DB an admin for testing purposes
    """
    option_list = (Option('-u', '--user-id', dest='user_id', help="The user_id to make an admin (defaults to first)"),)

    def run(self, user_id):
        if user_id:
            user = User.query.get(user_id)
        else:
            user = User.query.order_by(User.id).first()

        user.grant_permission('admin')
        db.session.commit()

        print('%r is now an admin' % user.name)

class CreatePermissions(Command):
    def run(self):
        for permission in ('admin', 'arrivals', 'cfp_reviewer', 'cfp_anonymiser', 'cfp_schedule'):
            if not Permission.query.filter_by(name=permission).first():
                db.session.add(Permission(permission))

        db.session.commit()

class SendEmails(Command):
    def run(self):
        with mail.connect() as conn:
            for rec in EmailJobRecipient.query.filter(EmailJobRecipient.sent == False):  # noqa
                self.send_email(conn, rec)

    def send_email(self, conn, rec):
        msg = Message(rec.job.subject, sender=app.config['CONTACT_EMAIL'])
        msg.add_recipient(rec.user.email)
        msg.body = rec.job.text_body
        msg.html = rec.job.html_body
        conn.send(msg)
        rec.sent = True
        db.session.add(rec)
        db.session.commit()


class CreateCalendars(Command):
    def run(self):
        icals = json.load(open('calendars.json'))

        for cal in icals:
            existing_calendar = CalendarSource.query.filter_by(url=cal['url']).first()
            if existing_calendar:
                source = existing_calendar
                app.logger.info('Refreshing calendar %s', source.name)
            else:
                source = CalendarSource(cal['url'])
                app.logger.info('Adding calendar %s', cal['name'])

            cal['lat'] = cal.get('lat')
            cal['lon'] = cal.get('lon')

            for f in ['name', 'type', 'priority', 'main_venue', 'lat', 'lon']:
                cur_val = getattr(source, f)
                new_val = cal[f]

                if cur_val != new_val:
                    app.logger.info(' %10s: %r -> %r', f, cur_val, new_val)
                    setattr(source, f, new_val)

            db.session.add(source)

        db.session.commit()

class RefreshCalendars(Command):
    def run(self):
        for source in CalendarSource.query.filter_by(enabled=True).all():
            source.refresh()

        db.session.commit()

class ExportCalendars(Command):
    def run(self):
        data = []
        calendars = CalendarSource.query.filter_by(enabled=True) \
                                  .order_by(CalendarSource.priority, CalendarSource.id)
        for source in calendars:
            source_data = OrderedDict([
                ('name', source.name),
                ('url', source.url),
                ('type', source.type),
                ('priority', source.priority),
                ('main_venue', source.main_venue)])
            if source.lat:
                source_data['lat'] = source.lat
                source_data['lon'] = source.lon

            data.append(source_data)

        json.dump(data, open('calendars.json', 'w'), indent=4, separators=(',', ': '))


if __name__ == "__main__":
    manager = Manager(create_app())
    manager.add_command('createdb', CreateDB())
    manager.add_command('db', MigrateCommand)

    manager.add_command('createbankaccounts', CreateBankAccounts())
    manager.add_command('loadofx', LoadOfx())
    manager.add_command('reconcile', Reconcile())

    manager.add_command('sendtransferreminder', SendTransferReminder())
    manager.add_command('createtickets', CreateTickets())
    manager.add_command('sendtickets', SendTickets())

    manager.add_command('lockproposals', LockProposals())
    manager.add_command('importcfp', ImportCFP())

    manager.add_command('createperms', CreatePermissions())
    manager.add_command('makeadmin', MakeAdmin())
    manager.add_command('makefakeusers', MakeFakeUsers())
    manager.add_command('makefaketickets', MakeFakeTickets())

    manager.add_command('sendemails', SendEmails())

    manager.add_command('emailspeakersaboutslot', EmailSpeakersAboutSlot())
    manager.add_command('emailspeakersaboutfinalising', EmailSpeakersAboutFinalising())
    manager.add_command('rejectunacceptedtalks', RejectUnacceptedTalks())

    manager.add_command('importvenues', ImportVenues())
    manager.add_command('setroughdurations', SetRoughDurations())
    manager.add_command('outputschedulerdata', OutputSchedulerData())
    manager.add_command('importschedulerdata', ImportSchedulerData())
    manager.add_command('runscheduler', RunScheduler())
    manager.add_command('applypotentialschedule', ApplyPotentialSchedule())

    manager.add_command('createcalendars', CreateCalendars())
    manager.add_command('refreshcalendars', RefreshCalendars())
    manager.add_command('exportcalendars', ExportCalendars())

    manager.add_command('createparkingtickets', CreateParkingTickets())
    manager.run()
