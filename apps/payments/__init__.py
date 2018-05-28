from flask import (
    current_app as app, Blueprint,
    render_template, abort,
)
from flask_login import current_user

from models.payment import Payment

payments = Blueprint('payments', __name__)


def get_user_payment_or_abort(payment_id, provider=None, valid_states=None, allow_admin=False):
    try:
        payment = Payment.query.get(payment_id)
    except Exception as e:
        app.logger.warning('Exception %r getting payment %s', e, payment_id)
        abort(404)

    if not payment:
        app.logger.warning('Payment %s does not exist.', payment_id)
        abort(404)

    if not (payment.user == current_user or (allow_admin and current_user.has_permission('admin'))):
        app.logger.warning('User not allowed to access payment %s', payment_id)
        abort(404)

    if provider and payment.provider != provider:
        app.logger.warning('Payment %s is of type %s, not %s', payment.provider, provider)
        abort(404)

    if valid_states and payment.state not in valid_states:
        app.logger.warning("Payment %s is %s, not one of %s", payment_id, payment.state, valid_states)
        abort(404)

    return payment


def lock_user_payment_or_abort(payment_id, provider=None, valid_states=None, allow_admin=False):

    # This does an unlocked check on state, which is handy if it's invalid
    payment = get_user_payment_or_abort(payment_id, provider, valid_states, allow_admin)

    # Payments are not contended, so it's OK to do this early in requests
    payment.lock()
    if valid_states and payment.state not in valid_states:
        app.logger.warning("Payment %s is %s, not one of %s", payment_id, payment.state, valid_states)
        abort(404)

    return payment


@payments.route("/pay/terms")
def terms():
    return render_template('terms.html')


from . import banktransfer  # noqa: F401
from . import gocardless  # noqa: F401
from . import stripe  # noqa: F401
from . import invoice # noqa: F401

