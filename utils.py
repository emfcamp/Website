#!/usr/bin/env python
# coding=utf-8
import json
from collections import OrderedDict

from flask_script import Command, Manager
from flask_migrate import MigrateCommand
from flask import current_app as app

from main import create_app, db
from models.ical import CalendarSource

from utils.admin import MakeAdmin, CreatePermissions, SendEmails
from utils.banking import CreateBankAccounts, LoadOfx, Reconcile
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
