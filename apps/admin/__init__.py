from datetime import timedelta

import logging_tree
from flask import (
    Blueprint,
    abort,
    flash,
    make_response,
    redirect,
    render_template,
    request,
    url_for,
)
from flask import (
    current_app as app,
)
from flask_login import current_user
from wtforms import (
    BooleanField,
    FieldList,
    FormField,
    HiddenField,
    SelectField,
    SubmitField,
)
from wtforms.validators import DataRequired, Optional

from main import db
from models import naive_utcnow
from models.feature_flag import DB_FEATURE_FLAGS, FeatureFlag, refresh_flags
from models.payment import BankAccount, BankPayment, BankTransaction, Payment
from models.purchase import Purchase
from models.scheduled_task import ScheduledTaskResult, tasks
from models.site_state import VALID_STATES, SiteState, get_states, refresh_states

from ..common import require_permission
from ..common.forms import Form
from ..payments.stripe import stripe_validate
from ..payments.wise import (
    wise_business_profile,
    wise_retrieve_accounts,
    wise_validate,
)

admin = Blueprint("admin", __name__)

admin_required = require_permission("admin")  # Decorator to require admin permissions


@admin.before_request
def admin_require_permission():
    """Require admin permission for everything under /admin"""
    if not current_user.is_authenticated or not current_user.has_permission("admin"):
        abort(404)


@admin.context_processor
def admin_variables():
    if not request.path.startswith("/admin"):
        return {}

    requested_refund_count = Payment.query.filter_by(state="refund-requested").count()
    unreconciled_count = BankTransaction.query.filter_by(payment_id=None, suppressed=False).count()

    expiring_count = (
        BankPayment.query.join(Purchase)
        .filter(
            BankPayment.state == "inprogress",
            BankPayment.expires < naive_utcnow() + timedelta(days=3),
        )
        .group_by(BankPayment.id)
        .count()
    )

    return {
        "requested_refund_count": requested_refund_count,
        "unreconciled_count": unreconciled_count,
        "expiring_count": expiring_count,
        "view_name": request.url_rule.endpoint.replace("admin.", "."),
    }


@admin.route("/")
def home():
    return render_template("admin/admin.html")


class UpdateFeatureFlagForm(Form):
    # We don't allow changing feature flag names
    feature = HiddenField("Feature name", [DataRequired()])
    enabled = BooleanField("Enabled")


class FeatureFlagForm(Form):
    flags = FieldList(FormField(UpdateFeatureFlagForm))
    new_feature = SelectField(
        "New feature name",
        [Optional()],
        choices=[("", "Add a new flag")] + [(f, f) for f in DB_FEATURE_FLAGS],
    )
    new_enabled = BooleanField("New feature enabled", [Optional()])
    update = SubmitField("Update flags")


@admin.route("/feature-flags", methods=["GET", "POST"])
def feature_flags():
    form = FeatureFlagForm()
    db_flags = FeatureFlag.query.all()

    if form.validate_on_submit():
        # Update existing flags
        db_flag_dict = {f.feature: f for f in db_flags}
        for flg in form.flags:
            feature = flg.feature.data

            # Update the db and clear the cache if there's a change
            if db_flag_dict[feature].enabled != flg.enabled.data:
                app.logger.info("Updating flag %s to %s", feature, flg.enabled.data)
                db_flag_dict[feature].enabled = flg.enabled.data
                db.session.commit()
                refresh_flags()

        # Add new flags if required
        if form.new_feature.data:
            new_flag = FeatureFlag(feature=form.new_feature.data, enabled=form.new_enabled.data)

            app.logger.info("Overriding new flag %s to %s", new_flag.feature, new_flag.enabled)
            db.session.add(new_flag)
            db.session.commit()
            refresh_flags()

            db_flags = FeatureFlag.query.all()

            # Unset previous form values
            form.new_feature.data = ""
            form.new_enabled.data = ""

    # Clear the list of flags (which may be stale)
    for _ in range(len(form.flags)):
        form.flags.pop_entry()

    # Build the list of flags to display
    for flg in sorted(db_flags, key=lambda x: x.feature):
        form.flags.append_entry()
        form.flags[-1].feature.data = flg.feature
        form.flags[-1].enabled.data = flg.enabled

    return render_template("admin/feature-flags.html", form=form)


