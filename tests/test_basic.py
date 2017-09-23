# coding=utf-8
from __future__ import division, absolute_import, print_function, unicode_literals
import unittest
from .core import get_app

URLS = [
    '/',
    '/about',
    '/cfp',
    '/login',
    '/sponsors'
]


class BasicTestCase(unittest.TestCase):

    def setUp(self):
        self.client, self.app, self.db = get_app()

    def tearDown(self):
        pass

    def test_root(self):
        for url in URLS:
            rv = self.client.get(url)
            assert 'Electromagnetic Field' in rv.data.decode('utf-8')
