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

from decimal import Decimal
import re, os, random
from datetime import datetime

from main import app
from models import User, TicketType, Ticket, TicketPrice
from models.payment import Payment, BankPayment, GoCardlessPayment, safechars
from sqlalchemy import text

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
          print "Exception matching ref %s paid %.2f: %s" % (repr(ref), amount, e)
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
            total += Decimal(str(t.type.cost))
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
    self.make_test_user()
    for p in self.user.payments.all():
      if p.provider == "gocardless":
        for t in ("tickets-purchased-email-gocardless.txt", "tickets-paid-email-gocardless.txt"):
          print "template:", t
          print
          self.test(t, p)
          print
          print "*" * 42
          print
      elif p.provider == "banktransfer":
        for t in ("tickets-purchased-email-banktransfer.txt", "tickets-paid-email-banktransfer.txt"):
          print "template:", t
          print
          self.test(t, p)
          print
          print "*" * 42
          print
    
    t = "welcome-email.txt"
    print  "template:", t
    print
    output = render_template(t, user = self.user)
    print output

  def make_test_user(self):
    try:
      user = User.query.filter(User.email == "test@example.com").one()
    except NoResultFound:
      user = User('test@example.com', 'testuser')
      user.set_password('happycamper')
      #
      # hack around sqlalchamey session stuff
      #
      foo = TicketType.query.filter(TicketType.name == 'Prepay Camp Ticket').one()
      sess = db.object_session(foo)
      sess.add(user)

      amounts = {
        "prepayfull" : TicketType.query.filter(TicketType.name == 'Full Camp Ticket (prepay)').one().cost,
        "full" : TicketType.query.filter(TicketType.name == 'Full Camp Ticket').one().cost
      }
      #
      # TODO: needs to cover:
      #
      # single full ticket, no prepay
      # single full ticket with prepay
      # multiple full tickets, no prepay
      # multiple full tickets, with prepay
      # multiple full tickets, some prepay
      #
      # kids & campervans?
      #
      
      # full, prepay
      for full, pp in ((1,0), (0,1), (3,0), (0,3), (2,1)):
        for pt in (BankPayment, GoCardlessPayment):
          total = (full * amounts['full']) + (pp * amounts['prepayfull'])
          payment = pt(total)
          payment.state = "inprogress"
          if payment.provider == "gocardless":
            payment.gcid = "%3dSDJADG" % (int(random.random() * 1000 ))
          sess.add(payment)
          
          tt = 'Full Camp Ticket'
          for i in range(full):
            t = Ticket(type_id = TicketType.query.filter(TicketType.name == tt).one().id)
            t.payment = payment
            t.expires = datetime.utcnow() + timedelta(days=app.config.get('EXPIRY_DAYS'))
            user.tickets.append(t)
            
          tt = 'Full Camp Ticket (prepay)'
          for i in range(pp):
            t = Ticket(type_id = TicketType.query.filter(TicketType.name == tt).one().id)
            t.payment = payment
            t.expires = datetime.utcnow() + timedelta(days=app.config.get('EXPIRY_DAYS'))
            user.tickets.append(t)

          user.payments.append(payment)

      sess.commit()

    self.user = user
    print user.name
    for p in user.payments.all():
      print p.provider, p.amount
      print p.tickets.all()
      
  def test(self, template, payment):
    output = render_template(template, user = self.user, payment=payment)
    print "To: \"%s\" <%s>" % (self.user.name, self.user.email)
    print
    print output.encode("utf-8")

class CreateTickets(Command):
    def run(self):
        #
        # if you change these, change ticket_forms in views/tickets.py as well.
        #

        data = [
            #(name, capacity, max per person, GBP, EUR, Description)
            ('Prepay Camp Ticket', 250, 4, 30.00, 40.00, None),
            ('Full Camp Ticket (prepay)', 250, 4, 60.00, 75.00, None),
            ('Full Camp Ticket', 499 - 20, 4, 95.00, 120.00, None),
            ('Under-14 Camp Ticket', 30, 4, 47.50, 60.00,
                "All children must be accompanied by an adult."),
            ('Campervan Ticket', 5, 1, 30.00, 40.00,
                "Space for campervans is extremely limited. We'll email you for details of your requirements."),
            ('Friday Ticket', 30, 4, 40.00, 50.00,
                "This ticket does not include camping"),
            ('Saturday Ticket', 30, 4, 40.00, 50.00,
                "This ticket does not include camping"),
            ('Sunday Ticket', 30, 4, 40.00, 50.00,
                "This ticket does not include camping"),
            ('Full Camp Ticket (UCL)', 25, 4, 85.00, 110.00,
                "Discounted ticket"),
            ('Full Camp Ticket (Hackspace)', 25, 4, 90.00, 115.00,
                "Discounted ticket"),
            # Until we have ticket codes, please add at the end so we can rebuild the table
            #('Full Camp Ticket (latecomer)', 499 - 20, 4, 100.00),
            #('Donation'),
            #('Parking Ticket', 25, 4, 10.00,
            #    "We're trying to keep cars on-site to a minimum. "
            #    "Please use the nearby carpark or find someone to share with if possible."),
        ]

        types = []
        for row in data:
            tt = TicketType(*row[0:3], notice=row[5])
            tt.prices = [TicketPrice(tt, 'GBP', row[3]), TicketPrice(tt, 'EUR', row[4])]
            types.append(tt)

        for tt in types:
            try:
                TicketType.query.filter_by(name=tt.name).one()
            except NoResultFound, e:
                db.session.add(tt)
                db.session.commit()

        print 'Tickets created'

