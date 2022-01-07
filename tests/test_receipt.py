import io

from cairosvg import svg2png
from PIL import Image
from pyzbar.pyzbar import decode

from apps.common.receipt import format_inline_qr, format_inline_epc_qr, make_qr_png
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


def test_format_inline_qr():
    data = "https://www.example.org"

    qr_inline = format_inline_qr(data)
    qr_image = render_svg(qr_inline)

    decoded = decode(qr_image)
    assert len(decoded) == 1
    content = decoded[0].data.decode("utf-8")
    assert content == data


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


def test_make_qr_png():
    data = "https://www.example.org"

    qr_file = make_qr_png(data)
    qr_image = Image.open(qr_file)

    decoded = decode(qr_image)
    assert len(decoded) == 1
    content = decoded[0].data.decode("utf-8")
    assert content == data
