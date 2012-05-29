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
import re

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

  def run(self, filename, doit, quiet):
    self.doit = doit
    self.quiet = quiet
    data = ofxparse.OfxParser.parse(file(filename))
    for t in data.account.statement.transactions:
      # field mappings:
      # 
      # NAME 		: payee  <-- the ref we want
      # TRNTYPE 	: type   <-- other (?)
      # MEMO		: memo   <-- ?
      # FITID		: id     <-- also ?
      # TRNAMT		: amount <-- this is important...
      # DTPOSTED	: date   
      self.reconcile(t.payee, Decimal(t.amount), t)

  def find_payment(self, name):
    name = name.upper()
    found = re.findall('[%s]{4}-?[%s]{4}' % (safechars, safechars), name)
    for f in found:
      bankref = f.replace('-', '')
      try:
        return BankPayment.query.filter_by(bankref=bankref).one()
      except NoResultFound:
        continue
    else:
      raise ValueError('No matches found')

  def reconcile(self, ref, amount, t):
    if t.type == 'other':
      try:
        payment = self.find_payment(ref)
      except Exception, e:
        if not self.quiet:
          print "Exception matching ref %s paid %d: %s" % (repr(ref), amount, e)
      else:
        user = payment.user
        print u"user %s paid %d with ref %s" % (user.name, amount, ref)
        #
        # so now we have the ref and an amount
        #
        unpaid = payment.tickets.all()
        total = Decimal(0)
        for t in unpaid:
          if t.paid == False:
            total += Decimal(str(t.type.cost_pence / 100.0))
          else:
            print "attempt to pay for ticket twice: %d" % (t.id)

        if total == 0:
          # nothing owed, so an old payment...
          return
          
        if total != amount:
          print "tried to reconcile payment %s for %s, but amount paid (%d) didn't match amount owed (%d)" % (ref, user.name, amount, total)
        else:
          # all paid up.
          if not self.quiet:
            print "user %s paid for %d tickets (%s)" % (user.name, len(unpaid), ref)
          if self.doit:
            # not sure why we have to do this, or why the object is already in a session.
            s = db.object_session(unpaid[0])
            for t in unpaid:
              t.paid = True
            payment.state = "paid"
            s.commit()
            # send email
            # tickets-paid-email-banktransfer.txt
            msg = Message("EMFCamp 2012 ticket purchase update.", \
                          sender=("EMF Camp 2012", app.config.get('EMAIL')), \
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
    print output

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
