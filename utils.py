#!/usr/bin/env python
# coding=utf-8
from flask_script import Manager
from flask_migrate import MigrateCommand

from main import create_app

from tasks.admin import MakeAdmin, CreatePermissions, SendEmails
from tasks.banking import CreateBankAccounts, LoadOfx, Reconcile
from tasks.cfp import (
    ImportCFP, EmailSpeakersAboutSlot, EmailSpeakersAboutFinalising,
    EmailSpeakersAboutReserveList, SetRoughDurations
)
from tasks.dev import MakeFakeData, MakeVolunteerData
from tasks.external_calendars import (
    CreateCalendars, RefreshCalendars, ExportCalendars
)
from tasks.schedule import (
    ImportVenues, RunScheduler, ApplyPotentialSchedule
)
from tasks.tickets import (
    CreateTickets, SendTickets, SendTransferReminder, CancelReservedTickets,
)
from tasks.exportdb import ExportDB


if __name__ == "__main__":
    manager = Manager(create_app())
    manager.add_command('db', MigrateCommand)
    manager.add_command('exportdb', ExportDB())

    manager.add_command('createbankaccounts', CreateBankAccounts())
    manager.add_command('loadofx', LoadOfx())
    manager.add_command('reconcile', Reconcile())

    manager.add_command('sendtransferreminder', SendTransferReminder())
    manager.add_command('cancelreservedtickets', CancelReservedTickets())
    manager.add_command('createtickets', CreateTickets())
    manager.add_command('sendtickets', SendTickets())

    manager.add_command('importcfp', ImportCFP())

    manager.add_command('createperms', CreatePermissions())
    manager.add_command('makeadmin', MakeAdmin())
    manager.add_command('makefakedata', MakeFakeData())
    manager.add_command('makevolunteerdata', MakeVolunteerData())

    manager.add_command('sendemails', SendEmails())

    manager.add_command('emailspeakersaboutslot', EmailSpeakersAboutSlot())
    manager.add_command('emailspeakersaboutfinalising', EmailSpeakersAboutFinalising())
    manager.add_command('emailspeakersaboutreservelist', EmailSpeakersAboutReserveList())

    manager.add_command('importvenues', ImportVenues())
    manager.add_command('runscheduler', RunScheduler())
    manager.add_command('setroughdurations', SetRoughDurations())
    manager.add_command('applypotentialschedule', ApplyPotentialSchedule())

    manager.add_command('createcalendars', CreateCalendars())
    manager.add_command('refreshcalendars', RefreshCalendars())
    manager.add_command('exportcalendars', ExportCalendars())

    manager.run()
