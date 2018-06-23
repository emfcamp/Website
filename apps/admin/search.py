from flask import request, redirect, url_for, render_template
from models.user import User
from models.payment import GoCardlessPayment, StripePayment, BankPayment
from sqlalchemy import func
from . import admin

@admin.route('/search')
def search():
    q = request.args['q']

    email_exact = User.query.filter(User.email == q).one_or_none()
    if email_exact:
        return redirect(url_for('.user', user_id=email_exact.id))

    gc_exact = GoCardlessPayment.query.filter(
        (GoCardlessPayment.gcid == q) | (GoCardlessPayment.mandate == q)).one_or_none()
    if gc_exact:
        return redirect(url_for('.payment', payment_id=gc_exact.id))

    stripe_exact = StripePayment.query.filter(StripePayment.chargeid == q).one_or_none()
    if stripe_exact:
        return redirect(url_for('.payment', payment_id=stripe_exact.id))

    bank_exact = BankPayment.query.filter(BankPayment.bankref == q).one_or_none()
    if bank_exact:
        return redirect(url_for('.payment', payment_id=bank_exact.id))

    results = User.query.filter(User.name.match(q) | (User.email.match(func.replace(q, '@', ' '))))
    return render_template('admin/search-results.html', q=q, results=results)
