# coding=utf-8
from __future__ import division, absolute_import, print_function, unicode_literals
import unittest
from .core import get_app

URLS = [
    '/',
    '/about',
    '/cfp',
    '/login',
    '/metrics'
]


class BasicTestCase(unittest.TestCase):

    def setUp(self):
        self.client, self.app, self.db = get_app()

    def test_url(self):
        for url in URLS:
            rv = self.client.get(url)
            assert rv.status_code == 200, "Fetching %s results in HTTP 200" % url
