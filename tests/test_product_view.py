from datetime import datetime, timedelta

from models.product import VOUCHER_GRACE_PERIOD, ProductView, Voucher
from models.cfp import TalkProposal


def test_product_view_accessible(db, user, monkeypatch):
    product_view = ProductView(name="other", type="ticket")
    assert product_view.is_accessible(user), "Default view should be visible"

    product_view = ProductView(name="another-other", type="ticket", vouchers_only=True)
    voucher = Voucher(view=product_view)

    db.session.add(product_view)
    db.session.add(voucher)
    db.session.commit()

    assert product_view.is_accessible(
        user, voucher.code
    ), "Product should be visible with voucher"

    assert not product_view.is_accessible(
        user
    ), "Product should be inaccessible without voucher"

    assert not product_view.is_accessible(
        user, "wrong"
    ), "Product should be inaccessible with incorrect voucher"

    product_view = ProductView(name="cfp", cfp_accepted_only=True, type="ticket")
    assert not product_view.is_accessible(
        user
    ), "CfP products should not be visible without accepted proposal"

    proposal = TalkProposal()
    proposal.title = "title"
    proposal.description = "description"
    proposal.requirements = "requirements"
    proposal.user = user
    db.session.add(proposal)
    db.session.commit()
    proposal.set_state("accepted")

    assert product_view.is_accessible(
        user
    ), "CfP products should be visible with accepted proposal"


def test_product_view_accessible_voucher_expiry(db, user, monkeypatch):
    EXPIRED_YESTERDAY = "test1"
    EXPIRES_TOMORROW = "test2"
    product_view = ProductView(name="other", type="ticket", vouchers_only=True)
    db.session.add(product_view)
    db.session.add(
        Voucher(
            view=product_view,
            code=EXPIRED_YESTERDAY,
            expiry=datetime.utcnow() - timedelta(days=1) - VOUCHER_GRACE_PERIOD,
        )
    )
    db.session.add(
        Voucher(
            view=product_view,
            code=EXPIRES_TOMORROW,
            expiry=datetime.utcnow() + timedelta(days=1),
        )
    )
    db.session.commit()

    assert not product_view.is_accessible(
        user, voucher=EXPIRED_YESTERDAY
    ), "View should be inaccessible with expired voucher"

    assert product_view.is_accessible(
        user, voucher=EXPIRES_TOMORROW
    ), "View should be accessible with in-date voucher"
