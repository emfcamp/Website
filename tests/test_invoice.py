import io
import pytest

from cairosvg import svg2png
from PIL import Image
from pyzbar.pyzbar import decode

from apps.payments.invoice import format_inline_epc_qr
from models.payment import BankPayment


def render_svg(svg):
    # pyzbar fails to decode qr codes under 52x52 and epc qr codes under 72x72
    png = svg2png(bytestring=svg, parent_width=80, parent_height=80)
    png_file = io.BytesIO(png)
    image = Image.open(png_file)

    # pillow renders alpha channel black by default
    alpha = image.convert("RGBA").split()[-1]
    opaque_image = Image.new("RGBA", image.size, "white")
    opaque_image.paste(image, mask=alpha)

    return opaque_image


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
