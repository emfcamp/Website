from main import app
from flask import render_template, redirect, url_for
from views.tickets import get_basket
from flask.ext.login import login_required

@app.route("/pay/terms")
def ticket_terms():
    return render_template('terms.html')

@app.route("/pay/choose")
@login_required
def pay_choose():
    basket, total = get_basket()

    if not basket:
        redirect(url_for('tickets'))

    return render_template('payment-choose.html', basket=basket, total=total)

