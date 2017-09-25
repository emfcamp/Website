# coding=utf-8
import unittest

from .core import get_app
from models.user import User
from models.permission import Permission
from models.user import (
    generate_login_code, verify_login_code, generate_sso_code,
    generate_checkin_code, verify_checkin_code
)

# Tests of the static functions in the user model
class UserFunctionTests(unittest.TestCase):

    def test_generate_login_code(self):
        expect = b'84400-1-Tqf88675CWYb2sge67b9'
        result = generate_login_code('abc', 84400, 1)
        self.assertEqual(expect, result)

        # Check that this will work with strings or bytes
        result = generate_login_code(b'abc', 84400, b'1')
        self.assertEqual(expect, result)

    def test_verify_login_code(self):
        uid = 1
        key = 'abc'
        gen_time = 84400
        good_time = 84401
        code = generate_login_code(key, gen_time, uid)

        good_result = verify_login_code('abc', good_time, code)
        self.assertEqual(good_result, uid)

        malformed_code_result = verify_login_code('abc', good_time, b'84400-1')
        self.assertIsNone(malformed_code_result)

        # Timeout is currently 6 hours
        expired_result = verify_login_code('abc', gen_time * 10, code)
        self.assertIsNone(expired_result)

        bad_code_result = verify_login_code('ab', good_time, code)
        self.assertIsNone(bad_code_result)

    def test_generate_sso_code(self):
        expect = b'84400-1-NB7m7JbQQB4NxKUzFgsv'
        result = generate_sso_code(b'abc', 84400, 1)
        self.assertEqual(expect, result)

    def test_generate_checking_code(self):
        expect = b'AQABZTmTZ7TfdSeh'
        result = generate_checkin_code('abc', 1)
        self.assertEqual(expect, result)

    def test_verify_checkin_code(self):
        uid = 1
        key = 'abc'

        bad_version_code = generate_checkin_code(key, uid, version=255).decode('utf-8')
        bad_version_result = verify_checkin_code(key, bad_version_code)

        self.assertIsNone(bad_version_result)

        good_code = generate_checkin_code(key, uid).decode('utf-8')
        good_result = verify_checkin_code(key, good_code)
        self.assertEqual(uid, good_result)

        # b'AQAB' is (user_id=1,version=1) in a struct & b64 encoded.
        bad_code_result = verify_checkin_code(key, 'bAQABbad')
        self.assertIsNone(bad_code_result)

# Tests of the actual user model
class UserModelTests(unittest.TestCase):
    admin_email = 'admin@example.invalid'
    user_email = 'user@example.invalid'
    permission_name = 'Test_permission'

    def get_users(self):
        return (User.get_by_email(self.admin_email),
                User.get_by_email(self.user_email))

    def setUp(self):
        self.client, self.app, self.db = get_app()
        self.app.testing = True

        with self.app.app_context():
            admin_user = User(self.admin_email, 'TEST_ADMIN_USER')
            admin_user.grant_permission('admin')
            self.db.session.add(admin_user)

            user = User(self.user_email, 'TEST_USER')
            self.db.session.add(user)

            permission = Permission(self.permission_name)
            self.db.session.add(permission)

            self.db.session.commit()

    def tearDown(self):
        with self.app.app_context():
            to_delete = [
                User.query.filter_by(email=self.admin_email).first(),
                User.query.filter_by(email=self.user_email).first(),
                Permission.query.filter_by(name=self.permission_name).first(),
            ]
            for item in to_delete:
                self.db.session.delete(item)
            self.db.session.commit()

    def test_get_user_by_email(self):
        with self.app.app_context():
            expect = User.query.filter_by(email=self.admin_email).first()
            result = User.get_by_email(email=self.admin_email)
            self.assertEqual(expect, result)

    def test_does_user_exist(self):
        with self.app.app_context():
            self.assertTrue(User.does_user_exist(self.admin_email))
            self.assertTrue(User.does_user_exist(self.admin_email.upper()))
            self.assertFalse(User.does_user_exist('sir@notappearing.com'))

    def test_has_permission(self):
        with self.app.app_context():
            # admin has all permissions
            admin_user, user = self.get_users()
            self.assertTrue(admin_user.has_permission('admin'))
            self.assertTrue(admin_user.has_permission(self.permission_name))

            self.assertFalse(user.has_permission('admin'))

    def test_change_permissions(self):
        with self.app.app_context():
            _, user = self.get_users()

            self.assertFalse(user.has_permission(self.permission_name))

            user.grant_permission(self.permission_name)
            self.assertTrue(user.has_permission(self.permission_name))

            user.revoke_permission(self.permission_name)
            self.assertFalse(user.has_permission(self.permission_name))

