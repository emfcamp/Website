# coding=utf-8
from __future__ import division, absolute_import, print_function, unicode_literals
from datetime import datetime
from dateutil.parser import parse
from main import cache, db
from flask import current_app as app
# from models.ticket import TicketType
from models.product import Product, ProductGroup

class SiteState(db.Model):
    __tablename__ = 'site_state'
    name = db.Column(db.String, primary_key=True)
    state = db.Column(db.String)

    def __init__(self, name, state=None):
        self.name = name
        self.state = state


VALID_STATES = {
    'site_state': ["before-sales", "sales", "event", "after-event"],
    'sales_state': ["sold-out", "sales-ended", "unavailable", "available"],
}

def config_date(key):
    return parse(app.config.get(key))

def calc_site_state(date):
    """ Logic to set the state of the homepage based on date. """
    if date < config_date('SALES_START'):
        return "before-sales"
    elif date < config_date('EVENT_START'):
        return "sales"
    elif date < config_date('EVENT_END'):
        return "event"
    else:
        return "after-event"

def calc_sales_state(date):
    site_capacity = ProductGroup.get_by_name('general')
    if site_capacity.get_total_remaining_capacity() < 1:
        # We've hit capacity - no more tickets will be sold
        return "sold-out"
    elif date > config_date('EVENT_END'):
        return "sales-ended"
    elif Product.get_by_name('full').get_cheapest_price('GBP') is None:
        # Tickets not currently available, probably just for this round, but we haven't hit site capacity
        return "unavailable"
    else:
        return "available"


@cache.cached(timeout=60, key_prefix='get_states')
def get_states():
    states = SiteState.query.all()
    states = {s.name: s.state for s in states}

    date = datetime.utcnow()

    if states.get('site_state') is None:
        states['site_state'] = calc_site_state(date)

    if states.get('sales_state') is None:
        states['sales_state'] = calc_sales_state(date)

    return states

def refresh_states():
    key = get_states.make_cache_key()
    cache.delete(key)

def get_site_state():
    states = get_states()
    return states['site_state']

def get_sales_state():
    states = get_states()
    return states['sales_state']

