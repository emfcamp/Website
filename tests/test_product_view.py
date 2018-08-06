from models.product import ProductView
from models.cfp import TalkProposal


def test_product_view_accessible(db, user):
    product_view = ProductView(name="other")
    assert product_view.is_accessible(user)

    product_view = ProductView(name="other", token="testtoken")
    assert product_view.is_accessible(user, "testtoken")
    assert not product_view.is_accessible(user)

    product_view = ProductView(name="cfp", cfp_accepted_only=True)
    assert not product_view.is_accessible(user)

    proposal = TalkProposal()
    proposal.title = "title"
    proposal.description = "description"
    proposal.requirements = "requirements"
    proposal.user = user
    db.session.add(proposal)
    db.session.commit()
    proposal.set_state('accepted')

    assert product_view.is_accessible(user)
