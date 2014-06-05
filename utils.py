#!/usr/bin/env python
# coding=utf-8
#
# reconcile an ofx file against pending payments
#

import ofxparse, sys
from flask.ext.script import Command, Manager, Option
from flask import Flask, render_template
from flask.ext.sqlalchemy import SQLAlchemy
from flaskext.mail import Mail, Message
from sqlalchemy.orm.exc import NoResultFound

from decimal import Decimal
import re, os, random
from datetime import datetime, timedelta

from main import app, mail, db
from models import User, TicketType, Ticket, TicketPrice, TicketToken, Role, Shift, ShiftSlot
from models.payment import Payment, BankPayment, GoCardlessPayment, safechars
from sqlalchemy import text

manager = Manager(app)

class CreateDB(Command):
    def run(self):
        from main import db
        db.create_all()

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

  def run(self, filename, doit, quiet):
    self.doit = doit
    self.quiet = quiet
    
    data = ofxparse.OfxParser.parse(file(filename))

    for txn in data.account.statement.transactions:
      # field mappings:
      # 
      # NAME 		: payee  <-- the ref we want
      # TRNTYPE 	: type   <-- OTHER or DIRECTDEP
      # MEMO		: memo   <-- ?
      # FITID		: id     <-- also ?
      # TRNAMT		: amount <-- this is important...
      # DTPOSTED	: date   
      if txn.date > datetime(2014, 1, 1) and txn.amount > 0:
        self.reconcile(txn)
    
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
    found = re.findall('[%s]{4}[- ]?[%s]{4}' % (safechars, safechars), ref)
    for f in found:
      bankref = f.replace('-', '').replace(' ', '')
      try:
        return BankPayment.query.filter_by(bankref=bankref).one()
      except NoResultFound:
        continue
    else:
      raise ValueError('No matches found ', name)

  def reconcile(self, txn):
    if txn.type.lower() not in ('other', 'directdep'):
      if not self.quiet:
        print 'Ignoring "%s" transaction from %s' % (txn.type, txn.payee)
      return

    if txn.payee.startswith("GOCARDLESS LTD "):
      # silently ignore gocardless payments
      return

    try:
      payment = self.find_payment(txn.payee)
    except Exception, e:
      if not self.quiet:
        print "Exception matching %s: %s" % (txn.payee, e)
      self.badrefs.append((txn.payee, txn.amount))
      return

    amount = Decimal(txn.amount)
    if payment.amount != amount:
       print "Tried to reconcile payment %s for %s, but amount paid (%.2f) didn't match amount owed (%.2f)" % (txn.payee, payment.user.name, amount, payment.amount)

    if payment.state == 'paid':
      self.alreadypaid += 1
      return

    if not self.quiet:
      print "User %s paid for payment %s with ref: %s" % (payment.user.name, payment.id, txn.payee)
    
    self.paid += 1
    self.tickets_paid += len(payment.tickets.all())
    if self.doit:
      for t in payment.tickets:
        t.paid = True
      payment.state = "paid"
      db.session.commit()

      msg = Message("Electromagnetic Field ticket purchase update",
                    sender=app.config['TICKETS_EMAIL'],
                    recipients=[payment.user.email])
      msg.body = render_template("tickets-paid-email-banktransfer.txt",
                    user=payment.user, payment=payment)
      mail.send(msg)


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
      db.session.add(user)

      types = {
        "full" : TicketType.query.get('full')
      }
      #
      # FIXME: this is a complete mess
      #
      # TODO: needs to cover:
      #
      # single full ticket
      # multiple full tickets
      #
      # kids & campervans?
      #
      
      # full
      for full in ([1], [0], [3], [0], [2]):
        for pt in (BankPayment, GoCardlessPayment):
          for curr in ['GBP', 'EUR']:
            total = (full * amounts['full'].get_price(curr))
            payment = pt(curr, total)
            payment.state = "inprogress"
            if payment.provider == "gocardless":
              payment.gcid = "%3dSDJADG" % (int(random.random() * 1000 ))
            sess.add(payment)
            
            for i in range(full):
              t = Ticket(code='full')
              t.payment = payment
              if payment.currency == 'GBP':
                  t.expires = datetime.utcnow() + timedelta(days=app.config['EXPIRY_DAYS_TRANSFER'])
              elif payment.currency == 'EUR':
                  t.expires = datetime.utcnow() + timedelta(days=app.config['EXPIRY_DAYS_TRANSFER_EURO'])
              user.tickets.append(t)

            user.payments.append(payment)

      db.session.commit()

    self.user = user
    print user.name
    for p in user.payments.all():
      print p.provider, p.amount
      print p.tickets.all()
      
  def test(self, template, payment):
    output = render_template(template, user=self.user, payment=payment)
    print "To: \"%s\" <%s>" % (self.user.name, self.user.email)
    print
    print output.encode("utf-8")

