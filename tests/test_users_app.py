# coding=utf-8
import unittest
import re

from main import Mail
from .core import get_app
from models.user import User


mail = Mail()
login_link_re = r'(https?://[^\s/]*/login[^\s]*)'


class UserAppTests(unittest.TestCase):
    user_email = 'user@example.invalid'

    def setUp(self):
        self.client, self.app, self.db = get_app()
        self.app.testing = True

        with self.app.app_context():
            user = User(self.user_email, 'TEST_USER')
            self.db.session.add(user)

            self.db.session.commit()

    def tearDown(self):
        with self.app.app_context():
            to_delete = [
                User.query.filter_by(email=self.user_email).first(),
            ]
            for item in to_delete:
                self.db.session.delete(item)
            self.db.session.commit()

    def test_login(self):
        url = '/login?next=test'
        with self.app.app_context(), mail.record_messages() as outbox:
            login_get = self.client.get(url)
            form_string = "Enter your email address and we'll email you a login link"
            self.assertIn(form_string, login_get.data.decode('utf-8'))

            form = dict(email=self.user_email)
            self.client.post(url, data=form, follow_redirects=True)

            self.assertEqual(1, len(outbox))
            self.assertEqual(str, type(outbox[0].body))

            match = re.search(login_link_re, outbox[0].body)
            self.assertEqual(1, len(match.groups()), 'Unexpected number of login links')

            login_link_get = self.client.get(match.group(0))
            self.assertEqual(302, login_link_get.status_code)
            self.assertTrue(login_link_get.location.endswith('/test'))

    def test_bad_login(self):
        url = '/login?next=test'
        with self.app.app_context(), mail.record_messages() as outbox:
            # Trying to login with an arbitrary email should look the same
            # as doing so with a valid email.
            form = dict(email='sir@notappearing.com')
            post = self.client.post(url, data=form, follow_redirects=True)

            self.assertEqual(200, post.status_code)
            self.assertEqual(0, len(outbox))

            bad_login_link = self.client.get(url + '&code=84400-1-Tqf88675CWYb2sge67b9')
            self.assertEqual(200, bad_login_link.status_code)
            error_string = "Your login link was invalid. Please note that they expire after 6 hours."
            self.assertIn(error_string, bad_login_link.data.decode('utf-8'))


