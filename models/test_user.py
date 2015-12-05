# coding=utf-8
from __future__ import division, absolute_import, print_function, unicode_literals
import unittest
from .user import generate_login_code, verify_login_code


class UserTests(unittest.TestCase):

    def test_login_code(self):
        timestamp = 12341235.30
        key = b"asdfsazdf34tfgrsdfgdaG"
        uid = 12345
        code = generate_login_code(key, timestamp, uid)
        self.assertEqual(verify_login_code(key, timestamp, code), uid)
        self.assertEqual(verify_login_code(key, timestamp, "asdf:%s:%s" % (int(timestamp), uid)), None)
        self.assertEqual(verify_login_code(key, timestamp + 60 * 60 * 7, code), None)
