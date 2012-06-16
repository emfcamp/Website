#!/usr/bin/env python
# coding=utf-8
#
# reconcile an ofx file against pending payments
#

import ofxparse, sys
from flaskext.script import Command, Manager, Option
from flask import Flask, render_template
from flask.ext.sqlalchemy import SQLAlchemy
from flaskext.mail import Mail, Message
from sqlalchemy.orm.exc import NoResultFound
from jinja2 import Environment, FileSystemLoader

from decimal import Decimal
import re, os

from main import app, mail
from models import User, TicketType
from models.payment import Payment, BankPayment, safechars

#app = Flask(__name__)
#app.config.from_envvar('SETTINGS_FILE')
db = SQLAlchemy(app)
mail = Mail(app)

manager = Manager(app)

class Reconcile(Command):
  """
    Reconcile transactions in a .ofx file against the emfcamp db
  """
  option_list = (Option('-f', '--file', dest='filename', help="The .ofx file to load"),
                 Option('-d', '--doit', action='store_true', help="set this to actually change the db"),
                 Option('-q', '--quiet', action='store_true', help="don't be verbose"),
                )

  badrefs = []
  alreadypaid = 0
  paid = 0
  tickets_paid = 0
  ref_fixups = {}
  overpays = {}

  def run(self, filename, doit, quiet):
    self.doit = doit
    self.quiet = quiet
    
    if os.path.exists("/etc/emf/reffixups.py"):
      sys.path.append("/etc/emf")
      import reffixups
      self.ref_fixups = reffixups.fixups
      self.overpays = reffixups.overpays

    data = ofxparse.OfxParser.parse(file(filename))

    for t in data.account.statement.transactions:
      # field mappings:
      # 
      # NAME 		: payee  <-- the ref we want
      # TRNTYPE 	: type   <-- OTHER or DIRECTDEP
      # MEMO		: memo   <-- ?
      # FITID		: id     <-- also ?
      # TRNAMT		: amount <-- this is important...
      # DTPOSTED	: date   
      self.reconcile(t.payee, Decimal(t.amount), t)
    
    if len(self.badrefs) > 0:
      print
      print "unmatched references:"
      for r in self.badrefs:
        print r
    print
    print "already paid: %d, payments paid this run: %d, tickets: %d" % (self.alreadypaid, self.paid, self.tickets_paid)

  def find_payment(self, name):
    ref = name.upper()
    # looks like this is:
    # NAME REF XXX
    # where name may contain multiple chars, and XXX is a 3 letter code
    # originating bank(?)
    #
    found = re.findall('[%s]{4}-?[%s]{4}' % (safechars, safechars), ref)
    for f in found:
      bankref = f.replace('-', '')
      try:
        return BankPayment.query.filter_by(bankref=bankref).one()
      except NoResultFound:
        continue
    else:
      #
      # some refs are missed typed so we have a list
      # of fixes to make them match
      #
      if name in self.ref_fixups:
        return BankPayment.query.filter_by(bankref=self.ref_fixups[name]).one()
      raise ValueError('No matches found ', name)

  def reconcile(self, ref, amount, t):
    if t.type.lower() == 'other' or t.type.upper() == "DIRECTDEP":
      try:
        payment = self.find_payment(ref)
      except Exception, e:
        if not self.quiet:
          print "Exception matching ref %s paid %d: %s" % (repr(ref), amount, e)
        self.badrefs.append([repr(ref), amount])
      else:
        user = payment.user
        #
        # so now we have the ref and an amount
        #

        if payment.state == "paid" and (Decimal(payment.amount_pence) / 100) == amount:
          # all paid up, great lets ignore this one.
          self.alreadypaid += 1
          return

        unpaid = payment.tickets.all()
        total = Decimal(0)
        for t in unpaid:
          if t.paid == False:
            total += Decimal(str(t.type.cost_pence / 100.0))
          elif not self.quiet:
            if payment.id not in self.overpays:
              print "attempt to pay for paid ticket: %d, user: %s, payment id: %d" % (t.id, payment.user.name, payment.id)

        if total == 0:
          # nothing owed, so an old payment...
          return
          
        if total != amount and payment.id not in self.overpays:
          print "tried to reconcile payment %s for %s, but amount paid (%.2f) didn't match amount owed (%.2f)" % (ref, user.name, amount, total)
        else:
          # all paid up.
          if not self.quiet:
            print "user %s paid for %d (%.2f) tickets with ref: %s" % (user.name, len(unpaid), amount, ref)
          
          self.paid += 1
          self.tickets_paid += len(unpaid)
          if self.doit:
            # not sure why we have to do this, or why the object is already in a session.
            s = db.object_session(unpaid[0])
            for t in unpaid:
              t.paid = True
            payment.state = "paid"
            s.commit()
            # send email
            # tickets-paid-email-banktransfer.txt
            msg = Message("Electromagnetic Field ticket purchase update", \
                          sender=app.config.get('TICKETS_EMAIL'), \
                          recipients=[payment.user.email]
                         )
            msg.body = render_template("tickets-paid-email-banktransfer.txt", \
                          basket={"count" : len(payment.tickets.all()), "reference" : payment.bankref}, \
                          user = payment.user, payment=payment
                         )
            mail.send(msg)

    else:
      if not self.quiet:
        print t, t.type, t.payee
    

class TestEmails(Command):
  """
    Test our email templates
  """

  def run(self):
    for num in (1,2):
      for t in ("tickets-purchased-email-gocardless.txt", "tickets-paid-email-gocardless.txt"):
        print "template:", t
        print
        self.test(t, num, "012SDJADG")
        print
        print "*" * 42
        print

    for num in (1,2):
      for t in ("tickets-purchased-email-banktransfer.txt", "tickets-paid-email-banktransfer.txt"):
        print "template:", t
        print
        self.test(t, num, "A23FBJA4")
        print
        print "*" * 42
        print
    
    t = "welcome-email.txt"
    print  "template:", t
    print
    output = render_template(t, user = {"name" : "J R Hartley", "email": "jrh@flyfishing.net"})
    print output

  def test(self, template, count, ref):
    cost = 30.00 * count
    basket = { "count" : count, "reference" : ref }
    output = render_template(template, basket=basket, user = {"name" : "J R Hartley"}, payment={"amount" : cost, "bankref": ref})
    print output.encode("utf-8")

class CreateTickets(Command):
    def run(self):
        try:
            prepay = TicketType.query.filter_by(name='Prepay Camp Ticket').one()
        except NoResultFound, e:
            prepay = TicketType('Prepay Camp Ticket', 250, 4, 30.00)
            db.session.add(prepay)
            db.session.commit()

        print 'Tickets created'


if __name__ == "__main__":
  manager.add_command('reconcile', Reconcile())
  manager.add_command('testemails', TestEmails())
  manager.add_command('createtickets', CreateTickets())
  manager.run()
