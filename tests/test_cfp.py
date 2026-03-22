from hypothesis import assume, given, settings
from hypothesis.strategies import text

from apps.cfp_review.base import send_email_for_proposal
from models.cfp import (
    PROPOSAL_INFOS,
    SCHEDULE_ITEM_INFOS,
    Proposal,
)


def test_type_infos():
    assert all(k == v.type for k, v in PROPOSAL_INFOS.items())
    assert all(k == v.type for k, v in SCHEDULE_ITEM_INFOS.items())


def test_cfp(db, app, user, outbox):
    # Run hypothesis over an inner function to avoid warnings about re-use of
    # `outbox` (which we are manually clearing in this test)
    @given(title=text(), description=text(), equipment_required=text())
    @settings(deadline=None)  # Variable execution time errors observed in Travis and locally for russ
    def test_cfp_inner(title, description, equipment_required):
        for c in ["\0", "\r", "\n"]:
            assume(c not in title)

        assume("\0" not in description)
        assume("\0" not in equipment_required)

        proposal = Proposal(
            type="talk",
            title=title,
            description=description,
            equipment_required=equipment_required,
            user=user,
        )
        db.session.add(proposal)
        db.session.commit()

        proposal.state = "accepted"

        # TODO: create schedule_item?

        with app.test_request_context("/"):
            send_email_for_proposal(proposal, reason="accepted")

        assert len(outbox) == 1
        del outbox[:]
