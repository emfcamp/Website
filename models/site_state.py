# coding=utf-8
from __future__ import division, absolute_import, print_function, unicode_literals
from datetime import datetime
from models.ticket import TicketType


def get_site_state(date):
    """ Logic to set the state of the homepage based on date. """
    if date < datetime(2015, 12, 14, 20):
        return "before-sales"
    elif date < datetime(2016, 8, 5):
        return "before-event"
    elif date < datetime(2016, 8, 8, 9):
        return "event"
    else:
        return "after-event"


def get_sales_state(date):
    if TicketType.get_tickets_remaining() < 1:
        return "sold-out"
    elif date > datetime(2016, 8, 7):
        return "sales-ended"
    elif TicketType.get_price_cheapest_full() is None:
        # Tickets not currently available, but we're not sold out
        return "unavailable"
    else:
        return "available"
