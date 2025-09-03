from flask import abort
from flask import current_app as app
from flask_login import current_user
from sqlalchemy import select

from main import db
from models.payment import Payment


def get_user_payment_or_abort(
    payment_id: int, provider=None, valid_states: list[str] | None = None, allow_admin=False
) -> Payment:
    try:
        payment = db.session.execute(select(Payment).where(Payment.id == payment_id)).scalar_one_or_none()
    except Exception as e:
        app.logger.exception("Exception %r getting payment %s", e, payment_id)
        abort(404)

    if not payment:
        app.logger.warning("Payment %s does not exist.", payment_id)
        abort(404)

    if not (payment.user == current_user or (allow_admin and current_user.has_permission("admin"))):
        app.logger.warning("User not allowed to access payment %s", payment_id)
        abort(404)

    if provider and payment.provider != provider:
        app.logger.warning("Payment %s is of type %s, not %s", payment.provider, provider)
        abort(404)

    if valid_states and payment.state not in valid_states:
        app.logger.warning("Payment %s is %s, not one of %s", payment_id, payment.state, valid_states)
        abort(404)

    return payment


def lock_user_payment_or_abort(payment_id, provider=None, valid_states=None, allow_admin=False) -> Payment:
    # This does an unlocked check on state, which is handy if it's invalid
    payment = get_user_payment_or_abort(payment_id, provider, valid_states, allow_admin)

    # Payments are not contended, so it's OK to do this early in requests
    payment.lock()
    if valid_states and payment.state not in valid_states:
        app.logger.warning("Payment %s is %s, not one of %s", payment_id, payment.state, valid_states)
        abort(404)

    return payment
