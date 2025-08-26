import asyncio
import io
from typing import IO

import segno
from flask import render_template
from markupsafe import Markup
from playwright.async_api import async_playwright

from apps.common import feature_enabled
from main import external_url
from models import event_year
from models.product import PriceTier, Product, ProductGroup
from models.purchase import Purchase, PurchaseTransfer

RECEIPT_TYPES = ["admissions", "parking", "campervan", "merchandise", "hire"]


def render_receipt(user, png=False, pdf=False):
    purchases = (
        user.owned_purchases.filter_by(is_paid_for=True)
        .join(PriceTier)
        .join(Product)
        .join(ProductGroup)
        .with_entities(Purchase)
        .order_by(Purchase.id)
    )

    admissions = purchases.filter(ProductGroup.type == "admissions").all()

    parking_tickets = purchases.filter(ProductGroup.type == "parking").all()
    campervan_tickets = purchases.filter(ProductGroup.type == "campervan").all()

    merch = purchases.filter(ProductGroup.type == "merchandise").all()
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
        admissions=admissions,
        parking_tickets=parking_tickets,
        campervan_tickets=campervan_tickets,
        transferred_tickets=transferred_tickets,
        merch=merch,
        hires=hires,
        pdf=pdf,
        png=png,
    )


def render_pdf(url, html):
    # This needs to fetch URLs found within the page, so if
    # you're running a dev server, use app.run(processes=2)

    async def to_pdf():
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                # Handlers don't work as we're not in the main thread.
                handle_sigint=False,
                handle_sigterm=False,
                handle_sighup=False,
            )
            context = await browser.new_context()
            page = await browser.new_page()

            await page.route(url, lambda route: route.fulfill(body=html))
            await page.goto(url)
            pdf = await page.pdf(format="A4")
            await page.close()
            await context.close()
            await browser.close()
        return pdf

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    pdf = loop.run_until_complete(to_pdf())

    pdffile = io.BytesIO(pdf)
    return pdffile


def make_qrfile(data: str, kind: str = "svg", **kwargs) -> IO[bytes]:
    qrfile = io.BytesIO()
    qr = segno.make_qr(data)
    qr.save(qrfile, kind=kind, **kwargs)
    qrfile.seek(0)
    return qrfile


def format_inline_qr(data: str) -> Markup:
    qr = segno.make(data)
    return Markup(qr.svg_inline(svgclass=None, omitsize=True))


def attach_tickets(msg, user):
    # Attach tickets to a mail Message
    page = render_receipt(user, pdf=True)
    url = external_url("tickets.receipt", user_id=user.id)
    pdf = render_pdf(url, page)

    msg.attach(f"EMF{event_year()}.pdf", pdf.read(), "application/pdf")


def set_tickets_emailed(user):
    if not feature_enabled("ISSUE_TICKETS"):
        return False

    purchases = (
        user.owned_purchases.filter_by(is_paid_for=True)
        .join(PriceTier)
        .join(Product)
        .join(ProductGroup)
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
