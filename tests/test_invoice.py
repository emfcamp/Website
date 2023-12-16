import pytest

from pyzbar.pyzbar import decode

from apps.payments.invoice import format_inline_epc_qr
from models.payment import BankPayment

from tests._utils import render_svg


@pytest.mark.skip
def test_format_inline_epc_qr():
    payment = BankPayment(currency="EUR", amount=10)

    qr_inline = format_inline_epc_qr(payment)
    qr_image = render_svg(qr_inline)

    expected = [
        "BCD",
        "002",
        "1",
        "SCT",
        "",
        "Electromagnetic Field Ltd",
        "GB21BARC20716472954433",
        "EUR10",
        "",
        payment.bankref,
    ]

    decoded = decode(qr_image)
    assert len(decoded) == 1
    content = decoded[0].data.decode("utf-8")
    assert content == "\n".join(expected)