class WarnExpire(Command):
  """
    Warn about Expired tickets
  """
  def run(self):
    print "warning about expired Tickets"
    seen = {}
    expired = Ticket.query.filter(Ticket.expires <= datetime.utcnow(), Ticket.paid == False).all()
    for t in expired:
      # test that the ticket has a payment... not all do.
      if t.payment:
        if t.payment.id not in seen:
          seen[t.payment.id] = True

    for p in seen:
      p = Payment.query.get(p)
      print "emailing %s <%s> about payment %d" % (p.user.name, p.user.email, p.id)
      # race condition, not all ticket may of expired, but if any of
      # them have we will warn about all of them.
      # not really a problem tho.
      
      msg = Message("Electromagnetic Field ticket purchase update", \
                      sender=app.config.get('TICKETS_EMAIL'), \
                      recipients=[p.user.email]
                  )
      msg.body = render_template("tickets-expired-warning.txt", payment=p)
      mail.send(msg)

class Expire(Command):
  """
    Expire Expired Tickets.
  """
  def run(self):
    print "expiring expired tickets"
    print
    seen = {}
    s = None
    expired = Ticket.query.filter(Ticket.expires <= datetime.utcnow(), Ticket.paid == False).all()
    for t in expired:
      # test that the ticket has a payment... not all do.
      if t.payment:
        if t.payment.id not in seen:
          seen[t.payment.id] = True

    for p in seen:
      p = Payment.query.get(p)
      print "expiring %s payment %d" % (p.provider, p.id)
      p.state = "expired"
      if not s:
        s = db.object_session(p)

      for t in p.tickets:
        print "deleting expired %s ticket %d" % (t.type.name, t.id)
        s.delete(t)

    if s:
      s.commit()

class MakeAdmin(Command):
  """
    Make userid one an admin for testing purposes.
  """
  option_list = (Option('-u', '--userid', dest='userid', help="The userid to make an admin (defaults to 1)"),)
  def run(self, userid):
    if not userid:
      userid = 1
    user = User.query.get(userid)
    user.admin = True
    s = db.object_session(user)
    s.commit()

    print 'userid 1 (%s) is now an admin' % (user.name)

class SendPrepayReminder(Command):

    def run(self):
        query = text("""select id from "user" where exists 
                        (select 1 from ticket, ticket_type where ticket.user_id = "user".id 
                            and ticket.type_id = ticket_type.id and 
                            ticket_type.name = 'Prepay Camp Ticket' and ticket.paid = true)
                    and not exists 
                        (select 1 from ticket, ticket_type where ticket.user_id = "user".id
                            and ticket.type_id = ticket_type.id and
                            ticket_type.name = 'Full Camp Ticket (prepay)')""")

        for row in db.engine.execute(query):
            user = User.query.filter_by(id=row[0]).one()
            msg = Message("Electromagnetic Field Ticket Update",
                          sender=app.config.get('TICKETS_EMAIL'),
                          recipients=[user.email]
                         )
            msg.body = render_template("tickets-prepay-reminder.txt",
                            user = user, tickets=user.tickets)
            print "Sending to", user.email, "..."
            mail.send(msg)

if __name__ == "__main__":
  manager.add_command('reconcile', Reconcile())
  manager.add_command('warnexpire', WarnExpire())
  manager.add_command('expire', Expire())
  manager.add_command('testemails', TestEmails())
  manager.add_command('createtickets', CreateTickets())
  manager.add_command('makeadmin', MakeAdmin())
  manager.add_command('prepayreminder', SendPrepayReminder())
  manager.run()
