import click
import csv
from io import StringIO

from flask import current_app as app
from models.payment import RefundRequest, Payment

from . import payments
from .refund import (
    handle_refund_request,
    manual_bank_refund,
    ManualRefundRequired,
    RefundException,
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


@payments.cli.command("transferwise_refund")
@click.option("-n", "--number", type=int, help="number of refunds to export")
@click.option("-a", "--amount", type=int, help="value of refunds to export")
@click.argument("currency", type=click.Choice(["GBP", "EUR"]))
def transferwise_refund(number, amount, currency):
    """Emit a CSV file for refunding with Transferwise"""
    query = (
        RefundRequest.query.join(Payment)
        .filter(Payment.state == "refund-requested")
        .order_by(RefundRequest.id)
    )

    io = StringIO()
    writer = csv.writer(io)
    writer.writerow(
        [
            "refund_id",
            "name",
            "paymentReference",
            "receiverType",
            "amountCurrency",
            "amount",
            "sourceCurrency",
            "targetCurrency",
            "sortCode",
            "accountNumber",
            "IBAN",
            "BIC",
        ]
    )

    count = 0
    total_amount = 0
    max_id = 0
    for request in query:
        if request.method != "banktransfer":
            continue

        if count == number:
            break

        payment = request.payment
        if request.currency != payment.currency or request.currency != currency:
            continue

        refund_amount = payment.amount - request.donation

        total_amount += refund_amount
        if total_amount > amount:
            break

        if refund_amount > 0:
            writer.writerow(
                [
                    request.id,
                    request.payee_name,
                    "EMF Ticket Refund",
                    "PRIVATE",
                    request.currency,
                    refund_amount,
                    request.currency,
                    request.currency,
                    request.sort_code,
                    request.account,
                    request.iban,
                    request.swiftbic,
                ]
            )
            count += 1
        max_id = request.id

    print(io.getvalue())
    app.logger.info(f"Refunds produced for currency {currency} up to id {max_id}")


@payments.cli.command("transferwise_refund_complete")
@click.argument("currency", type=click.Choice(["GBP", "EUR"]))
@click.argument("max_id", type=int)
def transferwise_refund_complete(max_id, currency):
    """Mark Transferwise bulk refunds as completed"""
    query = (
        RefundRequest.query.join(Payment)
        .filter(Payment.state == "refund-requested")
        .filter(RefundRequest.id <= max_id)
        .order_by(RefundRequest.id)
    )

    for request in query:
        if request.method != "banktransfer":
            continue

        if request.currency != request.payment.currency or request.currency != currency:
            continue

        manual_bank_refund(request)
