from pyzbar.pyzbar import decode
import re
from stdnum import iso11649

from apps.payments.invoice import format_inline_epc_qr
from main import db
from models.payment import BankPayment
from models.user import User

from tests._utils import render_svg


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
    assert re.match(f"^RF[0-9][0-9]E{payment.bankref}$", payment.customer_reference)

    qr_inline = format_inline_epc_qr(payment)
    qr_image = render_svg(qr_inline)

    expected = [
        "BCD",
        "002",
        "1",
        "SCT",
        "",
        "EMF Festivals Ltd",
        "GB47LOND11213141516171",
        "EUR10",
        "",
        payment.customer_reference,
    ]

    decoded = decode(qr_image)
    assert len(decoded) == 1
    content = decoded[0].data.decode("utf-8")
    assert content == "\n".join(expected)