class SiteStateForm(Form):
    site_state = SelectField(
        "Site",
        choices=[(s, s) for s in VALID_STATES["site_state"]],
    )
    sales_state = SelectField(
        "Sales",
        choices=[("", "(automatic)")] + [(s, s) for s in VALID_STATES["sales_state"]],
    )
    refund_state = SelectField(
        "Refunds",
        choices=[(s, s) for s in VALID_STATES["refund_state"]],
    )
    signup_state = SelectField(
        "Signups",
        choices=[(s, s) for s in VALID_STATES["signup_state"]],
    )
    update = SubmitField("Update states")


@admin.route("/site-states", methods=["GET", "POST"])
def site_states():
    form = SiteStateForm()

    db_states = SiteState.query.all()
    db_states = {s.name: s for s in db_states}
    current_states = get_states()

    if request.method != "POST":
        # Empty form
        for name in VALID_STATES:
            # sales_state has an "automatic" state which we should preserve
            if name in db_states:
                getattr(form, name).data = db_states[name].state
            else:
                getattr(form, name).data = current_states[name]

    if form.validate_on_submit():
        for name in VALID_STATES:
            state_form = getattr(form, name)
            if state_form.data == "":
                state_form.data = None

            if name in db_states:
                if db_states[name].state != state_form.data:
                    app.logger.info("Updating state %s to %s", name, state_form.data)
                    db_states[name].state = state_form.data

            else:
                if state_form.data:
                    state = SiteState(name, state_form.data)
                    db.session.add(state)

        db.session.commit()
        refresh_states()
        return redirect(url_for(".site_states"))

    return render_template("admin/site-states.html", form=form)


class BankAccountRefreshForm(Form):
    import_accounts = SubmitField("Import new Wise accounts")


@admin.route("/payment-config/activate", methods=["POST"])
def activate_payment_config():
    if request.form.get("activate"):
        to_activate = BankAccount.query.filter_by(id=request.form["activate"]).first()
        # Deactivate other accounts with this currency
        for account in BankAccount.query.filter_by(currency=to_activate.currency):
            if account.id != to_activate.id:
                account.active = False
        to_activate.active = True
        db.session.commit()

    return redirect(url_for(".payment_config_verify"), 303)


@admin.route("/payment-config", methods=["GET", "POST"])
def payment_config_verify():
    form = BankAccountRefreshForm()

    if form.validate_on_submit():
        profile_id = wise_business_profile()

        if not profile_id:
            flash("Cannot identify Wise profile", "warning")
            return redirect(url_for(".payment_config_verify"), 303)

        accounts = wise_retrieve_accounts(profile_id)
        for account in accounts:
            existing_account = BankAccount.query.filter_by(
                wise_balance_id=account.wise_balance_id,
                currency=account.currency,
            ).first()
            if existing_account:
                continue
            db.session.add(account)

        if db.session.new:
            db.session.commit()
            flash("New Wise bank accounts have been imported", "info")
        else:
            flash("No new Wise bank accounts have been imported", "warning")

        return redirect(url_for(".payment_config_verify"), 303)

    return render_template(
        "admin/payment-config-verify.html",
        stripe=stripe_validate(),
        transferwise=wise_validate(),
        bank_accounts=BankAccount.query.order_by(
            BankAccount.active.desc(), BankAccount.currency.desc()
        ).all(),
        form=form,
        last_bank_payment=BankTransaction.query.order_by(BankTransaction.id.desc()).first(),
    )


@admin.route("/scheduled-tasks")
def scheduled_tasks():
    data = []
    for task in tasks:
        results = list(
            ScheduledTaskResult.query.filter_by(name=task.name)
            .order_by(ScheduledTaskResult.start_time.desc())
            .limit(10)
        )
        data.append({"task": task, "results": results})
    return render_template("admin/scheduled-tasks.html", data=data)


@admin.route("/logging-config")
def logging_config():
    response = make_response(logging_tree.format.build_description())
    response.headers["Content-Type"] = "text/plain"
    return response


from . import (
    accounts,  # noqa: F401
    admin_message,  # noqa: F401
    arrivals,  # noqa: F401
    email,  # noqa: F401
    hire,  # noqa: F401
    payments,  # noqa: F401
    products,  # noqa: F401
    reports,  # noqa: F401
    search,  # noqa: F401
    tickets,  # noqa: F401
    users,  # noqa: F401
)
