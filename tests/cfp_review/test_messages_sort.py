import re

import pytest

from models.content.cfp import Proposal, ProposalMessage
from models.user import User
from tests._utils import login_link_re


def get_or_create_user(db, email, name):
    user = db.session.query(User).filter(User.email == email).one_or_none()
    if not user:
        user = User(email, name)
        db.session.add(user)
        db.session.commit()
    return user


@pytest.fixture
def admin_client(client, db, outbox):
    "A test client logged in as a cfp_admin user."
    admin = get_or_create_user(db, "admin-sort@example.com", "Sort Admin")
    if not admin.has_permission("cfp_admin"):
        admin.grant_permission("cfp_admin")
        db.session.commit()

    client.post("/login", data={"email": admin.email})
    m = re.search(login_link_re, outbox[0].body)
    assert m is not None
    client.get(m.group(0))
    client.post("/admin/cfp-review/confidentiality", data={"agree": "on"})
    yield client


@pytest.fixture
def proposals_with_messages(db):
    "One talk and one workshop proposal, each with a message to admin."
    proposer = get_or_create_user(db, "proposer-sort@example.com", "Proposer")
    for type_, title in (("talk", "My test talk"), ("workshop", "My test workshop")):
        proposal = db.session.query(Proposal).filter(Proposal.title == title).one_or_none()
        if not proposal:
            proposal = Proposal(type=type_, title=title, description="desc", user=proposer)
            db.session.add(proposal)
            db.session.flush()
        db.session.add(
            ProposalMessage(
                proposal=proposal,
                from_user=proposer,
                message="a message",
                is_to_admin=True,
                has_been_read=False,
            )
        )
    db.session.commit()


def test_messages_sort_without_filter_shows_all(admin_client, proposals_with_messages):
    "Sorting with no filter must not drop proposals (issue #1752)."
    resp = admin_client.get("/admin/cfp-review/messages?sort_by=date&type=all")
    assert resp.status_code == 200
    assert b"My test talk" in resp.data
    assert b"My test workshop" in resp.data


def test_messages_sort_links_do_not_carry_type_all(admin_client, proposals_with_messages):
    "Sort header links must not inject type=all into the query string."
    resp = admin_client.get("/admin/cfp-review/messages")
    assert resp.status_code == 200
    assert b"type=all" not in resp.data
