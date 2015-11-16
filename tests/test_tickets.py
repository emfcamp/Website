# coding=utf-8
from __future__ import division, absolute_import, print_function, unicode_literals
import unittest
from datetime import timedelta, datetime
from .core import get_app


class TicketTestCase(unittest.TestCase):

    def setUp(self):
        self.app, self.db = get_app()
        from models.user import User
        self.user = User('test@example.com', 'NULL')
        self.user.generate_random_password()
        self.db.session.add(self.user)
        self.db.session.commit()

    def test_ticket_creation(self):
        from models.ticket import Ticket, TicketType
        tt = TicketType.query.filter_by(admits='full').first()
        ticket = Ticket(type=tt, user_id=self.user.id)
        self.db.session.add(ticket)
        self.db.session.commit()
        assert ticket.id is not None
        assert sum(TicketType.get_ticket_sales().values()) == 1
        ticket.expires = datetime.now() - timedelta(minutes=1)
        self.db.session.flush()
        assert sum(TicketType.get_ticket_sales().values()) == 0
