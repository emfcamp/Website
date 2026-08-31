import csv
from datetime import timedelta
from io import StringIO

import click
from flask import current_app as app

from main import db
from models import naive_utcnow
from models.payment import BankPayment, Payment, RefundRequest

from . import payments
from .refund import (
    ManualRefundRequired,
    RefundException,
    handle_refund_request,
    manual_bank_refund,
)


@payments.cli.command("bulkrefund")
@click.option("-y", "--yes", is_flag=True, help="actually do refunds")
@click.option("-n", "--number", type=int, help="number of refunds to process")
@click.option("--provider", default="stripe")
def bulk_refund(yes, number, provider):
    """Automatically refund all pending refund requests where possible"""

    query = (
        RefundRequest.query.join(Payment)
        .filter(Payment.state == "refund-requested")
        .order_by(RefundRequest.id)
    )

    if number is not None:
        app.logger.info(f"Processing up to {number} refunds from providers: {provider}")

    count = 0
    for request in query:
        if request.method != "stripe":
            continue

        if count == number:
            break

        if not yes:
            count += 1
            app.logger.info("Would process refund %s", request)
            continue

        app.logger.info("Processing refund %s", request)
        try:
            handle_refund_request(request)
        except ManualRefundRequired as e:
            app.logger.warning(f"Manual refund required for request {request}: {e}")
        except RefundException as e:
            app.logger.exception(f"Error refunding request {request}: {e}")

        count += 1

    if yes:
        app.logger.info(f"{count} refunds processed")
    else:
        app.logger.info(f"{count} refunds would be processed. Pass the -y option to refund these for real.")


# TODO: make this a scheduled task, assuming it works
# @scheduled_task(minutes=60)
@payments.cli.command("expire_pending_payments")
@click.option("-y", "--yes", is_flag=True, help="actually do refunds")
def expire_pending_payments(yes):
    """Expire payments that have been sent a reminder more than 5 days ago"""
    if not yes:
        app.logger.info("Not expiring payments. Pass the -y option to do so.")
    query = (
        BankPayment.query.filter(BankPayment.state == "inprogress")
        .filter(BankPayment.expires < naive_utcnow())
        .filter(BankPayment.reminder_sent_at < naive_utcnow() - timedelta(days=5))
    )
    for payment in query:
        if yes:
            app.logger.info(f"Expiring payment {payment}")
            payment.cancel()
        else:
            app.logger.info(f"Would expire payment {payment}")

    db.session.commit()


@payments.cli.command("mark_transfer_paid")
@click.argument("payment_id", type=int)
def mark_paid(payment_id: int) -> None:
    """Mark a Bank transfer payment as paid. Useful for testing."""
    p = db.session.get(BankPayment, payment_id)
    if p is None:
        app.logger.error("Payment id %d not found!", payment_id)
        return
    p.paid()
    db.session.commit()
