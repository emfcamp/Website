import logging
from datetime import datetime, timedelta
import re
import hmac
import hashlib
import json

from flask import (
    render_template,
    redirect,
    request,
    flash,
    url_for,
    current_app as app,
    abort,
)
from flask_login import login_required
from flask_mail import Message
from wtforms import SubmitField
import gocardless_pro.errors
from sqlalchemy.orm.exc import NoResultFound

from main import db, mail, external_url, gocardless_client, csrf
from models.payment import GoCardlessPayment
from ..common import feature_enabled
from ..common.receipt import attach_tickets, set_tickets_emailed
from ..common.forms import Form
from . import get_user_payment_or_abort, lock_user_payment_or_abort
from . import payments

logger = logging.getLogger(__name__)


class IgnoreWebhook(Exception):
    pass


webhook_handlers = {}


def webhook(resource=None, action=None):
    def inner(f):
        webhook_handlers[(resource, action)] = f
        return f

    return inner


def gocardless_start(payment):
    logger.info("Starting GoCardless flow for payment %s", payment.id)

    prefilled_customer = {"email": payment.user.email}
    match = re.match(r"^ *([^ ,]+) +([^ ,]+) *$", payment.user.name)
    if match:
        prefilled_customer.update(
            {"given_name": match.group(1), "family_name": match.group(2)}
        )

    params = {
        "description": "Electromagnetic Field",
        "session_token": str(payment.id),
        "success_redirect_url": external_url(
            "payments.gocardless_complete", payment_id=payment.id
        ),
        "prefilled_customer": prefilled_customer,
    }
    if payment.currency == "GBP":
        params["scheme"] = "bacs"
    elif payment.currency == "EUR":
        # sepa_cor1 isn't an option, so let's hope it upgrades automatically
        params["scheme"] = "sepa_core"

    redirect_flow = gocardless_client.redirect_flows.create(params=params)

    logger.debug("GoCardless redirect ID: %s", redirect_flow.id)
    assert payment.redirect_id is None
    payment.redirect_id = redirect_flow.id

    # "Redirect flows expire 30 minutes after they are first created. You cannot complete an expired redirect flow."
    # https://developer.gocardless.com/api-reference/#core-endpoints-redirect-flows
    payment.expires = datetime.utcnow() + timedelta(minutes=30)

    db.session.commit()

    return redirect(redirect_flow.redirect_url)


@payments.route("/pay/gocardless/<int:payment_id>/complete")
@login_required
def gocardless_complete(payment_id):
    payment = lock_user_payment_or_abort(payment_id, "gocardless", valid_states=["new"])
    untrusted_redirect_id = request.args.get("redirect_flow_id")
    if untrusted_redirect_id != payment.redirect_id:
        # This probably means the user changed currency but then completed a previous flow.
        # We don't get webhooks for flows, so validate it now.
        try:
            redirect_flow = gocardless_client.redirect_flows.get(untrusted_redirect_id)
        except gocardless_pro.errors.InvalidApiUsageError as e:
            logging.warn(
                "InvalidApiUsageError from GoCardless getting flow: %s", e.message
            )
            abort(404)

        if redirect_flow.session_token != str(payment.id):
            logging.error(
                "Invalid redirect_flow_id for payment %s: %r (%s)",
                payment.id,
                untrusted_redirect_id,
                redirect_flow.session_token,
            )
            abort(404)

        payment.redirect_id = redirect_flow.id

    logger.info(
        "Completing GoCardless payment %s (%s)", payment.id, payment.redirect_id
    )

    try:
        # We've already validated the redirect_id, so don't expect this to fail
        redirect_flow = gocardless_client.redirect_flows.complete(
            payment.redirect_id, params={"session_token": str(payment.id)}
        )
        payment.mandate = redirect_flow.links.mandate
        payment.state = "captured"
        db.session.commit()

        payment = lock_user_payment_or_abort(
            payment_id, "gocardless", valid_states=["captured"]
        )
    except gocardless_pro.errors.InvalidStateError as e:
        # Assume the webhook will do its magic
        logging.error(
            "InvalidStateError from GoCardless confirming mandate: %s", e.message
        )
        flash(
            "An error occurred with your mandate, please check below or contact {}".format(
                app.config["TICKETS_EMAIL"][1]
            )
        )
        return redirect(url_for("users.purchases"))

    except Exception as e:
        logger.error("Exception %r confirming mandate", e)
        flash(
            "An error occurred with your payment, please contact {}".format(
                app.config["TICKETS_EMAIL"][1]
            )
        )
        return redirect(url_for("users.purchases"))

    return create_gc_payment(payment)


