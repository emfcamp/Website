from io import BytesIO

from markupsafe import Markup
from segno import helpers


def make_epc_qrfile(payment, **kwargs):
    qrfile = BytesIO()
    # TODO: this isn't currently used. Need to fetch IBAN from payment.recommended_destination
    # and name from somewhere - maybe config rather than hard-coding.
    qr = helpers.make_epc_qr(
        name="EMF Festivals Ltd",
        iban=payment.recommended_destination.iban,
        amount=payment.amount,
        reference=payment.bankref,
        encoding=1,
    )
    qr.save(qrfile, **kwargs)
    qrfile.seek(0)
    return qrfile


def qrfile_to_svg(qrfile):
    return Markup(qrfile.getvalue().decode("utf-8"))


def format_inline_epc_qr(payment):
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
