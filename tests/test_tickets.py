# coding=utf-8
from __future__ import division, absolute_import, print_function, unicode_literals
import unittest
from datetime import timedelta, datetime
from models.user import User
from models.ticket import Ticket, TicketType
from .core import get_app


class TicketTestCase(unittest.TestCase):

    def setUp(self):
        self.client, self.app, self.db = get_app()
        with self.app.app_context():
            self.user = User('test@example.com', 'NULL')
            self.db.session.add(self.user)
            self.db.session.commit()

    def test_ticket_creation(self):
        with self.app.app_context():
            self.db.session.add(self.user)
            tt = TicketType.query.filter_by(admits='full').first()
            ticket = Ticket(type=tt, user_id=self.user.id)
            self.db.session.add(ticket)
            self.db.session.commit()

            # A ticket without a payment isn't sold...
            assert sum(TicketType.get_ticket_sales().values()) == 0
            assert ticket.id is not None

            ticket.paid = True
            self.db.session.flush()
            # ... but a paid one is
            assert sum(TicketType.get_ticket_sales().values()) == 1

            ticket.expires = datetime.now() - timedelta(minutes=1)
            self.db.session.flush()
            # Expired tickets still count towards capacity
            assert sum(TicketType.get_ticket_sales().values()) == 1

            ticket.paid = False
            self.db.session.flush()
            assert sum(TicketType.get_ticket_sales().values()) == 0

