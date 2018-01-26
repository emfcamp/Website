# coding=utf-8
from __future__ import division, absolute_import, print_function, unicode_literals
from datetime import datetime, timedelta

from flask import (
    render_template, redirect, request, flash,
    url_for, current_app as app, Blueprint
)

from wtforms.validators import Optional, Required, URL
from wtforms import (
    SubmitField, BooleanField, HiddenField, StringField,
    FieldList, FormField, SelectField, FloatField, IntegerField
)

from sqlalchemy.sql.functions import func

from main import db
from models.user import User
from models.payment import (
    Payment, BankPayment,
    BankTransaction,
)
from models.product import ProductGroup, Product, PriceTier
from models.purchase import (
    Purchase, Ticket, AdmissionTicket,
)
from models.cfp import Proposal
from models.ical import CalendarSource
from models.feature_flag import FeatureFlag, DB_FEATURE_FLAGS, refresh_flags
from models.site_state import SiteState, VALID_STATES, refresh_states
from ..common import require_permission
from ..common.forms import Form, TelField
from ..common.receipt import render_parking_receipts


admin = Blueprint('admin', __name__)

admin_required = require_permission('admin')  # Decorator to require admin permissions


@admin.context_processor
def admin_variables():
    if not request.path.startswith('/admin'):
        return {}

    unreconciled_count = BankTransaction.query.filter_by(payment_id=None, suppressed=False).count()

    expiring_count = BankPayment.query.join(Purchase).filter(
        BankPayment.state == 'inprogress',
        BankPayment.expires < datetime.utcnow() + timedelta(days=3),
    ).group_by(BankPayment.id).count()

    return {'unreconciled_count': unreconciled_count,
            'expiring_count': expiring_count,
            'view_name': request.url_rule.endpoint.replace('admin.', '.')}


@admin.route("/stats")
def stats():
    paid_all = Ticket.query.filter_by(is_paid_for=True)
    parking_paid = paid_all.join(PriceTier, Product, ProductGroup).filter_by(type='parking').count()
    campervan_paid = paid_all.join(PriceTier, Product, ProductGroup).filter_by(type='campervan').count()

    # Don't care about the state of the payment if it's paid for
    paid = AdmissionTicket.query.filter(is_paid_for=True)

    # For new payments, the user hasn't committed to paying yet
    unpaid = AdmissionTicket.filter_by(is_paid_for=False).join(Payment).filter(
        Payment.state != 'new',
        Payment.state != 'cancelled',
    )

    expired = unpaid.filter_by(expired=True)
    unexpired = unpaid.filter_by(expired=False)

    # Providers who take a while to clear - don't care about captured Stripe payments
    gocardless_unpaid = unpaid.filter(Payment.provider == 'gocardless',
                                      Payment.state == 'inprogress')
    banktransfer_unpaid = unpaid.filter(Payment.provider == 'banktransfer',
                                        Payment.state == 'inprogress')

    admissions_gocardless_unexpired = unexpired.filter(
        Payment.provider == 'gocardless',
        Payment.state == 'inprogress',
    ).join(AdmissionTicket)

    admissions_banktransfer_unexpired = unexpired.filter(
        Payment.provider == 'banktransfer',
        Payment.state == 'inprogress',
    ).join(AdmissionTicket)

    # These are people queries - don't care about cars or campervans being checked in
    checked_in = AdmissionTicket.query.filter_by(checked_in=True)
    badged_up = AdmissionTicket.query.filter_by(badged_up=True)

    users = User.query  # noqa

    proposals = Proposal.query

    # Simple count queries
    queries = [
        'checked_in', 'badged_up',
        'users',
        'proposals',
        'gocardless_unpaid', 'banktransfer_unpaid',
        'full_gocardless_unexpired', 'full_banktransfer_unexpired',
    ]
    stats = ['{}:{}'.format(q, locals()[q].count()) for q in queries]

    # Ticket types breakdown
    ticket_types = ['admission', 'campervan', 'parking']
    ticket_type_totals = dict.fromkeys(ticket_types, 0)

    for query in 'paid', 'expired', 'unexpired':
        counts = locals()[query].join(PriceTier, Product, ProductGroup) \
            .filter(ProductGroup.type.in_(ticket_types)) \
            .with_entities(
                ProductGroup.type,
                func.count()) \
            .group_by(ProductGroup.type).all()
        counts = dict(counts)

        for t in ticket_types:
            stats.append('{}_{}:{}'.format(t, query, counts.get(t, 0)))
            ticket_type_totals[t] += counts.get(t, 0)

    for t in ticket_types:
        stats.append('{}:{}'.format(t, ticket_type_totals[t]))

    return ' '.join(stats)


@admin.route('/')
@admin_required
def home():
    return render_template('admin/admin.html')


class UpdateFeatureFlagForm(Form):
    # We don't allow changing feature flag names
    feature = HiddenField('Feature name', [Required()])
    enabled = BooleanField('Enabled')


class FeatureFlagForm(Form):
    flags = FieldList(FormField(UpdateFeatureFlagForm))
    new_feature = SelectField('New feature name', [Optional()],
                              choices=[('', 'Add a new flag')] +
                              list(zip(DB_FEATURE_FLAGS, DB_FEATURE_FLAGS)))
    new_enabled = BooleanField('New feature enabled', [Optional()])
    update = SubmitField('Update flags')


