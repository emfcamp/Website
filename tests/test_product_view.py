from datetime import datetime, timedelta

from models.product import ProductView, Voucher
from models.cfp import TalkProposal

YESTERDAY = datetime.utcnow() - timedelta(days=1)
TOMORROW = datetime.utcnow() + timedelta(days=1)


def test_product_view_accessible(db, user):
    product_view = ProductView(name="other")
    assert product_view.is_accessible(user), "Default view should be visible"

    product_view = ProductView(name="other")

    voucher = Voucher(view=product_view)
    assert product_view.is_accessible(
        user, voucher.token
    ), "Product should be visible with token"
    assert not product_view.is_accessible(
        user
    ), "Product should be inaccessible without token"
    assert not product_view.is_accessible(
        user, "wrong"
    ), "Product should be inaccessible with incorrect token"

    product_view = ProductView(name="cfp", cfp_accepted_only=True)
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


def test_product_view_accessible_wrt_sales_start(db, user, monkeypatch):
    # force SALES_START into the future
    def sales_start_mock_future(key):
        return TOMORROW

    # Patch config_date rather than utcnow as apparently you can't patch builtins
    monkeypatch.setattr("models.product.config_date", sales_start_mock_future)

    product_view = ProductView(name="other")
    assert not product_view.is_accessible(
        user
    ), "Default view should not be visible before SALES_START"

    # force sales start into the future
    def sales_start_mock_past(key):
        return YESTERDAY

    # Patch config_date rather than utcnow as apparently you can't patch builtins
    monkeypatch.setattr("models.product.config_date", sales_start_mock_past)

    product_view = ProductView(name="other")
    assert product_view.is_accessible(
        user
    ), "Default view should be visible after SALES_START"


def test_product_view_accessible_voucher_expiry(db, user, monkeypatch):
    # Vouchers should work regardless of SALES_START so set it into the future
    def sales_start_mock_future(key):
        return TOMORROW

    # Patch config_date rather than utcnow as apparently you can't patch builtins
    monkeypatch.setattr("models.product.config_date", sales_start_mock_future)

    product_view = ProductView(name="other")
    voucher = Voucher(view=product_view, token="test1", expiry=YESTERDAY)
    voucher = Voucher(view=product_view, token="test2", expiry=TOMORROW)

    assert not product_view.is_accessible(
        user, user_token="test1"
    ), "View should be inaccessible with expired voucher"

    assert product_view.is_accessible(
        user, user_token="test2"
    ), "View should be accessible with in-date voucher"
