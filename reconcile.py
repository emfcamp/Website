#!/usr/bin/env python
# coding=utf-8
#
# reconcile an ofx file against pending payments
#

import ofxparse, sys
from flaskext.script import Command, Manager, Option
from flask import Flask
from flask.ext.sqlalchemy import SQLAlchemy
from flaskext.mail import Mail
from sqlalchemy.orm.exc import NoResultFound

from decimal import Decimal
import re

from main import app
from models import User
from models.payment import Payment, safechars

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
        return Payment.query.filter_by(bankref=bankref).one()
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

    else:
      if not self.quiet:
        print t, t.type, t.payee

if __name__ == "__main__":
  manager.add_command('reconcile', Reconcile())
  manager.run()
