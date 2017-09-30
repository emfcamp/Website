# coding=utf-8
from __future__ import division, absolute_import, print_function, unicode_literals
from datetime import datetime
from main import cache, db
# from models.ticket import TicketType
from models.product import ProductGroup

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


def calc_site_state(date):
    """ Logic to set the state of the homepage based on date. """
    return "before-sales"

def calc_sales_state(date):
    # if TicketType.get_tickets_remaining() < 1:
    site_capacity = ProductGroup.get_by_name('site_capacity')
    if site_capacity.get_total_remaining_capacity() < 1:
        # We've hit capacity - no more tickets will be sold
        return "sold-out"
    elif date > datetime(2016, 8, 7):
        return "sales-ended"
    elif site_capacity.get_price_cheapest_full() is None:
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