@admin.route('/feature-flags', methods=['GET', 'POST'])
@admin_required
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
                app.logger.info('Updating flag %s to %s', feature, flg.enabled.data)
                db_flag_dict[feature].enabled = flg.enabled.data
                db.session.commit()
                refresh_flags()

        # Add new flags if required
        if form.new_feature.data:
            new_flag = FeatureFlag(feature=form.new_feature.data,
                                   enabled=form.new_enabled.data)

            app.logger.info('Overriding new flag %s to %s', new_flag.feature, new_flag.enabled)
            db.session.add(new_flag)
            db.session.commit()
            refresh_flags()

            db_flags = FeatureFlag.query.all()

            # Unset previous form values
            form.new_feature.data = ''
            form.new_enabled.data = ''

    # Clear the list of flags (which may be stale)
    for old_field in range(len(form.flags)):
        form.flags.pop_entry()

    # Build the list of flags to display
    for flg in sorted(db_flags, key=lambda x: x.feature):
        form.flags.append_entry()
        form.flags[-1].feature.data = flg.feature
        form.flags[-1].enabled.data = flg.enabled

    return render_template('admin/feature-flags.html', form=form)


class SiteStateForm(Form):
    site_state = SelectField('Site', choices=[('', '(automatic)')] +
                             list(zip(VALID_STATES['site_state'], VALID_STATES['site_state'])))
    sales_state = SelectField('Sales', choices=[('', '(automatic)')] +
                              list(zip(VALID_STATES['sales_state'], VALID_STATES['sales_state'])))
    update = SubmitField('Update states')


@admin.route('/site-states', methods=['GET', 'POST'])
@admin_required
def site_states():
    form = SiteStateForm()

    db_states = SiteState.query.all()
    db_states = {s.name: s for s in db_states}

    if request.method != 'POST':
        # Empty form
        for name in VALID_STATES.keys():
            if name in db_states:
                getattr(form, name).data = db_states[name].state

    if form.validate_on_submit():
        for name in VALID_STATES.keys():
            state_form = getattr(form, name)
            if state_form.data == '':
                state_form.data = None

            if name in db_states:
                if db_states[name].state != state_form.data:
                    app.logger.info('Updating state %s to %s', name, state_form.data)
                    db_states[name].state = state_form.data

            else:
                if state_form.data:
                    state = SiteState(name, state_form.data)
                    db.session.add(state)

        db.session.commit()
        refresh_states()
        return redirect(url_for('.site_states'))

    return render_template('admin/site-states.html', form=form)

@admin.route('/schedule-feeds')
@admin_required
def schedule_feeds():
    feeds = CalendarSource.query.all()
    return render_template('admin/schedule-feeds.html', feeds=feeds)

class ScheduleForm(Form):
    feed_name = StringField('Name', [Required()])
    url = StringField('iCal URL', [Required(), URL()])
    enabled = BooleanField('Enabled')
    main_venue = StringField('Main Venue')
    type = StringField('Type')
    phone = TelField('Phone')
    email = StringField('Email')
    lat = FloatField('lat', [Optional()])
    lon = FloatField('lon', [Optional()])
    priority = IntegerField('priority', [Optional()])

    submit = SubmitField('Save')

    def update_feed(self, feed):
        feed.name = self.feed_name.data
        feed.url = self.url.data
        feed.enabled = self.enabled.data
        feed.main_venue = self.main_venue.data
        feed.type = self.type.data
        feed.contact_phone = self.phone.data
        feed.contact_email = self.email.data
        feed.lat = self.lat.data
        feed.lon = self.lon.data
        feed.priority = self.priority.data

    def init_from_feed(self, feed):
        self.feed_name.data = feed.name
        self.url.data = feed.url
        self.enabled.data = feed.enabled
        self.main_venue.data = feed.main_venue
        self.type.data = feed.type
        self.phone.data = feed.contact_phone
        self.email.data = feed.contact_email
        self.lat.data = feed.lat
        self.lon.data = feed.lon
        self.priority.data = feed.priority

@admin.route('/schedule-feeds/<int:feed_id>', methods=['GET', 'POST'])
@admin_required
def feed(feed_id):
    feed = CalendarSource.query.get_or_404(feed_id)
    form = ScheduleForm()

    if form.validate_on_submit():
        form.update_feed(feed)
        db.session.commit()
        msg = "Updated feed %s" % feed.name
        flash(msg)
        app.logger.info(msg)
        return redirect(url_for('.feed', feed_id=feed_id))

    form.init_from_feed(feed)

    return render_template('admin/edit-feed.html', feed=feed, form=form)

@admin.route('/schedule-feeds/new', methods=['GET', 'POST'])
@admin_required
def new_feed():
    form = ScheduleForm()

    if form.validate_on_submit():
        feed = CalendarSource('')
        form.update_feed(feed)
        db.session.add(feed)
        db.session.commit()
        msg = "Created feed %s" % feed.name
        flash(msg)
        app.logger.info(msg)
        return redirect(url_for('.feed', feed_id=feed.id))
    return render_template('admin/edit-feed.html', form=form)

@admin.route('/parking-tickets', methods=['GET', 'POST'])
@admin_required
def parking_tickets():
    return render_parking_receipts()

from . import accounts  # noqa: F401
from . import payments  # noqa: F401
from . import products  # noqa: F401
from . import tickets  # noqa: F401
from . import users  # noqa: F401
from . import email  # noqa: F401


