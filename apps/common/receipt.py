# coding=utf-8
from __future__ import division, absolute_import, print_function, unicode_literals
from StringIO import StringIO
from urlparse import urljoin
from xhtml2pdf import pisa
import qrcode
from qrcode.image.svg import SvgPathImage
import barcode
from barcode.writer import ImageWriter, SVGWriter
from lxml import etree

from flask import Markup, render_template, request, current_app as app
from sqlalchemy import func

from models.ticket import Ticket, TicketType


def render_receipt(user, png=False, pdf=False):
    tickets = (user.tickets
                  .filter_by(paid=True)
                  .join(TicketType)
                  .order_by(TicketType.order))

    entrance_tts_counts = (tickets.filter(TicketType.admits.in_(['full', 'kids']))
        .with_entities(TicketType, func.count(Ticket.id).label('ticket_count'))
        .group_by(TicketType).all())
    entrance_tickets_count = sum(c for tt, c in entrance_tts_counts)

    vehicle_tickets = tickets.filter(TicketType.admits.in_(['car', 'campervan'])).all()

    return render_template('receipt.html', user=user,
                           format_inline_qr=format_inline_qr,
                           format_inline_barcode=format_inline_barcode,
                           entrance_tts_counts=entrance_tts_counts,
                           entrance_tickets_count=entrance_tickets_count,
                           vehicle_tickets=vehicle_tickets,
                           pdf=pdf, png=png)


def render_pdf(html, url_root=None):
    # This needs to fetch URLs found within the page, so if
    # you're running a dev server, use app.run(processes=2)
    if url_root is None:
        url_root = app.config.get('BASE_URL', request.url_root)

    def fix_link(uri, rel):
        if uri.startswith('//'):
            uri = 'https:' + uri
        if uri.startswith('https://'):
            return uri

        return urljoin(url_root, uri)

    pdffile = StringIO()
    pisa.CreatePDF(html, pdffile, link_callback=fix_link)
    pdffile.seek(0)

    return pdffile

def format_inline_qr(data):
    qrfile = StringIO()
    qr = qrcode.make(data, image_factory=SvgPathImage)
    qr.save(qrfile, 'SVG')
    qrfile.seek(0)

    root = etree.XML(qrfile.read())
    # Allow us to scale it with CSS
    del root.attrib['width']
    del root.attrib['height']
    root.attrib['preserveAspectRatio'] = 'none'

    return Markup(etree.tostring(root))


def make_qr_png(*args, **kwargs):
    qrfile = StringIO()

    qr = qrcode.make(*args, **kwargs)
    qr.save(qrfile, 'PNG')
    qrfile.seek(0)

    return qrfile


def format_inline_barcode(data):
    barcodefile = StringIO()

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

    return Markup(etree.tostring(root))


def make_barcode_png(data, **options):
    barcodefile = StringIO()

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

    for t in tickets:
        t.emailed = True

