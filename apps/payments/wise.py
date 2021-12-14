from datetime import datetime, timedelta
from flask import abort, current_app as app, request
import logging
import pywisetransfer
from pywisetransfer.webhooks import verify_signature

from models.payment import BankAccount, BankTransaction
from . import payments

logger = logging.getLogger(__name__)


webhook_handlers = {}


def webhook(type=None):
    def inner(f):
        webhook_handlers[type] = f
        return f

    return inner


@payments.route("/wise-webhook", methods=["POST"])
def wise_webhook():
    valid_signature = verify_signature(
        request.data,
        request.headers["X-Signature"],
    )
    if not valid_signature:
        logger.exception("Error verifying Wise webhook signature")
        abort(400)

    event_type = request.json.get("event_type")
    try:
        try:
            handler = webhook_handlers[event_type]
        except KeyError as e:
            handler = webhook_handlers[None]
        return handler(event_type, request.json)
    except Exception as e:
        logger.exception("Unhandled exception during Wise webhook")
        logger.info("Webhook data: %s", request.data)
        abort(500)


@webhook("balances#credit")
def wise_balance_credit(event_type, event):
    profile_id = event.get("data", {}).get("resource", {}).get("profile_id")
    if profile_id is None:
        logger.exception("Missing profile_id in Wise webhook")
        logger.info("Webhook data: %s", request.data)
        abort(400)

    borderless_account_id = event.get("data", {}).get("resource", {}).get("id")
    if borderless_account_id is None:
        logger.exception("Missing borderless_account_id in Wise webhook")
        logger.info("Webhook data: %s", request.data)
        abort(400)

    if borderless_account_id == 0:
        # A credit event with an account ID of 0 is sent when webhook connections are configured.
        return ("", 204)

    currency = event.get("data", {}).get("currency")
    if currency is None:
        logger.exception("Missing currency in Wise webhook")
        logger.info("Webhook data: %s", request.data)
        abort(400)

    # Find the Wise bank account in the application database
    bank_account = BankAccount.query.filter_by(
        borderless_account_id=borderless_account_id, active=True
    ).first()
    if not bank_account:
        logger.warn(
            "Could not find bank account for borderless_account_id %s",
            borderless_account_id,
        )
        return ("", 204)

    # Retrieve an account transaction statement for the past week
    client = pywisetransfer.Client()
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


def wise_business_profile():
    client = pywisetransfer.Client()

    if app.config.get("TRANSFERWISE_PROFILE_ID"):
        id = int(app.config["TRANSFERWISE_PROFILE_ID"])
        borderless_accounts = list(client.borderless_accounts.list(profile_id=id))
        if len(borderless_accounts) == 0:
            raise Exception("Provided TRANSFERWISE_PROFILE_ID has no accoutns")
    else:
        # Wise bug:
        # As of 11-2021, this endpoint only returns one random business profile.
        # So if you have multiple business profiles (as we do in production),
        # you'll need to set it manually as above.
        profiles = client.profiles.list(type="business")
        profiles = list(filter(lambda p: p.type == "business", profiles))

        if len(profiles) > 1:
            raise Exception("Multiple business profiles found")
        id = profiles[0].id
    return id


def _collect_bank_accounts(borderless_account):
    for account in borderless_account.balances:
        try:
            if not account.bankDetails:
                continue
            if not account.bankDetails.bankAddress:
                continue
        except AttributeError:
            continue

        address = ", ".join(
            [
                account.bankDetails.bankAddress.addressFirstLine,
                account.bankDetails.bankAddress.city
                + " "
                + (account.bankDetails.bankAddress.postCode or ""),
                account.bankDetails.bankAddress.country,
            ]
        )

        sort_code = account_number = None

        if account.bankDetails.currency == "GBP":
            # bankCode is the SWIFT code for non-GBP accounts.
            sort_code = account.bankDetails.bankCode

            if len(account.bankDetails.accountNumber) == 8:
                account_number = account.bankDetails.accountNumber
            else:
                # Wise bug:
                # accountNumber is sometimes erroneously the IBAN for GBP accounts.
                # Extract the account number from the IBAN.
                account_number = account.bankDetails.accountNumber.replace(" ", "")[-8:]

        yield BankAccount(
            sort_code=sort_code,
            acct_id=account_number,
            currency=account.bankDetails.currency,
            active=False,
            institution=account.bankDetails.bankName,
            address=address,
            swift=account.bankDetails.get("swift"),
            iban=account.bankDetails.get("iban"),
            borderless_account_id=account.id,
        )


def wise_retrieve_accounts():
    business_profile = wise_business_profile()

    if not business_profile:
        return

    client = pywisetransfer.Client()
    borderless_accounts = client.borderless_accounts.list(profile_id=business_profile)

    for borderless_account in borderless_accounts:
        for bank_account in _collect_bank_accounts(borderless_account):
            yield bank_account


def wise_validate():
    """Validate that Wise is configured and operational"""
    result = []

    env = app.config.get("TRANSFERWISE_ENVIRONMENT")
    if env == "sandbox":
        result.append((True, "Sandbox environment being used"))
    elif env == "live":
        result.append((True, "Live environment being used"))
    else:
        result.append((False, "No environment configured"))
        return result

    val = app.config.get("TRANSFERWISE_API_TOKEN", "")
    if len(val) == 36:
        result.append((True, "Access token set"))
    else:
        result.append((False, "Access token not set"))
        return result

    try:
        client = pywisetransfer.Client()
        client.users.me()
        result.append((True, "Connection to Wise API succeeded"))
    except Exception as e:
        result.append((False, f"Unable to connect to Wise: {e}"))
        return result

    business_profile = wise_business_profile()
    if business_profile:
        result.append((True, "Wise business profile exists"))
    else:
        result.append((False, "Wise business profile does not exist"))

    webhooks = client.subscriptions.list(profile_id=business_profile)
    if webhooks:
        result.append((True, "Webhook event subscriptions are present"))
    else:
        result.append((False, "Webhook event subscriptions are not present"))

    return result
