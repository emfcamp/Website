# coding=utf-8
from __future__ import division, absolute_import, print_function, unicode_literals
from StringIO import StringIO
from urlparse import urljoin
from xhtml2pdf import pisa
import qrcode
from qrcode.image.svg import SvgPathImage
from lxml import etree
from flask import Markup, render_template, request, current_app as app

from models.ticket import TicketType


def render_receipt(tickets, png=False, table=False, pdf=False):
    user = tickets[0].user

    entrance_tickets = tickets.filter(TicketType.admits.in_(['full', 'kids'])).all()
    vehicle_tickets = tickets.filter(TicketType.admits.in_(['car', 'campervan'])).all()

    return render_template('receipt.html', user=user, format_inline_qr=format_inline_qr,
                           entrance_tickets=entrance_tickets, vehicle_tickets=vehicle_tickets,
                           pdf=pdf, png=png, table=table)


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


def format_inline_qr(code):
    url = app.config.get('CHECKIN_BASE') + code

    qrfile = StringIO()
    qr = qrcode.make(url, image_factory=SvgPathImage)
    qr.save(qrfile, 'SVG')
    qrfile.seek(0)

    root = etree.XML(qrfile.read())
    # Wrap inside an element with the right default namespace
    svgns = 'http://www.w3.org/2000/svg'
    newroot = root.makeelement('{%s}svg' % svgns, nsmap={None: svgns})
    newroot.append(root)

    return Markup(etree.tostring(root))


def make_qr_png(*args, **kwargs):
    qrfile = StringIO()

    qr = qrcode.make(*args, **kwargs)
    qr.save(qrfile, 'PNG')
    qrfile.seek(0)

    return qrfile


def attach_tickets(msg, tickets):
    # Attach tickets to a mail Message
    page = render_receipt(tickets, pdf=True)
    pdf = render_pdf(page)
    plural = (tickets.count() != 1 and 's' or '')
    msg.attach('Ticket%s.pdf' % plural, 'application/pdf', pdf.read())

    for t in tickets:
        t.emailed = True

