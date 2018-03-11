# coding=utf-8
from __future__ import division, absolute_import, print_function, unicode_literals
import io
from lxml import etree
import asyncio

from flask import Markup, render_template
from sqlalchemy import func
from pyppeteer.launcher import launch
import qrcode
from qrcode.image.svg import SvgPathImage
import barcode
from barcode.writer import ImageWriter, SVGWriter

from models.product import Product, ProductGroup, PriceTier
from models.purchase import PurchaseTransfer, Ticket
from models import Purchase


def render_receipt(user, png=False, pdf=False):
    entrance_products_counts = (user.purchased_products
                               .filter_by(state='paid', is_ticket=True)
                               .join(Product)
                               .with_entities(Product,
                                              func.count(Purchase.id)
                                                  .label('ticket_count'))
                               .group_by(Product.id).all())
    entrance_tickets_count = sum(c for p, c in entrance_products_counts)

    other = user.purchased_products.filter_by(state='paid', is_ticket=False) \
                                   .join(PriceTier, Product, ProductGroup)

    vehicle_tickets = other.filter(ProductGroup.name == 'Parking').all()

    tees = (other.filter(ProductGroup.name == 'Tee')
                 .with_entities(PriceTier, func.count(Purchase.id).label('ticket_count'))
                 .group_by(PriceTier).all())  # t-shirts

    transferred_tickets = user.transfers_from.join(Purchase).filter_by(state='paid') \
                              .with_entities(PurchaseTransfer).order_by('timestamp').all()

    return render_template('receipt.html', user=user,
                           format_inline_qr=format_inline_qr,
                           format_inline_barcode=format_inline_barcode,
                           entrance_products_counts=entrance_products_counts,
                           entrance_tickets_count=entrance_tickets_count,
                           vehicle_tickets=vehicle_tickets,
                           transferred_tickets=transferred_tickets,
                           tees=tees,
                           pdf=pdf, png=png)


def render_parking_receipts(png=False, pdf=False):
    vehicle_tickets = Ticket.query.filter(is_paid_for=True) \
        .join(PriceTier, Product, ProductGroup) \
        .filter_by(type='parking')

    users = [t.user for t in vehicle_tickets]

    return render_template('parking-receipts.html', users=users,
                           format_inline_qr=format_inline_qr,
                           format_inline_barcode=format_inline_barcode,
                           vehicle_tickets=vehicle_tickets,
                           pdf=pdf, png=png)


def render_pdf(url, html):
    # This needs to fetch URLs found within the page, so if
    # you're running a dev server, use app.run(processes=2)
    async def to_pdf():
        # TOSO: make it possible to use a running process
        browser = await launch(executablePath='google-chrome')

        page = await browser.newPage()

        async def request_intercepted(request):
            if request.url == url:
                await request.respond({'body': html})
            else:
                await request.continue_()

        page.on('request', request_intercepted)
        await page.setRequestInterception(True)

        await page.goto(url)
        pdf = await page.pdf()
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
    qr.save(qrfile, 'SVG')
    qrfile.seek(0)

    root = etree.XML(qrfile.read())
    # Allow us to scale it with CSS
    del root.attrib['width']
    del root.attrib['height']
    root.attrib['preserveAspectRatio'] = 'none'

    return Markup(etree.tostring(root).decode('utf-8'))


def make_qr_png(*args, **kwargs):
    qrfile = io.BytesIO()

    qr = qrcode.make(*args, **kwargs)
    qr.save(qrfile, 'PNG')
    qrfile.seek(0)

    return qrfile


def format_inline_barcode(data):
    barcodefile = io.BytesIO()

    # data is written into the SVG without a CDATA, so base64 encode it
    code128 = barcode.get('code128', data, writer=SVGWriter())
    code128.write(barcodefile, {'write_text': False})
    barcodefile.seek(0)

    root = etree.XML(barcodefile.read())
    # Allow us to scale it with CSS
    root.attrib['viewBox'] = '0 0 %s %s' % (root.attrib['width'], root.attrib['height'])
    del root.attrib['width']
    del root.attrib['height']
    root.attrib['preserveAspectRatio'] = 'none'

    return Markup(etree.tostring(root).decode('utf-8'))


def make_barcode_png(data, **options):
    barcodefile = io.BytesIO()

    code128 = barcode.get('code128', data, writer=ImageWriter())
    # Sizes here are the ones used in the PDF
    code128.write(barcodefile, {'write_text': False, 'module_height': 8})
    barcodefile.seek(0)

    return barcodefile


def attach_tickets(msg, user):
    # Attach tickets to a mail Message
    page = render_receipt(user, pdf=True)
    pdf = render_pdf(page)

    tickets = user.tickets.filter_by(paid=True)
    plural = (tickets.count() != 1 and 's' or '')
    msg.attach('Ticket%s.pdf' % plural, 'application/pdf', pdf.read())

    tickets = user.purchased_products.filter_by(state='paid')
    for t in tickets:
        tickets.set_state('receipt-emailed')

