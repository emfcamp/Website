from markupsafe import Markup
from segno import QRCode, helpers

from models.payment import BankPayment


def make_epc_qr(payment: BankPayment) -> QRCode:
    return helpers.make_epc_qr(
        name=payment.recommended_destination.payee_name,
        iban=payment.recommended_destination.iban,
        amount=payment.amount,
        reference=payment.customer_reference,
        bic=payment.recommended_destination.swift,
        encoding="utf-8",
    )


def format_inline_epc_qr(payment: BankPayment) -> Markup:
    qr: QRCode = make_epc_qr(payment)
    return Markup(qr.svg_inline(svgclass=None, omitsize=True))
