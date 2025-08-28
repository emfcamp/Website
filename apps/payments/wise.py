import logging
from datetime import timedelta

from flask import abort, request
from flask import current_app as app
from pywisetransfer.exceptions import InvalidWebhookSignature
from pywisetransfer.webhooks import validate_request

from main import db, wise
from models import naive_utcnow
from models.payment import BankAccount, BankTransaction

from . import payments
from .banktransfer import reconcile_txns

logger = logging.getLogger(__name__)


webhook_handlers = {}


def webhook(type=None):
    def inner(f):
        webhook_handlers[type] = f
        return f

    return inner


@payments.route("/wise-webhook", methods=["POST"])
def wise_webhook():
    logger.debug(
        "Received Wise webhook request: data=%r headers=%r",
        request.data,
        request.headers,
    )

    environment = app.config["TRANSFERWISE_ENVIRONMENT"]
    try:
        validate_request(request=request, environment=environment)
    except InvalidWebhookSignature as e:
        logger.exception(e)
        abort(400)
    except Exception as e:
        logger.info(e)
        abort(400)

    schema_version = request.json.get("schema_version")
    if schema_version != "2.0.0":
        logger.warning("Unsupported Wise schema version %s", schema_version)
        abort(500)

    event_type = request.json.get("event_type")
    try:
        handler = webhook_handlers[event_type]
    except KeyError:
        logger.warning("Unhandled Wise webhook event type %s", event_type)
        # logger.info("Webhook data: %s", request.data)
        abort(500)

    try:
        return handler(event_type, request.json)
    except Exception:
        logger.exception("Unhandled exception during Wise webhook")
        # logger.info("Webhook data: %s", request.data)
        abort(500)


@webhook("balances#credit")
def wise_balance_credit(event_type, event):
    profile_id = event.get("data", {}).get("resource", {}).get("profile_id")
    if profile_id is None:
        logger.exception("Missing profile_id in Wise webhook")
        # logger.info("Webhook data: %s", request.data)
        abort(400)

    wise_balance_id = event.get("data", {}).get("resource", {}).get("id")
    if wise_balance_id is None:
        logger.exception("Missing balance-account id in Wise webhook")
        # logger.info("Webhook data: %s", request.data)
        abort(400)

    if wise_balance_id == 0:
        # A credit event with a balance account ID of 0 is sent when webhook connections are configured.
        return ("", 204)

    currency = event.get("data", {}).get("currency")
    if currency is None:
        logger.exception("Missing currency in Wise webhook")
        # logger.info("Webhook data: %s", request.data)
        abort(400)

    logger.info(
        "Checking Wise details for wise_balance_id %s and currency %s",
        wise_balance_id,
        currency,
    )
    # Find the Wise bank account in the application database
    bank_account = BankAccount.query.filter_by(
        wise_balance_id=wise_balance_id,
        currency=currency,
        active=True,
    ).first()
    if not bank_account:
        logger.warning("Could not find bank account")
        return ("", 204)

    try:
        sync_wise_statement(profile_id, wise_balance_id, currency)
    except Exception:
        logger.exception("Error fetching statement")
        return ("", 500)

    return ("", 204)


