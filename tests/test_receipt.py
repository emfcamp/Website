from PIL import Image
from pyzbar.pyzbar import decode

from apps.common.receipt import format_inline_qr, make_qr_png

from tests._utils import render_svg


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
