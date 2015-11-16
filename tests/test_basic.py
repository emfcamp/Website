# coding=utf-8
from __future__ import division, absolute_import, print_function, unicode_literals
import unittest
from .core import get_app


class BasicTestCase(unittest.TestCase):

    def setUp(self):
        self.client, self.app, self.db = get_app()

    def tearDown(self):
        pass

    def test_root(self):
        rv = self.client.get('/')
        assert 'Electromagnetic Field' in rv.data

    def test_tickets(self):
        res = self.client.get('/tickets/choose')
        assert "Full Camp Ticket" in res.data.decode('utf-8')
