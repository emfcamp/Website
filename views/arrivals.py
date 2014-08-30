from main import app
from models.ticket import Ticket, TicketType, CheckinStateException, TicketCheckin
from models.user import User
from views import Form

from flask import (
    render_template, redirect, request, flash,
    url_for, abort, session,
)
from flask.json import jsonify
from flask.ext.login import current_user

from wtforms import (
    SubmitField,
)
from wtforms.validators import Optional
from sqlalchemy import or_

from functools import wraps
import re

def arrivals_required(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        if current_user.is_authenticated():
            if current_user.arrivals:
                return f(*args, **kwargs)
            abort(404)
        return app.login_manager.unauthorized()
    return wrapped

@app.route('/arrivals')
@arrivals_required
def arrivals():
    badge = bool(session.get('badge'))
    return render_template('arrivals/arrivals.html', badge=badge)

@app.route('/arrivals/check-in')
def begin_check_in():
    session.pop('badge', None)
    return redirect(url_for('arrivals'))

@app.route('/arrivals/badge-up')
def begin_badge_up():
    session['badge'] = True
    return redirect(url_for('arrivals'))

@app.route('/arrivals/search')
@app.route('/arrivals/search/<query>')
@arrivals_required
def arrivals_search(query=None):
    if query is None:
        query = request.args.get('q')

    badge = bool(session.get('badge'))

    try:
        query = query.strip()

        if not query:
            if badge:
                tickets = []

            else:
                tickets = Ticket.query.filter_by(paid=True).join(User).join(TicketType) \
                                      .order_by(User.name, TicketType.order).limit(100)

        else:
            match = re.match(re.escape(app.config.get('CHECKIN_BASE')) + r'([0-9a-z]+)', query)
            if match:
                query = match.group(1)

            if badge:
                tickets = Ticket.query.join(TicketCheckin).filter_by(checked_in=True) \
                                      .filter( or_(Ticket.code.like('full%'), Ticket.code == 'kids_u16') )
            else:
                tickets = Ticket.query

            qrcode_tickets = tickets.filter( Ticket.qrcode == query )
            receipt_tickets = tickets.filter( Ticket.receipt == query)
            name_tickets = tickets.join(User).order_by(User.name)
            email_tickets = tickets.join(User).order_by(User.email)
            for word in filter(None, query.split(' ')):
                name_tickets = name_tickets.filter( User.name.ilike('%' + word + '%') )
                email_tickets = email_tickets.filter( User.email.ilike('%' + word + '%') )

            tickets = (qrcode_tickets.all() + receipt_tickets.all() +
                       name_tickets.limit(100).all() + email_tickets.limit(100).all())

        tickets_data = []
        emails_seen = set()
        for ticket in tickets:
            if ticket in emails_seen:
                continue
            emails_seen.add(ticket.user.email)

            if not ticket.receipt:
                # unpaid tickets won't have receipts
                ticket.create_receipt()

            ticket_data = {
                'name': ticket.user.name,
                'email': ticket.user.email,
                'type': ticket.type.name,
                'receipt': ticket.receipt,
                'paid': ticket.paid,
                'action': {},
            }
            if badge:
                if ticket.checkin.badged_up:
                    ticket_data['action']['badged_up'] = True
                    ticket_data['action']['url'] = url_for('arrivals_undo_checkin', receipts=ticket.receipt)
                else:
                    ticket_data['action']['badged_up'] = False
                    ticket_data['action']['url'] = url_for('arrivals_checkin', receipts=ticket.receipt)
            else:
                if ticket.checkin and ticket.checkin.checked_in:
                    ticket_data['action']['checked_in'] = True
                    ticket_data['action']['url'] = url_for('arrivals_undo_checkin', receipts=ticket.receipt)
                else:
                    ticket_data['action']['checked_in'] = False
                    ticket_data['action']['url'] = url_for('arrivals_checkin', receipts=ticket.receipt)

            tickets_data.append(ticket_data)

        data = {
            'tickets': tickets_data,
        }
        if len(emails_seen) == 1:
            data['all_receipts'] = url_for('arrivals_checkin', receipts=','.join(t.receipt for t in tickets))
        if request.args.get('n'):
            data['n'] = request.args.get('n')

        return jsonify(data), 200

    except Exception, e:
        return jsonify({'error': repr(e)}), 500

@app.route('/checkin/qrcode/<qrcode>')
@arrivals_required
def arrivals_checkin_qrcode(qrcode):
    ticket = Ticket.query.filter_by(qrcode=qrcode).one()
    return redirect(url_for('arrivals_checkin', receipts=ticket.receipt))


class CheckinForm(Form):
    proceed = SubmitField('Check in', [Optional()])
    undo = SubmitField('Undo check-in', [Optional()])

class BadgeUpForm(Form):
    proceed = SubmitField('Issue badge', [Optional()])
    undo = SubmitField('Return badge', [Optional()])


@app.route('/checkin/receipt/<receipts>', methods=['GET', 'POST'])
@arrivals_required
def arrivals_checkin(receipts):
    badge = bool(session.get('badge'))

    if badge:
        form = BadgeUpForm()
    else:
        form = CheckinForm()

    receipts = receipts.split(',')
    tickets = Ticket.query.filter( Ticket.receipt.in_(receipts) ).join(TicketType).order_by(TicketType.order)

    if form.validate_on_submit():
        failed = []
        for t in tickets:
            try:
                if badge:
                    t.badge_up()
                else:
                    t.check_in()
            except CheckinStateException:
                failed.append(t)

        if failed:
            flash("Already checked in: \n" +
                  ', '.join(t.receipt for t in failed))
            return redirect(url_for('arrivals_undo_checkin', receipts=','.join(t.receipt for t in tickets)))

        if tickets.count() == 1:
            flash("1 ticket checked in")
        else:
            flash("%s tickets checked in" % tickets.count())

        return redirect(url_for('arrivals'))

    user = tickets[0].user
    return render_template('arrivals/checkin_receipt.html', tickets=tickets, form=form,
                           user=user, receipts=','.join(t.receipt for t in tickets), badge=badge)

@app.route('/checkin/receipt/<receipts>/undo', methods=['GET', 'POST'])
@arrivals_required
def arrivals_undo_checkin(receipts):
    badge = bool(session.get('badge'))

    if badge:
        form = BadgeUpForm()
    else:
        form = CheckinForm()

    receipts = receipts.split(',')
    tickets = Ticket.query.filter( Ticket.receipt.in_(receipts) ).join(TicketType).order_by(TicketType.order)

    if form.validate_on_submit():
        failed = []
        for t in tickets:
            try:
                if badge:
                    t.undo_badge_up()
                else:
                    t.undo_check_in()
            except CheckinStateException:
                failed.append(t)

        if failed:
            flash("Not yet checked in: \n" +
                  ', '.join(t.receipt for t in failed))
            return redirect(url_for('arrivals_checkin', receipts=','.join(t.receipt for t in tickets)))

        if tickets.count() == 1:
            flash("1 ticket check-in undone")
        else:
            flash("%s tickets check-ins undone" % tickets.count())

        return redirect(url_for('arrivals'))

    user = tickets[0].user
    return render_template('arrivals/checkin_receipt_undo.html', tickets=tickets, form=form,
                           user=user, receipts=','.join(t.receipt for t in tickets), badge=badge)