@payments.route("/pay/gocardless/<int:payment_id>/waiting")
@login_required
def gocardless_waiting(payment_id):
    payment = get_user_payment_or_abort(
        payment_id, "gocardless", valid_states=["new", "inprogress", "paid"]
    )
    return render_template(
        "gocardless-waiting.html",
        payment=payment,
        days=app.config["EXPIRY_DAYS_GOCARDLESS"],
    )


def create_gc_payment(payment):
    try:
        logger.info("Creating GC payment for %s (%s)", payment.id, payment.mandate)
        gc_payment = gocardless_client.payments.create(
            params={
                "amount": payment.amount_int,
                "currency": payment.currency,
                "links": {"mandate": payment.mandate},
                "metadata": {"payment_id": str(payment.id)},
            },
            headers={"Idempotency-Key": str(payment.id)},
        )

        payment.gcid = gc_payment.id
        payment.state = "inprogress"

    except gocardless_pro.errors.ValidationFailedError as exc:
        currency_errors = [e for e in exc.errors if e["field"] == "currency"]
        if currency_errors:
            # e['message'] will be one of:
            #   'must be GBP for a bacs mandate'
            #   'must be EUR for a sepa_core mandate'
            logger.error("Currency exception %r confirming payment", exc)
            flash(
                "Your account cannot be used for {} payments".format(payment.currency)
            )
        else:
            logger.error("Exception %r confirming payment", exc)
            flash(
                "An error occurred with your payment, please contact {}".format(
                    app.config["TICKETS_EMAIL"][1]
                )
            )

        return redirect(url_for("users.purchases"))

    except Exception as e:
        logger.error("Exception %r confirming payment", e)
        flash(
            "An error occurred with your payment, please contact {}".format(
                app.config["TICKETS_EMAIL"][1]
            )
        )
        return redirect(url_for("users.purchases"))

    # We need to make sure of a 5 working days grace
    # for gocardless payments, so push the payment expiry forwards
    payment.expires = datetime.utcnow() + timedelta(
        days=app.config["EXPIRY_DAYS_GOCARDLESS"]
    )
    for purchase in payment.purchases:
        purchase.set_state("payment-pending")

    db.session.commit()
    logger.info("Reset expiry for payment %s", payment.id)

    # FIXME: determine whether these are tickets or generic products
    msg = Message(
        "Your EMF ticket purchase",
        sender=app.config["TICKETS_EMAIL"],
        recipients=[payment.user.email],
    )
    msg.body = render_template(
        "emails/tickets-purchased-email-gocardless.txt",
        user=payment.user,
        payment=payment,
    )
    mail.send(msg)

    return redirect(url_for(".gocardless_waiting", payment_id=payment.id))


@payments.route("/pay/gocardless/<int:payment_id>/tryagain")
@login_required
def gocardless_tryagain(payment_id):
    payment = lock_user_payment_or_abort(
        payment_id, "gocardless", valid_states=["new", "captured", "failed"]
    )

    if not feature_enabled("GOCARDLESS"):
        logger.error("Unable to retry payment %s as GoCardless is disabled", payment.id)
        flash("GoCardless is currently unavailable. Please try again later")
        return redirect(url_for("users.purchases"))

    if payment.state == "new":
        if payment.redirect_id is not None:
            redirect_flow = gocardless_client.redirect_flows.get(payment.redirect_id)

            # If the flow's already been used, we get additional entries in links,
            # a confirmation_url "for 15 minutes", and redirect_url disappears.
            if redirect_flow.redirect_url is None:
                logger.info(
                    "Assuming flow for payment %s (%s) is captured",
                    payment.id,
                    payment.redirect_id,
                )
                payment.set_state("captured")
                db.session.commit()
                return redirect(redirect_flow.redirect_url)

        # Otherwise, always try again. GC say flows are valid for
        # 30 minutes, but I don't want to hardcode that here.
        logger.info("Trying to capture payment %s again", payment.id)
        payment.redirect_id = None
        return gocardless_start(payment)

    elif payment.state == "captured":
        return create_gc_payment(payment)

    # At this point, we've probably got a valid mandate but the user had no funds.
    try:
        logger.info("Trying payment %s (%s) again", payment.id, payment.gcid)
        gocardless_client.payments.retry(payment.gcid)

        payment.state = "inprogress"
        db.session.commit()

    except gocardless_pro.errors.InvalidStateError as e:
        logging.error(
            "InvalidStateError from GoCardless retrying payment: %s", e.message
        )
        flash(
            "An error occurred with your payment, please check below or contact {}".format(
                app.config["TICKETS_EMAIL"][1]
            )
        )
        return redirect(url_for("users.purchases"))

    except Exception as e:
        logger.error("Exception %r retrying payment", e)
        flash(
            "An error occurred with your payment, please contact {}".format(
                app.config["TICKETS_EMAIL"][1]
            )
        )
        return redirect(url_for("users.purchases"))

    flash("Your GoCardless payment is being retried")
    return redirect(url_for("users.purchases"))


