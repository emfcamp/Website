import io
from lxml import etree
import asyncio

from flask import Markup, render_template, current_app as app
from pyppeteer.launcher import launch
import qrcode
from qrcode.image.svg import SvgPathImage
import barcode
from barcode.writer import ImageWriter, SVGWriter

from main import external_url
from models import event_year
from models.product import Product, ProductGroup, PriceTier
from models.purchase import Purchase, PurchaseTransfer


RECEIPT_TYPES = ["admissions", "parking", "campervan", "tees", "hire"]


def render_receipt(user, png=False, pdf=False):
    purchases = (
        user.owned_purchases.filter_by(is_paid_for=True)
        .join(PriceTier, Product, ProductGroup)
        .with_entities(Purchase)
        .order_by(Purchase.id)
    )

    admissions = purchases.filter(ProductGroup.type == "admissions").all()

    vehicle_tickets = purchases.filter(
        ProductGroup.type.in_(["parking", "campervan"])
    ).all()

    tees = purchases.filter(ProductGroup.type == "tees").all()
    hires = purchases.filter(ProductGroup.type == "hire").all()

    transferred_tickets = (
        user.transfers_from.join(Purchase)
        .filter_by(state="paid")
        .with_entities(PurchaseTransfer)
        .order_by("timestamp")
        .all()
    )

    return render_template(
        "receipt.html",
        user=user,
        format_inline_qr=format_inline_qr,
        format_inline_barcode=format_inline_barcode,
        admissions=admissions,
        vehicle_tickets=vehicle_tickets,
        transferred_tickets=transferred_tickets,
        tees=tees,
        hires=hires,
        pdf=pdf,
        png=png,
    )


def render_pdf(url, html):
    # This needs to fetch URLs found within the page, so if
    # you're running a dev server, use app.run(processes=2)

    async def to_pdf():
        browser = await launch(
            # Handlers don't work as we're not in the main thread.
            handleSIGINT=False,
            handleSIGTERM=False,
            handleSIGHUP=False,
            # --no-sandbox is necessary as we're running as root (in docker!)
            args=["--no-sandbox"],
        )
        page = await browser.newPage()

        async def request_intercepted(request):
            app.logger.debug("Intercepted URL: %s", request.url)
            if request.url == url:
                await request.respond({"body": html})
            else:
                await request.continue_()

        page.on("request", request_intercepted)
        await page.setRequestInterception(True)

        await page.goto(url)
        pdf = await page.pdf(format="A4")
        await browser.close()
        return pdf

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    pdf = loop.run_until_complete(to_pdf())

    pdffile = io.BytesIO(pdf)
    return pdffile


def format_inline_qr(data):
    qrfile = io.BytesIO()
    qr = qrcode.make(data, image_factory=SvgPathImage)
    qr.save(qrfile, "SVG")
    qrfile.seek(0)

    root = etree.XML(qrfile.read())
    # Allow us to scale it with CSS
    del root.attrib["width"]
    del root.attrib["height"]
    root.attrib["preserveAspectRatio"] = "none"

    return Markup(etree.tostring(root).decode("utf-8"))


def make_qr_png(url):
    qrfile = io.BytesIO()

    qr = qrcode.make(url, box_size=3)
    qr.save(qrfile, "PNG")
    qrfile.seek(0)

    return qrfile


def format_inline_barcode(data):
    barcodefile = io.BytesIO()

    # data is written into the SVG without a CDATA, so base64 encode it
    code128 = barcode.get("code128", data, writer=SVGWriter())
    code128.write(barcodefile, {"write_text": False})
    barcodefile.seek(0)

    root = etree.XML(barcodefile.read())
    # Allow us to scale it with CSS
    root.attrib["viewBox"] = "0 0 %s %s" % (root.attrib["width"], root.attrib["height"])
    del root.attrib["width"]
    del root.attrib["height"]
    root.attrib["preserveAspectRatio"] = "none"

    return Markup(etree.tostring(root).decode("utf-8"))


def make_barcode_png(data, **options):
    barcodefile = io.BytesIO()

    code128 = barcode.get("code128", data, writer=ImageWriter())
    # Sizes here are the ones used in the PDF
    code128.write(barcodefile, {"write_text": False, "module_height": 8})
    barcodefile.seek(0)

    return barcodefile


def attach_tickets(msg, user):
    # Attach tickets to a mail Message
    page = render_receipt(user, pdf=True)
    url = external_url("tickets.receipt", user_id=user.id)
    pdf = render_pdf(url, page)

    msg.attach("EMF{}.pdf".format(event_year()), "application/pdf", pdf.read())


def set_tickets_emailed(user):
    purchases = (
        user.owned_purchases.filter_by(is_paid_for=True)
        .filter(Purchase.state.in_(["paid"]))
        .join(PriceTier, Product, ProductGroup)
        .filter(ProductGroup.type.in_(RECEIPT_TYPES))
        .with_entities(Purchase)
        .group_by(Purchase)
        .order_by(Purchase.id)
    )

    already_emailed = False
    for p in purchases:
        if p.ticket_issued:
            already_emailed = True

        p.ticket_issued = True

    return already_emailed
