import pytest

from pyzbar.pyzbar import decode
import re
from stdnum import iso11649

from main import db
from apps.common.epc import format_inline_epc_qr
from models.payment import BankPayment
from models.user import User

from tests._utils import render_svg


@pytest.mark.parametrize(
    "customer_reference, expected_format",
    [
        ("VFH9K3RQ", "VFH9-K3RQ"),
        ("RF679HKFVR8Q", "RF67 9HKF VR8Q"),
    ],
)
def test_customer_reference_display_format(app, customer_reference, expected_format):
    assert app.jinja_env.filters["bankref"](customer_reference) == expected_format


def test_format_inline_epc_qr(app):
    user = User("test_invoice_user@test.invalid", "test_invoice_user")
    db.session.add(user)
    db.session.commit()

    payment = BankPayment(currency="EUR", amount=10)
    payment.user_id = user.id

    # Persist the payment object so that a sequence ID is generated for it
    db.session.add(payment)
    db.session.commit()

    # Ensure that the structured creditor reference is valid and contains the bankref
    assert iso11649.is_valid(payment.customer_reference)
    assert re.match(f"^RF[0-9][0-9]{payment.bankref}$", payment.customer_reference)

    qr_inline = format_inline_epc_qr(payment)
    qr_image = render_svg(qr_inline)

    expected = [
        "BCD",
        "002",
        "1",
        "SCT",
        "BUKBGB33",
        "EMF Festivals Ltd",
        "GB33BUKB20201555555555",
        "EUR10",
        "",
        payment.customer_reference,
    ]

    decoded = decode(qr_image)
    assert len(decoded) == 1
    content = decoded[0].data.decode("utf-8")
    assert content == "\n".join(expected)