class GoCardlessCancelForm(Form):
    yes = SubmitField("Cancel payment")


@payments.route("/pay/gocardless/<int:payment_id>/cancel", methods=["GET", "POST"])
@login_required
def gocardless_cancel(payment_id):
    payment = lock_user_payment_or_abort(
        payment_id,
        "gocardless",
        # once it's inprogress, there's potentially money moving around
        valid_states=["new", "failed", "cancelled"],
    )

    if payment.state == "cancelled":
        logger.info("Payment %s has already been cancelled", payment.id)
        flash("Payment has already been cancelled")
        return redirect(url_for("users.purchases"))

    form = GoCardlessCancelForm(request.form)
    if form.validate_on_submit():
        if form.yes.data:

            try:
                if payment.gcid is not None:
                    gocardless_client.payments.cancel(payment.gcid)

            except gocardless_pro.errors.InvalidStateError as e:
                logging.error(
                    "InvalidStateError from GoCardless cancelling payment: %s",
                    e.message,
                )
                flash(
                    "An error occurred with your payment, please check below or contact {}".format(
                        app.config["TICKETS_EMAIL"][1]
                    )
                )
                return redirect(url_for("users.purchases"))

            logger.info("Cancelling GoCardless payment %s", payment.id)
            payment.cancel()
            db.session.commit()

            logger.info("Payment %s cancelled", payment.id)
            flash("Payment cancelled")

        return redirect(url_for("users.purchases"))

    return render_template("gocardless-cancel.html", payment=payment, form=form)


def is_valid_signature(request):
    secret = bytes(app.config.get("GOCARDLESS_WEBHOOK_SECRET"), "utf-8")
    computed_signature = hmac.new(secret, request.data, hashlib.sha256).hexdigest()
    provided_signature = request.headers.get("Webhook-Signature")
    return hmac.compare_digest(provided_signature, computed_signature)


@csrf.exempt
@payments.route("/gocardless-webhook", methods=["POST"])
def gocardless_webhook():
    # Documentation: https://developer.gocardless.com/api-reference/#appendix-webhooks
    # For testing, see https://developer.gocardless.com/getting-started/developer-tools/scenario-simulators/

    logger.debug("GoCardless webhook received: %s", request.data)
    if not is_valid_signature(request):
        logger.error("Unable to validate GoCardless webhook")
        abort(498)

    origin = request.headers.get("Origin")
    if origin not in [
        "https://api.gocardless.com",
        "https://api-sandbox.gocardless.com",
    ]:
        logger.error("Invalid webhook origin: %s", origin)
        abort(500)

    content_type = request.headers.get("Content-Type")
    if content_type != "application/json":
        logger.error("Invalid webhook content type: %s", content_type)
        abort(500)

    try:
        payload = json.loads(request.data.decode("utf-8"))
        for event in payload["events"]:
            resource = event["resource_type"]
            action = event["action"]
            # The examples suggest details is optional, despite being "recommended"
            origin = event.get("details", {}).get("origin")
            cause = event.get("details", {}).get("cause")
            logger.info(
                "Webhook resource type: %s, action: %s, cause: %s, origin: %s",
                resource,
                action,
                cause,
                origin,
            )

            try:
                handler = webhook_handlers[(resource, action)]
            except KeyError as e:
                try:
                    handler = webhook_handlers[resource, None]
                except KeyError as e:
                    handler = webhook_handlers[(None, None)]

            try:
                handler(resource, action, event)

            except IgnoreWebhook:
                pass

            finally:
                db.session.rollback()

    except Exception as e:
        logger.error("Unexpected exception during webhook: %r", e)
        abort(500)

    # As far as I can tell, the webhook response content is entirely
    # for my benefit, and they only check the first character of the
    # response code. As we log everything, and I don't want GC to be
    # a store of debug info, always return 204 No Content.
    #
    # We therefore don't need to worry about payloads with a mixture
    # of known and unknown events (the documentation is ambiguous).
    return ("", 204)


@webhook()
def gocardless_webhook_default(resource, action, event):
    logger.info("Default handler called for %s", event)


