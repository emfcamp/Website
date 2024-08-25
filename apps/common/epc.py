from io import BytesIO

from markupsafe import Markup
from segno import QRCode, helpers

from models.payment import BankPayment


def make_epc_qrfile(payment: BankPayment, **kwargs) -> BytesIO:
    qrfile = BytesIO()
    qr: QRCode = helpers.make_epc_qr(
        name=payment.recommended_destination.payee_name,
        iban=payment.recommended_destination.iban,
        amount=payment.amount,
        reference=payment.customer_reference,
        bic=payment.recommended_destination.swift,
        encoding=1,
    )
    qr.save(qrfile, **kwargs)
    qrfile.seek(0)
    return qrfile


def qrfile_to_svg(qrfile: BytesIO) -> str:
    return Markup(qrfile.getvalue().decode("utf-8"))


def format_inline_epc_qr(payment: BankPayment) -> str:
    qrfile = make_epc_qrfile(
        payment,
        kind="svg",
        svgclass=None,
        omitsize=True,
        xmldecl=False,
        svgns=False,
        nl=False,
    )
    return qrfile_to_svg(qrfile)
