import re

login_link_re = r"(https?://[^\s/]*/login[^\s]*)"


def test_login(user, client, outbox):
    url = "/login?next=test"
    login_get = client.get(url)
    form_string = "Enter your email address and we'll email you a login link"
    assert form_string in login_get.data.decode("utf-8")

    form = dict(email=user.email)
    client.post(url, data=form, follow_redirects=True)

    assert len(outbox) == 1

    match = re.search(login_link_re, outbox[0].body)
    assert len(match.groups()) == 1

    login_link_get = client.get(match.group(0))
    assert login_link_get.status_code == 302
    assert login_link_get.location.endswith("/test")


def test_bad_login(user, client, outbox):
    url = "/login?next=test"

    # Trying to login with an arbitrary email should look the same
    # as doing so with a valid email.
    form = dict(email="sir.notappearinginthisfilm@test.invalid")
    post = client.post(url, data=form, follow_redirects=True)

    assert post.status_code == 200
    assert len(outbox) == 0

    bad_login_link = client.get(url + "&code=84400-1-Tqf88675CWYb2sge67b9")
    assert bad_login_link.status_code == 200
    error_string = "Your login link was invalid. Please enter your email address below to receive a new link."
    assert error_string in bad_login_link.data.decode("utf-8")