class CreateTickets(Command):
    def run(self):
        #
        # if you change these, change ticket_forms in views/tickets.py as well.
        #

        data = [
            #(order, code, name, capacity, max per person, GBP, EUR, Description)
            (5, 'full', 'Full Camp Ticket', 200, 10, 95.00, 120.00, None),
            (6, 'full_supporter', 'Full Camp Ticket (Supporter)', 200, 10, 125.00, 160.00,
                "Support this non-profit event by paying a little more. "
                "All money will go towards making EMF more awesome."),
            (10, 'kids_u16', 'Under-16 Camp Ticket', 500, 10, 40.00, 50.00,
                "For visitors born after August 28th, 1998. "
                "All under-16s  must be accompanied by an adult."),
            (15, 'kids_u5', 'Under-5 Camp Ticket', 200, 4, 0, 0,
                "For children born after August 28th, 2009. "
                "All children must be accompanied by an adult."),
            (30, 'parking', 'Parking Ticket', 200, 4, 15.00, 20.00,
                "We're trying to keep cars on-site to a minimum. "
                "Please take public transport or find someone to share with if possible."),
            (35, 'campervan', 'Caravan/Campervan Ticket', 30, 1, 30.00, 40.00,
                "If you bring a caravan, you won't need a separate parking ticket for the towing car."),
        ]

        types = []
        for row in data:
            tt = TicketType(*row[1:5], order=row[0], notice=row[7])
            tt.prices = [TicketPrice('GBP', row[5]), TicketPrice('EUR', row[6])]
            types.append(tt)

        for tt in types:
            existing_tt = TicketType.query.get(tt.code)
            if existing_tt:
                print 'Refreshing TicketType %s' % tt.code
                for f in ['name', 'capacity', 'limit', 'order', 'notice']:
                    cur_val = getattr(existing_tt, f)
                    new_val = getattr(tt, f)
                    if cur_val != new_val:
                        print ' %10s: %r -> %r' % (f, cur_val, new_val)
                        setattr(existing_tt, f, new_val)
            else:
                print 'Adding TicketType %s' % tt.code
                db.session.add(tt)

            db.session.commit()

        print 'Tickets created'
        
class CreateRoles(Command):
    def run(self):
        roles = [
            ('bar', 'Barstaff', 'http://wiki.emfcamp.org/wiki/Team/Volunteers/Bar'),
            ('steward', 'Stewarding', 'http://wiki.emfcamp.org/wiki/Team/Volunteers/Stewards'),
            ('stage', 'Stage helper', 'http://wiki.emfcamp.org/wiki/Team/Volunteers/Stage_Helpers')
            ]
            
        for role in roles:
            try:
                Role.query.filter_by(code=role[0]).one()
            except NoResultFound, e:
                db.session.add(Role(*role))
                db.session.commit()    

