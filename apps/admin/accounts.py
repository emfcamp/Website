# coding=utf-8
from __future__ import division, absolute_import, print_function, unicode_literals
from . import admin
import re

from Levenshtein import ratio, jaro
from flask import (
    render_template, redirect, flash,
    url_for, current_app as app,
)
from flask_login import current_user
from flask_mail import Message

from wtforms import SubmitField

from main import db, mail
from models.payment import BankPayment, BankTransaction

from ..common import feature_enabled
from ..common.forms import Form
from ..common.receipt import attach_tickets, set_tickets_emailed


@admin.route('/transactions')
def transactions():
    txns = BankTransaction.query.filter_by(payment_id=None, suppressed=False).\
        order_by(BankTransaction.posted.desc())
    return render_template('admin/accounts/txns.html', txns=txns)


class TransactionSuppressForm(Form):
    suppress = SubmitField("Suppress")


@admin.route('/transaction/<int:txn_id>/suppress', methods=['GET', 'POST'])
def transaction_suppress(txn_id):
    txn = BankTransaction.query.get_or_404(txn_id)

    form = TransactionSuppressForm()
    if form.validate_on_submit():
        if form.suppress.data:
            txn.suppressed = True
            app.logger.info('Transaction %s suppressed', txn.id)

            db.session.commit()
            flash("Transaction %s suppressed" % txn.id)
            return redirect(url_for('admin.transactions'))

    return render_template('admin/accounts/txn-suppress.html', txn=txn, form=form)


@admin.route('/transactions/suppressed')
def suppressed():
    suppressed = BankTransaction.query.filter_by(suppressed=True).all()
    return render_template('admin/accounts/txns-suppressed.html', suppressed=suppressed)


def score_reconciliation(txn, payment):
    words = list(filter(None, re.split('\W+', txn.payee)))

    bankref_parts = [payment.bankref[:4], payment.bankref[4:]]
    bankref_distances = [ratio(w, p) for w in words for p in bankref_parts]
    # Get the two best matches, for the two parts of the bankref
    # A match gives 1.0, a 2-char substring 0.666, and a 6-char superstring 0.857
    bankref_score = sum(sorted(bankref_distances)[-2:])
    name_score = jaro(txn.payee, payment.user.name)

    other_score = 0.0

    if txn.amount == payment.amount:
        other_score += 0.4

    if txn.account.currency == payment.currency:
        other_score += 0.6

    # check posted against expiry?

    app.logger.debug('Scores for txn %s payment %s: %s %s %s',
                     txn.id, payment.id, bankref_score, name_score, other_score)
    return bankref_score + name_score + other_score


@admin.route('/transaction/<int:txn_id>/reconcile')
def transaction_suggest_payments(txn_id):
    txn = BankTransaction.query.get_or_404(txn_id)

    payments = BankPayment.query.filter_by(state='inprogress').order_by(BankPayment.bankref).all()
    payments = sorted(payments, key=lambda p: score_reconciliation(txn, p))
    payments = list(reversed(payments[-20:]))

    app.logger.info('Suggesting %s payments for txn %s', len(payments), txn.id)
    return render_template('admin/accounts/txn-suggest-payments.html', txn=txn, payments=payments)


class ManualReconcilePaymentForm(Form):
    reconcile = SubmitField("Reconcile")


@admin.route('/transaction/<int:txn_id>/reconcile/<int:payment_id>', methods=['GET', 'POST'])
def transaction_reconcile(txn_id, payment_id):
    txn = BankTransaction.query.get_or_404(txn_id)
    payment = BankPayment.query.get_or_404(payment_id)

    form = ManualReconcilePaymentForm()
    if form.validate_on_submit():
        if form.reconcile.data:
            app.logger.info("%s manually reconciling against payment %s (%s) by %s",
                            current_user.name, payment.id, payment.bankref, payment.user.email)

            if txn.payment:
                app.logger.error("Transaction already reconciled")
                flash("Transaction %s already reconciled" % txn.id)
                return redirect(url_for('admin.transactions'))

            payment.lock()

            if payment.state == 'paid':
                app.logger.error("Payment has already been paid")
                flash("Payment %s already paid" % payment.id)
                return redirect(url_for('admin.transactions'))

            txn.payment = payment
            payment.paid()
            db.session.commit()

            msg = Message("Electromagnetic Field ticket purchase update",
                          sender=app.config['TICKETS_EMAIL'],
                          recipients=[payment.user.email])

            already_emailed = set_tickets_emailed(payment.user)
            msg.body = render_template("emails/tickets-paid-email-banktransfer.txt",
                                       user=payment.user, payment=payment,
                                       already_emailed=already_emailed)

            if feature_enabled('ISSUE_TICKETS'):
                attach_tickets(msg, payment.user)

            mail.send(msg)

            flash("Payment ID %s marked as paid" % payment.id)
            return redirect(url_for('admin.transactions'))

    return render_template('admin/accounts/txn-reconcile.html', txn=txn, payment=payment, form=form)


