#!/usr/bin/env python
# coding=utf-8
from flask_script import Manager
from flask_migrate import MigrateCommand

from main import create_app

from tasks.admin import MakeAdmin, CreatePermissions, SendEmails
from tasks.banking import CreateBankAccounts, LoadOfx, Reconcile
from tasks.cfp import (
    ImportCFP, LockProposals, EmailSpeakersAboutSlot,
    EmailSpeakersAboutFinalising, RejectUnacceptedTalks
)
from tasks.dev import CreateDB, MakeFakeUsers, MakeFakeTickets
from tasks.external_calendars import (
    CreateCalendars, RefreshCalendars, ExportCalendars
)
from tasks.schedule import (
    ImportVenues, SetRoughDurations, OutputSchedulerData, ImportSchedulerData,
    RunScheduler, ApplyPotentialSchedule
)
from tasks.tickets import (
    CreateTickets, CreateParkingTickets, SendTickets, SendTransferReminder
)
from tasks.exportdb import ExportDB


if __name__ == "__main__":
    manager = Manager(create_app())
    manager.add_command('createdb', CreateDB())
    manager.add_command('db', MigrateCommand)
    manager.add_command('exportdb', ExportDB())

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