class CreateShifts(Command):
    # datetimes are apparently stored in the following format:
    # %04d-%02d-%02d %02d:%02d:%02d.%06d" % (value.year, 
    #                         value.month, value.day,
    #                         value.hour, value.minute, 
    #                         value.second, value.microsecond )
    # only need worry about year, month, day & hour (sod minutes & seconds etc)
    def run(self):
        fmt = "%04d-%02d-%02d %02d:%02d:%02d.%06d"
                        
        days ={"Friday"  :{'m':8, 'd':31},  
               "Saturday":{'m':9, 'd':1 },  
               "Sunday"  :{'m':9, 'd':2 },  
               "Monday"  :{'m':9, 'd':3 }}
        
        dailyshifts = {'steward':
                                {'starts':(2, 5, 8, 11, 14, 17, 20, 23), 
                                 'mins'  :(2, 2, 3,  3,  3,  3,  3,  2),
                                 'maxs'  :(2, 2, 4,  6,  6,  4,  4,  2)
                                 },
                       'bar':
                                {'starts':(12, 15, 18, 21), 
                                 'mins'  :(1,  1,  1,  1),
                                 'maxs'  :(2,  2,  2,  2) 
                                 },
                       'stage':
                                {'starts':(10, 13, 16, 19), 
                                 'mins'  :(1,  1,  1,  1),
                                 'maxs'  :(2,  2,  2,  2) 
                                 },
                        }
        
        shifts = []
        shift_length = timedelta(hours=3)
        for day,date in days.items():
            for role, data in dailyshifts.items():
                if day=="Monday" and not (role == "steward" or role == "parking"):
                    # only parking attendants & stewards needed on Monday
                    continue
                # transform from human readable to python friendly
                data = map(None, *data.values())
                for start, min, max in data:
                    if day=="Friday" and start < 8: 
                        # gates open at 8am Friday
                        continue
                    elif day=="Monday" and start > 11:
                        # last shift is 11->14 Monday
                        continue
                    start_time = datetime(2012, date['m'], date['d'], start)
                    s = ShiftSlot(start_time, min, max, role)
                    shifts.append(s)
        
        for shift in shifts:
            try:
                Shift.query.filter_by(id=shift.id).one()
            except NoResultFound, e:
                db.session.add(shift)
                db.session.commit()    
                    

class CreateTicketTokens(Command):
    def run(self):
        tokens = [
          ('full_ucl', 'ucl1'),
          ('full_ucl', 'ucl2'),
          ('full_ucl', 'ucl3'),
          ('full_hs', 'hs1'),
          ('full_hs', 'hs2'),
          ('full_hs', 'hs3'),
        ]

        for code, token in tokens:
            tt = TicketToken(token, datetime.utcnow() + timedelta(days=7))
            tt.type = TicketType.query.get(code)
            db.session.commit()

        print 'Tokens added'

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
      
      msg = Message("Electromagnetic Field ticket purchase update",
                      sender=app.config['TICKETS_EMAIL'],
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

class SendTickets(Command):

    def run(self):
        query = text("""select distinct "user".id from "user", ticket 
                        where ticket.user_id = "user".id and ticket.paid = true""")

        for row in db.engine.execute(query):
            user = User.query.filter_by(id=row[0]).one()
            msg = Message("Your Electromagnetic Field Ticket",
                          sender=app.config['TICKETS_EMAIL'],
                          recipients=[user.email]
                         )
            user.create_receipt()
            msg.body = render_template("ticket.txt", user=user)
            print "Sending to", user.email, "..."
            mail.send(msg)


if __name__ == "__main__":
  manager.add_command('createdb', CreateDB())
  manager.add_command('reconcile', Reconcile())
  manager.add_command('warnexpire', WarnExpire())
  manager.add_command('expire', Expire())
  manager.add_command('testemails', TestEmails())
  manager.add_command('createtickets', CreateTickets())
  manager.add_command('makeadmin', MakeAdmin())
  manager.add_command('addtokens', CreateTicketTokens())
  manager.add_command('createroles', CreateRoles())
  manager.add_command('createshifts', CreateShifts())
  manager.add_command('sendtickets', SendTickets())
  manager.run()
