from hypothesis import given, assume
from hypothesis.strategies import text

from models.cfp import TalkProposal
from apps.cfp_review.base import send_email_for_proposal


@given(title=text(), description=text(), requirements=text())
def test_cfp(db, app, user, outbox, title, description, requirements):
    for c in ["\0", "\r", "\n"]:
        assume(c not in title)

    assume("\0" not in description)
    assume("\0" not in requirements)

    proposal = TalkProposal()
    proposal.title = title
    proposal.description = description
    proposal.requirements = requirements
    proposal.user = user

    db.session.add(proposal)
    db.session.commit()

    proposal.set_state('accepted')
    with app.test_request_context('/'):
        send_email_for_proposal(proposal, reason='accepted')

    assert len(outbox) == 1
    del outbox[:]
