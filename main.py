from flask import Flask
from flaskext.login import LoginManager
from flaskext.mail import Mail
from flask.ext.sqlalchemy import SQLAlchemy
from sqlalchemy.orm.exc import NoResultFound
from flask.ext.assets import Environment, Bundle

import logging

logging.basicConfig(level=logging.NOTSET)

app = Flask(__name__)
app.config.from_envvar('SETTINGS_FILE')

login_manager = LoginManager()
login_manager.setup_app(app, add_context_processor=True)
app.login_manager.login_view = 'login'

@app.context_processor
def utility_processor():
    def format_price(amount, currency=u'\xa3', after=False):
        amount = u'{0:.2f}'.format(amount)
        if after:
            return amount + currency
        return currency + amount

    def format_bankref(bankref):
        return '%s-%s' % (bankref[:4], bankref[4:])

    return dict(
        format_price=format_price,
        format_bankref=format_bankref,
    )


db = SQLAlchemy(app)

mail = Mail(app)

assets = Environment(app)
css = Bundle('css/bootstrap.css', 'css/main.css', output='gen/packed.css')
assets.register('css_all', css)

js = Bundle('js/jquery-1.7.2.js', 'js/bootstrap.js', output='gen/packed.js')
assets.register('js_all', js)


import gocardless

gocardless.environment = app.config['GOCARDLESS_ENVIRONMENT']
gocardless.set_details(app_id=app.config['GOCARDLESS_APP_ID'],
                        app_secret=app.config['GOCARDLESS_APP_SECRET'],
                        access_token=app.config['GOCARDLESS_ACCESS_TOKEN'],
                        merchant_id=app.config['GOCARDLESS_MERCHANT_ID'])

from views import *
from models import *
db.create_all()

if TicketType.query.count() == 0:
    # no ticket types setup, so set some up
    # the - 20 here is from the budget
    camp = TicketType("Camp Ticket", 499 - 20, 99.42)
    # onsite parking i guess?
    parking = TicketType("Car Parking", 25, 25.00)
    # onsite i guess?
    camper = TicketType("Caravan/Campervan", 25, 25.00)
    db.session.add(camp)
    db.session.add(parking)
    db.session.add(camper)
    db.session.commit()

@login_manager.user_loader
def load_user(userid):
    return User.query.filter_by(id=userid).first()

if __name__ == "__main__":
    app.run()
