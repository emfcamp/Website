from datetime import datetime, timedelta
from flask import abort, current_app as app, request
import logging
import pywisetransfer
from pywisetransfer.webhooks import verify_signature

from main import csrf
from models.payment import BankAccount, BankTransaction
from . import payments

logger = logging.getLogger(__name__)


webhook_handlers = {}


def webhook(type=None):
    def inner(f):
        webhook_handlers[type] = f
        return f

    return inner


@csrf.exempt
@payments.route("/transferwise-webhook", methods=["POST"])
def transferwise_webhook():
    valid_signature = verify_signature(
        request.data,
        request.headers["X-Signature"],
    )
    if not valid_signature:
        logger.exception("Error verifying TransferWise webhook signature")
        abort(400)

    event_type = request.json.get("event_type")
    try:
        try:
            handler = webhook_handlers[event_type]
        except KeyError as e:
            handler = webhook_handlers[None]
        return handler(event_type, request.json)
    except Exception as e:
        logger.exception("Unhandled exception during TransferWise webhook")
        logger.info("Webhook data: %s", request.data)
        abort(500)


@webhook("balances#credit")
def transferwise_balance_credit(event_type, event):
    profile_id = event.get("data", {}).get("resource", {}).get("profile_id")
    if profile_id is None:
        logger.exception("Missing profile_id in TransferWise webhook")
        logger.info("Webhook data: %s", request.data)
        abort(400)

    borderless_account_id = event.get("data", {}).get("resource", {}).get("id")
    if borderless_account_id is None:
        logger.exception("Missing borderless_account_id in TransferWise webhook")
        logger.info("Webhook data: %s", request.data)
        abort(400)

    currency = event.get("data", {}).get("currency")
    if currency is None:
        logger.exception("Missing currency in TransferWise webhook")
        logger.info("Webhook data: %s", request.data)
        abort(400)

    # Find the TransferWise bank account in the application database
    bank_account = BankAccount.query.filter_by(
        borderless_account_id=borderless_account_id, active=True
    ).first()
    if not bank_account:
        logger.exception("Could not find bank account for borderless_account_id")
        logger.info("Webhook data: %s", request.data)
        abort(400)

    # Retrieve an account transaction statement for the past week
    client = pytransferwise.Client()
    interval_end = datetime.now()
    interval_start = interval_end - timedelta(days=7)
    statement = client.borderless_accounts.statement(
        profile_id=profile_id,
        account_id=borderless_account_id,
        currency=currency,
        interval_start=interval_start.isoformat() + "Z",
        interval_end=interval_end.isoformat() + "Z",
    )

    # Retrieve or construct transactions for each credit in the statement
    txns = []
    for transaction in statement.transactions:
        if transaction.type != "CREDIT":
            continue

        # Attempt to find transaction in the application database
        txn = BankTransaction.query.filter(
            account_id=bank_account.id,
            posted=transaction.date,
            type=transaction.details.type.lower(),
            payee=transaction.details.paymentReference,
        ).first()

        # Construct a transaction record if not found
        txn = txn or BankTransaction(
            account_id=bank_account.id,
            posted=transaction.date,
            type=transaction.details.type.lower(),
            amount=transaction.amount.value,
            payee=transaction.details.paymentReference,
        )
        txns.append(txn)

    # TODO: Reconcile txns <-> payments

    return ("", 204)


def transferwise_business_profile():
    client = pywisetransfer.Client()
    profiles = client.profiles.list(type="business")
    return next(profiles, None)


def _collect_bank_accounts(borderless_account):
    for balance in borderless_account.balances:
        try:
            if not balance.bankDetails:
                continue
            if not balance.bankDetails.bankAddress:
                continue
            if not balance.bankDetails.swift:
                continue
            if not balance.bankDetails.iban:
                continue
        except AttributeError:
            continue

        address = ", ".join(
            [
                balance.bankDetails.bankAddress.addressFirstLine,
                balance.bankDetails.bankAddress.city
                + " "
                + (balance.bankDetails.bankAddress.postCode or ""),
                balance.bankDetails.bankAddress.country,
            ]
        )
        yield BankAccount(
            sort_code=None,
            acct_id=None,
            currency=balance.bankDetails.currency,
            active=False,
            institution=balance.bankDetails.bankName,
            address=address,
            swift=balance.bankDetails.swift,
            iban=balance.bankDetails.iban,
            borderless_account_id=balance.id,
        )


def transferwise_retrieve_accounts():
    business_profile = transferwise_business_profile()
    if not business_profile:
        return

    client = pywisetransfer.Client()
    borderless_accounts = client.borderless_accounts.list(
        profile_id=business_profile.id
    )
    for borderless_account in borderless_accounts:
        for bank_account in _collect_bank_accounts(borderless_account):
            yield bank_account


def transferwise_validate():
    """Validate that TransferWise is configured and operational"""
    result = []

    env = app.config.get("TRANSFERWISE_ENVIRONMENT")
    if env == "sandbox":
        result.append((True, "Sandbox environment being used"))
    elif env == "live":
        result.append((True, "Live environment being used"))
    else:
        result.append((False, "No environment configured"))

    val = app.config.get("TRANSFERWISE_API_TOKEN", "")
    if len(val) == 36:
        result.append((True, "Access token set"))
    else:
        result.append((False, "Access token not set"))

    try:
        client = pywisetransfer.Client()
        user = client.users.me()
        result.append((True, "Connection to TransferWise API succeeded"))
    except Exception as e:
        result.append((False, f"Unable to connect to TransferWise: {e}"))

    business_profile = transferwise_business_profile()
    if business_profile:
        result.append((True, "TransferWise business profile exists"))
    else:
        result.append((False, "TransferWise business profile does not exist"))

    webhooks = client.subscriptions.list(profile_id=business_profile.id)
    if webhooks:
        result.append((True, "Webhook event subscriptions are present"))
    else:
        result.append((False, "Webhook event subscriptions are not present"))

    return result
