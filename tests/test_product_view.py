from datetime import datetime, timedelta

from models.product import ProductView, Voucher
from models.cfp import TalkProposal

YESTERDAY = datetime.utcnow() - timedelta(days=1)
TOMORROW = datetime.utcnow() + timedelta(days=1)


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

    product_view = ProductView(name="other", type="ticket", vouchers_only=True)
    db.session.add(product_view)
    db.session.add(Voucher(view=product_view, code="test1", expiry=YESTERDAY))
    db.session.add(Voucher(view=product_view, code="test2", expiry=TOMORROW))
    db.session.commit()

    assert not product_view.is_accessible(
        user, voucher="test1"
    ), "View should be inaccessible with expired voucher"

    assert product_view.is_accessible(
        user, voucher="test2"
    ), "View should be accessible with in-date voucher"
