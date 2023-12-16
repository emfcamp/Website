from io import BytesIO

from cairosvg import svg2png
from PIL import Image


def render_svg(svg):
    # pyzbar fails to decode qr codes under 52x52 and epc qr codes under 72x72
    png = svg2png(bytestring=svg, parent_width=80, parent_height=80)
    png_file = BytesIO(png)
    image = Image.open(png_file)

    # pillow renders alpha channel black by default
    alpha = image.convert("RGBA").split()[-1]
    opaque_image = Image.new("RGBA", image.size, "white")
    opaque_image.paste(image, mask=alpha)

    return opaque_image