@webhook("mandates", "created")
@webhook("mandates", "submitted")
@webhook("mandates", "active")
@webhook("mandates", "reinstated")
@webhook("mandates", "transferred")
@webhook("mandates", "cancelled")
@webhook("mandates", "failed")
@webhook("mandates", "expired")
@webhook("mandates", "replaced")
def gocardless_webhook_mandate_ignore(resource, action, event):
    """ Ignore mandate-related noise
        https://developer.gocardless.com/api-reference/#events-mandate-actions
    """
    mandate = event["links"]["mandate"]
    logger.info("Received %s action for mandate %s", action, mandate)


def lock_payment_or_ignore(gcid):
    try:
        return GoCardlessPayment.query.filter_by(gcid=gcid).with_for_update().one()
    except NoResultFound:
        logger.warn("Payment for GC payment %s not found, skipping", gcid)
        # FIXME: if GC send us a payment.created before we've managed to
        # save gcid to the DB, is that worth replying with a 404 for?
        raise IgnoreWebhook()


# https://developer.gocardless.com/api-reference/#events-payment-actions
@webhook("payments", "created")
@webhook("payments", "submitted")
@webhook("payments", "paid_out")
def gocardless_webhook_payment_do_nothing(resource, action, event):
    gcid = event["links"]["payment"]
    payment = lock_payment_or_ignore(gcid)

    logging.info("Received %s action for gcid %s, payment %s", action, gcid, payment.id)


@webhook("payments", "failed")
def gocardless_webhook_payment_failed(resource, action, event):
    gcid = event["links"]["payment"]
    payment = lock_payment_or_ignore(gcid)

    logger.info("Received failed action for gcid %s, payment %s", gcid, payment.id)

    gc_payment = gocardless_client.payments.get(payment.gcid)
    if gc_payment.status != "failed":
        logger.error(
            "Payment status is %s (should be failed), ignoring", gc_payment.status
        )
        return

    gocardless_payment_failed(payment)


@webhook("payments", "resubmission_requested")
def gocardless_webhook_payment_retried(resource, action, event):
    gcid = event["links"]["payment"]
    payment = lock_payment_or_ignore(gcid)

    logger.info(
        "Received resubmission action for gcid %s, payment %s", gcid, payment.id
    )

    gc_payment = gocardless_client.payments.get(payment.gcid)
    logger.info("Payment status is %s", gc_payment.status)

    gocardless_payment_pending(payment)


@webhook("payments", "cancelled")
def gocardless_webhook_payment_cancelled(resource, action, event):
    gcid = event["links"]["payment"]
    payment = lock_payment_or_ignore(gcid)

    logger.info("Received cancelled action for gcid %s, payment %s", gcid, payment.id)

    gc_payment = gocardless_client.payments.get(payment.gcid)
    if gc_payment.status != "cancelled":
        logger.error(
            "Payment status is %s (should be cancelled), ignoring", gc_payment.status
        )
        return

    gocardless_payment_cancelled(payment)


@webhook("payments", "confirmed")
def gocardless_webhook_payment_confirmed(resource, action, event):
    gcid = event["links"]["payment"]
    payment = lock_payment_or_ignore(gcid)

    logger.info("Received confirmed action for gcid %s, payment %s", gcid, payment.id)

    gc_payment = gocardless_client.payments.get(payment.gcid)
    if gc_payment.status not in {"confirmed", "paid_out"}:
        logger.error(
            "Payment status is %s (should be confirmed or paid_out), ignoring",
            gc_payment.status,
        )
        return

    gocardless_payment_paid(payment)


@webhook("payments", "charged_back")
def gocardless_webhook_payment_charged_back(resource, action, event):
    gcid = event["links"]["payment"]
    payment = lock_payment_or_ignore(gcid)

    logger.info(
        "Received charged_back action for gcid %s, payment %s", gcid, payment.id
    )

    gc_payment = gocardless_client.payments.get(payment.gcid)
    if gc_payment.status != "charged_back":
        logger.error(
            "Payment status is %s (should be charged_back), ignoring", gc_payment.status
        )
        return

    gocardless_payment_charged_back(payment)


def gocardless_update_payment(payment):
    # Assumes payment is already locked

    gc_payment = gocardless_client.payments.get(payment.gcid)

    if gc_payment.status == "pending_submission":
        return gocardless_payment_pending(payment)

    elif gc_payment.status in {"confirmed", "paid_out"}:
        return gocardless_payment_paid(payment)

    elif gc_payment.status == "cancelled":
        return gocardless_payment_cancelled(payment)

    elif gc_payment.status == "failed":
        return gocardless_payment_failed(payment)

    elif gc_payment.status == "charged_back":
        return gocardless_payment_charged_back(payment)

    app.logger.warn("Unsupported payment status %s, ignoring", gc_payment.status)


