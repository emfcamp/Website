from flask import redirect, render_template, request, url_for
from sqlalchemy import func

from main import db
from models.payment import BankPayment, StripePayment
from models.product import Voucher
from models.user import User

from . import admin


def to_query(q):
    return " & ".join(q.split(" "))


@admin.route("/search")
def search():
    q = request.args["q"].strip()

    email_exact = db.session.query(User).filter(User.email == q).one_or_none()
    if email_exact:
        return redirect(url_for(".user", user_id=email_exact.id))

    stripe_exact = (
        db.session.query(StripePayment)
        .filter((StripePayment.charge_id == q) | (StripePayment.intent_id == q))
        .one_or_none()
    )
    if stripe_exact:
        return redirect(url_for(".payment", payment_id=stripe_exact.id))

    bank_exact = db.session.query(BankPayment).filter(BankPayment.bankref == q).one_or_none()
    if bank_exact:
        return redirect(url_for(".payment", payment_id=bank_exact.id))

    voucher_exact = db.session.query(Voucher).filter(Voucher.code == q.lower()).one_or_none()
    if voucher_exact:
        return redirect(
            url_for(
                "admin.product_views.product_view_voucher_detail",
                view_id=voucher_exact.product_view_id,
                voucher_code=voucher_exact.code,
            )
        )

    email_query = to_query(q.replace("@", " "))

    # Careful with the following query. It'll stop using the indexes if you change the
    # functions applied to the indexed columns. Which isn't really the end of the world given
    # how small our dataset is, but I spent ages trying to work out how to get Alembic to add
    # those indexes. So humour me.
    results = db.session.query(User).filter(
        func.to_tsvector("simple", User.name).match(to_query(q), postgresql_regconfig="simple")
        | (
            func.to_tsvector("simple", func.replace(User.email, "@", " ")).match(
                email_query, postgresql_regconfig="simple"
            )
        )
    )
    return render_template("admin/search-results.html", q=q, results=results)
