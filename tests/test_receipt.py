import io
import pytest

from cairosvg import svg2png
from PIL import Image
from pyzbar.pyzbar import decode

from apps.common.receipt import (
    format_inline_qr,
    make_qr_png,
)


def render_svg(svg):
    # pyzbar fails to decode qr codes under 52x52
    png = svg2png(bytestring=svg, parent_width=64, parent_height=64)
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


def test_make_qr_png():
    data = "https://www.example.org"

    qr_file = make_qr_png(data)
    qr_image = Image.open(qr_file)

    decoded = decode(qr_image)
    assert len(decoded) == 1
    content = decoded[0].data.decode("utf-8")
    assert content == data