def gocardless_payment_pending(payment):
    if payment.state == "inprogress":
        logger.info("Payment is already inprogress, skipping")
        return

    if payment.state != "failed":
        logger.error(
            "Current payment state is %s (should be failed), ignoring", payment.state
        )
        return

    logger.info("Setting payment %s to inprogress", payment.id)
    payment.state = "inprogress"
    db.session.commit()


def gocardless_payment_paid(payment):
    if payment.state == "paid":
        logger.info("Payment is already paid, ignoring")
        return

    if payment.state == "partrefunded":
        logger.info("Payment is already partially refunded, ignoring")
        return

    if payment.state != "inprogress":
        logger.error(
            "Current payment state is %s (should be inprogress), ignoring",
            payment.state,
        )
        return

    logger.info("Setting payment %s to paid", payment.id)
    payment.paid()

    msg = Message(
        "Your EMF ticket payment has been confirmed",
        sender=app.config["TICKETS_EMAIL"],
        recipients=[payment.user.email],
    )

    already_emailed = set_tickets_emailed(payment.user)
    msg.body = render_template(
        "emails/tickets-paid-email-gocardless.txt",
        user=payment.user,
        payment=payment,
        already_emailed=already_emailed,
    )

    if feature_enabled("ISSUE_TICKETS"):
        attach_tickets(msg, payment.user)

    db.session.commit()
    mail.send(msg)


def gocardless_payment_cancelled(payment):
    if payment.state == "cancelled":
        logger.info("Payment is already cancelled, ignoring")
        return

    if payment.state != "inprogress":
        logger.error(
            "Current payment state is %s (should be inprogress), ignoring",
            payment.state,
        )
        return

    logger.info("Setting payment %s to cancelled", payment.id)
    payment.cancel()
    db.session.commit()


def gocardless_payment_failed(payment):
    if payment.state == "failed":
        logger.info("Payment is already failed, skipping")
        return

    if payment.state in {"inprogress", "paid"}:
        logger.info("Setting payment %s to failed", payment.id)
        payment.state = "failed"

    else:
        logger.error(
            "Current payment state is %s (should be inprogress or paid), ignoring",
            payment.state,
        )
        return

    payment.expires = datetime.utcnow() + timedelta(
        days=app.config["EXPIRY_DAYS_GOCARDLESS"]
    )
    for purchase in payment.purchases:
        purchase.set_state("payment-pending")

    msg = Message(
        "Your EMF payment has failed",
        sender=app.config["TICKETS_EMAIL"],
        recipients=[payment.user.email],
    )
    msg.body = render_template("emails/payment-failed.txt", payment=payment)
    mail.send(msg)

    db.session.commit()

    if not app.config.get("TICKETS_NOTICE_EMAIL"):
        app.logger.warning("No tickets notice email configured, not sending")
        return

    msg = Message(
        "An EMF payment has failed",
        sender=app.config.get("TICKETS_EMAIL"),
        recipients=[app.config.get("TICKETS_NOTICE_EMAIL")[1]],
    )
    msg.body = render_template("emails/notice-payment-failed.txt", payment=payment)
    mail.send(msg)


def gocardless_payment_charged_back(payment):
    raise NotImplementedError("Chargebacks not supported yet")


def gocardless_validate():
    """ Validate that GoCardless is configured and operational"""
    result = []

    env = app.config.get("GOCARDLESS_ENVIRONMENT")
    if env == "sandbox":
        result.append((True, "Sandbox environment being used"))
    elif env == "live":
        result.append((True, "Live environment being used"))
    else:
        result.append((False, "No environment configured"))

    val = app.config.get("GOCARDLESS_ACCESS_TOKEN", "")
    if len(val) > 9:
        result.append((True, "Access token set"))
    else:
        result.append((False, "Access token not set"))

    secret = app.config.get("GOCARDLESS_WEBHOOK_SECRET", "")
    if len(secret) > 5:
        result.append((True, "Webhook secret set"))
    else:
        result.append((False, "Webhook secret not set"))

    try:
        gocardless_client.events.list().records
        result.append((True, f"Connection to GoCardless API succeeded"))
    except gocardless_pro.errors.InvalidApiUsageError as e:
        result.append((False, f"Unable to connect to GoCardless: {e}"))

    return result
