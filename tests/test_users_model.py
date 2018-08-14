from models.user import User
from models.user import (
    generate_login_code, verify_login_code, generate_sso_code,
    generate_checkin_code, verify_checkin_code
)


def test_generate_login_code():
    expect = b'84400-1-Tqf88675CWYb2sge67b9'
    result = generate_login_code('abc', 84400, 1)
    assert expect == result

    # Check that this will work with a key made of bytes
    result = generate_login_code(b'abc', 84400, 1)
    assert expect == result

def test_verify_login_code():
    uid = 1
    key = 'abc'
    gen_time = 84400
    good_time = 84401
    code = generate_login_code(key, gen_time, uid)

    good_result = verify_login_code('abc', good_time, code)
    assert good_result == uid

    malformed_code_result = verify_login_code('abc', good_time, b'84400-1')
    assert malformed_code_result is None

    # Timeout is currently 6 hours
    expired_result = verify_login_code('abc', gen_time * 10, code)
    assert expired_result is None

    bad_code_result = verify_login_code('ab', good_time, code)
    assert bad_code_result is None

def test_generate_sso_code():
    expect = b'84400-1-NB7m7JbQQB4NxKUzFgsv'
    result = generate_sso_code(b'abc', 84400, 1)
    assert expect == result

def test_generate_checkin_code():
    expect = b'AQABZTmTZ7TfdSeh'
    result = generate_checkin_code('abc', 1)
    assert expect == result

def test_verify_checkin_code():
    uid = 1
    key = 'abc'

    bad_version_code = generate_checkin_code(key, uid, version=255).decode('utf-8')
    bad_version_result = verify_checkin_code(key, bad_version_code)

    assert bad_version_result is None

    good_code = generate_checkin_code(key, uid).decode('utf-8')
    good_result = verify_checkin_code(key, good_code)
    assert uid == good_result

    # b'AQAB' is (user_id=1,version=1) in a struct & b64 encoded.
    bad_code_result = verify_checkin_code(key, 'bAQABbad')
    assert bad_code_result is None


def test_get_user_by_email(user):
    assert User.get_by_email(email=user.email) == user


def test_does_user_exist(user):
    assert User.does_user_exist(user.email)
    assert User.does_user_exist(user.email.upper())
    assert not User.does_user_exist('sir.notappearinginthisfilm@test.invalid')

def test_has_permission(user, db):
    assert not user.has_permission('admin')
    user.grant_permission('admin')
    db.session.commit()
    assert user.has_permission('admin')
