from main import app, db
from models.ticket import Ticket, TicketType, CheckinStateException
from models.user import User
from views import Form

from flask import (
    render_template, redirect, request, flash,
    url_for, abort,
)
from flask.json import jsonify
from flask.ext.login import current_user

from wtforms import (
    SubmitField,
)
from wtforms.validators import Optional

from sqlalchemy.orm.exc import NoResultFound
from sqlalchemy.sql.functions import func

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
    return render_template('arrivals/arrivals.html')

@app.route('/arrivals/search')
@app.route('/arrivals/search/<query>')
@arrivals_required
def arrivals_search(query=None):
    if query is None:
        query = request.args.get('q')

    try:
        query = query.strip()

        if not query:
            tickets = Ticket.query.filter_by(paid=True).join(User).join(TicketType) \
                                  .order_by(User.name, TicketType.order)

        else:
            match = re.match(re.escape(app.config.get('CHECKIN_BASE')) + r'([0-9a-z]+)', query)
            if match:
                query = match.group(1)

            qrcode_tickets = Ticket.query.filter_by(qrcode=query)
            receipt_tickets = Ticket.query.filter_by(receipt=query)
            name_tickets = Ticket.query.join(User).order_by(User.name)
            email_tickets = Ticket.query.join(User).order_by(User.email)
            for word in filter(None, query.split(' ')):
                name_tickets = name_tickets.filter( User.name.like('%' + word + '%') )
                email_tickets = email_tickets.filter( User.email.like('%' + word + '%') )

            tickets = (qrcode_tickets.all() + receipt_tickets.all() +
                       name_tickets.all() + email_tickets.all())

        # TODO: add multiselect, and if it's a qrcode/receipt, show all the tickets for that user?

        tickets_data = []
        tickets_seen = set()
        for ticket in tickets:
            if ticket in tickets_seen:
                continue
            tickets_seen.add(ticket)

            if not ticket.receipt:
                # unpaid tickets won't have receipts
                ticket.create_receipt()

            tickets_data.append({
                'name': ticket.user.name,
                'email': ticket.user.email,
                'type': ticket.type.name,
                'receipt': ticket.receipt,
                'receipt_url': url_for('arrivals_checkin', receipts=ticket.receipt),
            })
        return jsonify({'tickets': tickets_data}), 200

    except Exception, e:
        return jsonify({'error': repr(e)}), 500

@app.route('/checkin/qrcode/<qrcode>')
@arrivals_required
def arrivals_checkin_qrcode(qrcode):
    ticket = Ticket.query.filter_by(qrcode=qrcode).one()
    return redirect(url_for('arrivals_checkin', receipts=ticket.receipt))


class CheckinForm(Form):
    checkin = SubmitField('Check in', [Optional()])
    undo = SubmitField('Undo check-in', [Optional()])

@app.route('/checkin/receipt/<receipts>', methods=['GET', 'POST'])
@arrivals_required
def arrivals_checkin(receipts):
    form = CheckinForm()

    receipts = receipts.split(',')
    tickets = Ticket.query.filter( Ticket.receipt.in_(receipts) )

    if form.validate_on_submit():
        failed = []
        for t in tickets:
            try:
                t.check_in()
            except CheckinStateException:
                failed.append(t)

        if failed:
            flash("Already checked in: \n" +
                  ', '.join('%s at %s' % (t.receipt, t.checkin.timestamp.strftime('%H:%M %A')) for t in tickets))
            return redirect(url_for('arrivals_checkin', receipts=','.join(t.receipt for t in tickets)))

        if tickets.count() == 1:
            flash("1 ticket checked in")
        else:
            flash("%s tickets checked in" % tickets.count())

        return redirect(url_for('arrivals'))

    return render_template('arrivals/checkin_receipt.html', tickets=tickets, form=form, receipts=','.join(t.receipt for t in tickets))


