from flask import request, redirect, url_for, render_template
from models.user import User
from models.payment import GoCardlessPayment, StripePayment, BankPayment
from sqlalchemy import func
from . import admin


def to_query(q):
    return " & ".join(q.split(" "))


@admin.route("/search")
def search():
    q = request.args["q"]

    email_exact = User.query.filter(User.email == q).one_or_none()
    if email_exact:
        return redirect(url_for(".user", user_id=email_exact.id))

    gc_exact = GoCardlessPayment.query.filter(
        (GoCardlessPayment.gcid == q) | (GoCardlessPayment.mandate == q)
    ).one_or_none()
    if gc_exact:
        return redirect(url_for(".payment", payment_id=gc_exact.id))

    stripe_exact = StripePayment.query.filter(
        (StripePayment.charge_id == q) | (StripePayment.intent_id == q)
    ).one_or_none()
    if stripe_exact:
        return redirect(url_for(".payment", payment_id=stripe_exact.id))

    bank_exact = BankPayment.query.filter(BankPayment.bankref == q).one_or_none()
    if bank_exact:
        return redirect(url_for(".payment", payment_id=bank_exact.id))

    email_query = to_query(q.replace("@", " "))

    # Careful with the following query. It'll stop using the indexes if you change the
    # functions applied to the indexed columns. Which isn't really the end of the world given
    # how small our dataset is, but I spent ages trying to work out how to get Alembic to add
    # those indexes. So humour me.
    results = User.query.filter(
        func.to_tsvector("simple", User.name).match(to_query(q))
        | (
            func.to_tsvector("simple", func.replace(User.email, "@", " ")).match(
                email_query
            )
        )
    )
    return render_template("admin/search-results.html", q=q, results=results)
