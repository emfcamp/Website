from pyzbar.pyzbar import decode

from apps.common.epc import format_inline_epc_qr
from models.payment import BankPayment

from tests._utils import render_svg


def test_format_inline_epc_qr(app):
    payment = BankPayment(currency="EUR", amount=10)

    qr_inline = format_inline_epc_qr(payment)
    qr_image = render_svg(qr_inline)

    expected = [
        "BCD",
        "002",
        "1",
        "SCT",
        "",
        "EMF Festivals Ltd",
        "GB33BUKB20201555555555",
        "EUR10",
        "",
        payment.bankref,
    ]

    decoded = decode(qr_image)
    assert len(decoded) == 1
    content = decoded[0].data.decode("utf-8")
    assert content == "\n".join(expected)