def sync_wise_statement(profile_id, wise_balance_id, currency):
    # Retrieve an account transaction statement for the past week
    interval_end = naive_utcnow()
    interval_start = interval_end - timedelta(days=7)
    statement = wise.balance_statements.statement(
        profile_id,
        wise_balance_id,
        currency,
        interval_start.isoformat() + "Z",
        interval_end.isoformat() + "Z",
    )

    # Lock the bank account as BankTransactions don't have an external unique ID
    # TODO: we could include referenceNumber to prevent this or at least detect issues
    bank_account = (
        BankAccount.query.with_for_update()
        .filter_by(
            wise_balance_id=wise_balance_id,
            currency=currency,
        )
        .one()
    )
    if not bank_account.active:
        logger.info(
            f"BankAccount for Wise balance account {wise_balance_id} and {currency} is not active, not syncing"
        )
        db.session.commit()
        return

    # Retrieve or construct transactions for each credit in the statement
    txns = []
    for transaction in statement.transactions:
        if transaction.type != "CREDIT":
            continue

        if transaction.details.type != "DEPOSIT":
            continue

        # Attempt to find transaction in the application database
        # TODO: we should probably check the amount_int, too
        txn = BankTransaction.query.filter_by(
            account_id=bank_account.id,
            posted=transaction.date,
            type=transaction.details.type.lower(),
            payee=transaction.details.paymentReference,
        ).first()

        # Construct a transaction record if not found
        if txn:
            continue

        txn = BankTransaction(
            account_id=bank_account.id,
            posted=transaction.date,
            type=transaction.details.type.lower(),
            amount=transaction.amount.value,
            payee=transaction.details.paymentReference,
            wise_id=transaction.referenceNumber,
        )
        db.session.add(txn)
        txns.append(txn)

    logger.info("Imported %s transactions", len(txns))
    db.session.commit()

    logger.info("Reconciling...")
    reconcile_txns(txns, doit=True)


def wise_business_profile():
    if app.config.get("TRANSFERWISE_PROFILE_ID"):
        id = int(app.config["TRANSFERWISE_PROFILE_ID"])
        accounts = list(wise.account_details.list(profile_id=id))
        if len(accounts) == 0:
            raise Exception("Provided TRANSFERWISE_PROFILE_ID has no accoutns")
    else:
        # Wise bug:
        # As of 11-2021, this endpoint only returns one random business profile.
        # So if you have multiple business profiles (as we do in production),
        # you'll need to set it manually as above.
        profiles = wise.profiles.list(type="business")
        profiles = list(filter(lambda p: p.type == "business", profiles))

        if len(profiles) > 1:
            raise Exception("Multiple business profiles found")
        id = profiles[0].id
    return id


def _retrieve_detail(details, requested_type):
    """Helper method to retrieve content from attribute-value details recordsets"""
    for detail in details:
        if detail.type == requested_type:
            return detail.body


def wise_retrieve_accounts(profile_id):
    for account in wise.accounts.list(profile_id=profile_id):

        account_holder = bank_name = bank_address = sort_code = account_number = swift = iban = None

        if account.currency.code == "GBP":

            for receive_options in account.receiveOptions:

                account_holder = _retrieve_detail(details, "ACCOUNT_HOLDER")
                bank_info = _retrieve_detail(details, "BANK_NAME_AND_ADDRESS")

                if receive_options.type == "LOCAL":
                    sort_code = _retrieve_detail(details, "BANK_CODE").replace("-", "")
                    account_number = _retrieve_detail(details, "ACCOUNT_NUMBER")

                elif receive_options.type == "INTERNATIONAL":
                    swift = _retrieve_detail(details, "SWIFT_CODE")
                    iban = _retrieve_detail(details, "IBAN")

             if not bank_info:
                 continue

             bank_name, _, bank_address = bank_info.partition("\n")

             if not bank_name or not bank_address:
                 continue

        yield BankAccount(
            sort_code=sort_code,
            acct_id=account_number,
            currency=account.currency.code,
            active=False,
            payee_name=account_holder,
            institution=bank_name,
            address=bank_address,
            swift=swift,
            iban=iban,
            # Webhooks only include the borderlessAccountId
            wise_balance_id=account.id,
        )


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
        wise.users.me()
        result.append((True, "Connection to Wise API succeeded"))
    except Exception as e:
        result.append((False, f"Unable to connect to Wise: {e}"))
        return result

    business_profile = wise_business_profile()
    if business_profile:
        result.append((True, "Wise business profile exists"))
    else:
        result.append((False, "Wise business profile does not exist"))

    webhooks = wise.subscriptions.list(profile_id=business_profile)
    if webhooks:
        result.append((True, "Webhook event subscriptions are present"))
    else:
        result.append((False, "Webhook event subscriptions are not present"))

    return result
