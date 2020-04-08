import click

from flask import current_app as app
from models.payment import (
    RefundRequest,
    Payment,
    StripePayment,
    BankPayment,
    GoCardlessPayment,
)

from . import payments
from .refund import handle_refund_request, ManualRefundRequired, RefundException


def payment_type(name):
    if name == "stripe":
        return StripePayment
    elif name == "bank":
        return BankPayment
    elif name == "gocardless":
        return GoCardlessPayment


@payments.cli.command("bulkrefund")
@click.option("-y", "--yes", is_flag=True, help="actually do refunds")
@click.option("-n", "--number", type=int, help="number of refunds to process")
@click.option("--provider", default="stripe")
def bulk_refund(yes, number, provider):
    """ Fully refund all pending refund requests """

    query = (
        RefundRequest.query.join(Payment)
        .filter(Payment.state == "refund-requested")
        .order_by(RefundRequest.id)
    )

    if number is not None:
        app.logger.info(f"Processing up to {number} refunds from providers: {provider}")

    count = 0
    for request in query:
        if type(request.payment) is not payment_type(provider):
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
            app.logger.warn(f"Manual refund required for request {request}: {e}")
        except RefundException as e:
            app.logger.exception(f"Error refunding request {request}: {e}")

        count += 1

    if yes:
        app.logger.info(f"{count} refunds processed")
    else:
        app.logger.info(
            f"{count} refunds would be processed. Pass the -y option to refund these for real."
        )
