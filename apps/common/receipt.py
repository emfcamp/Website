# coding=utf-8
from __future__ import division, absolute_import, print_function, unicode_literals
import io
import os
import tempfile
import shutil
from lxml import etree
import asyncio
from urllib.parse import urljoin

from flask import Markup, render_template, current_app as app
from pyppeteer.browser import Browser
from pyppeteer.connection import Connection
from pyppeteer.launcher import launch
import qrcode
from qrcode.image.svg import SvgPathImage
import barcode
from barcode.writer import ImageWriter, SVGWriter
import requests

from main import external_url
from models.product import Product, ProductGroup, PriceTier
from models.purchase import PurchaseTransfer, Ticket
from models.site_state import event_start
from models import Purchase


RECEIPT_TYPES = ['admissions', 'parking', 'campervan', 'tees', 'hire']

def render_receipt(user, png=False, pdf=False):
    purchases = user.owned_purchases.filter_by(is_paid_for=True) \
                                    .join(PriceTier, Product, ProductGroup) \
                                    .with_entities(Purchase) \
                                    .order_by(Purchase.id)

    admissions = purchases.filter(ProductGroup.type == 'admissions').all()

    vehicle_tickets = purchases.filter(ProductGroup.type.in_(['parking', 'campervan'])).all()

    tees = purchases.filter(ProductGroup.type == 'tees').all()
    hires = purchases.filter(ProductGroup.type == 'hire').all()

    transferred_tickets = user.transfers_from \
                              .join(Purchase) \
                              .filter_by(state='paid') \
                              .with_entities(PurchaseTransfer) \
                              .order_by('timestamp').all()

    return render_template('receipt.html', user=user,
                           format_inline_qr=format_inline_qr,
                           format_inline_barcode=format_inline_barcode,
                           admissions=admissions,
                           vehicle_tickets=vehicle_tickets,
                           transferred_tickets=transferred_tickets,
                           tees=tees, hires=hires,
                           pdf=pdf, png=png)


def render_parking_receipts(png=False, pdf=False):
    vehicle_tickets = Ticket.query.filter_by(is_paid_for=True) \
        .join(PriceTier, Product, ProductGroup) \
        .filter_by(type='parking')

    users = [t.owner for t in vehicle_tickets]

    return render_template('parking-receipts.html', users=users,
                           format_inline_qr=format_inline_qr,
                           format_inline_barcode=format_inline_barcode,
                           vehicle_tickets=vehicle_tickets,
                           pdf=pdf, png=png)


def render_pdf(url, html):
    # This needs to fetch URLs found within the page, so if
    # you're running a dev server, use app.run(processes=2)

    async def to_pdf():
        if app.config.get('CHROME_URL'):
            version_url = urljoin(app.config['CHROME_URL'], 'json/version')
            data = requests.get(version_url).json()
            con = Connection(data['webSocketDebuggerUrl'])
            browser = await Browser.create(con)

        else:
            chrome_dir = 'var/pyppeteer'
            if not os.path.exists(chrome_dir):
                os.mkdir(chrome_dir)

            tmp_chrome_dir = tempfile.mkdtemp(dir=chrome_dir)
            browser = await launch(executablePath='google-chrome', userDataDir=tmp_chrome_dir)

        page = await browser.newPage()

        async def request_intercepted(request):
            app.logger.debug('Intercepted URL: %s', request.url)
            if request.url == url:
                await request.respond({'body': html})
            else:
                await request.continue_()

        page.on('request', request_intercepted)
        await page.setRequestInterception(True)

        await page.goto(url)
        pdf = await page.pdf(format='A4')
        await browser.close()

        if not app.config.get('CHROME_URL'):
            shutil.rmtree(tmp_chrome_dir)

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
    url = external_url('tickets.receipt', user_id=user.id)
    pdf = render_pdf(url, page)

    msg.attach('EMF{}.pdf'.format(event_start().year), 'application/pdf', pdf.read())

    purchases = user.owned_purchases.filter_by(is_paid_for=True, state='paid') \
                                    .join(PriceTier, Product, ProductGroup) \
                                    .filter(ProductGroup.type.in_(RECEIPT_TYPES)) \
                                    .with_entities(Purchase) \
                                    .group_by(Purchase) \
                                    .order_by(Purchase.id)

    for p in purchases:
        p.set_state('receipt-emailed')

