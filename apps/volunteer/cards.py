import json
from decorator import decorator
from flask import Response, abort, flash, redirect, render_template, request, url_for, current_app as app
from flask_login import current_user
from wtforms import SelectField, StringField, SubmitField
from wtforms.validators import InputRequired

from main import db
from apps.common.forms import Form
from apps.common.fields import HiddenIntegerField
from models.user import User
from models.volunteer.card import Card
from . import v_admin_required, volunteer


class CardForm(Form):
    printer = SelectField("Printer", [InputRequired()], choices=[["volunteer", "Volunteering"], ["hq", "HQ"]])
    type = SelectField(
        "Card Type",
        [InputRequired()],
        choices=[
            ["volunteer", "Volunteer"],
            ["orga", "Orga Member"],
            ["orga_lead", "Orga Lead"],
            ["brown", "Brown Role"],
            ["orange", "Orange Role"],
        ],
    )
    user_id = HiddenIntegerField("User ID", [InputRequired()])
    name = StringField("Preferred Name", [InputRequired()])
    alias = StringField("Alias")
    pronouns = StringField("Pronouns", [InputRequired()])
    line_one = StringField("Line One")
    line_two = StringField("Line Two")
    submit = SubmitField("Print ID")

def build_card_for(user: User) -> Card:
    return Card(volunteer_number=f"2024-{user.id}", name=user.name)


def card_for(user: User) -> tuple[CardForm, Card]:
    return Card(volunteer_number=f"2024-{user.id}", name=user.name, type="volunteer", printer="volunteer")


@volunteer.route("/cards", methods=["GET", "POST"])
@v_admin_required
def cards():
    if request.method == "POST":
        user = User.get_by_email(request.form.get("email"))
        if user is None:
            flash("No user was found with that email address.")
            return redirect(url_for(".cards"))
        else:
            card = card_for(user)
            form = CardForm(obj=card)
            form.user_id.data = user.id
            return render_template("volunteer/cards/index.html", user=user, form=form)

    return render_template("volunteer/cards/index.html")


@volunteer.route("/cards/issue", methods=["POST"])
@v_admin_required
def issue_card():
    user = User.query.get_or_404(request.form["user_id"])

    form = CardForm(data=request.form)
    form.user_id.data = user.id
    if not current_user.has_permission("admin"):
        # Force values for non-admins
        form.data.type = "volunteer"
        form.data.printer = "volunteer"

    if not form.validate():
        return render_template("volunteer/cards/index.html", user=user, form=form)

    card = card_for(user)
    form.populate_obj(card)
    db.session.add(card)

    db.session.commit()

    flash("Card created")
    return redirect(url_for(".cards"))


@decorator
def print_key_required(f, *args, **kwargs):
    if (
        "X_PRINTER_KEY" not in request.headers
        or "PRINTER_KEY" not in app.config
        or request.headers["X_PRINTER_KEY"] != app.config["PRINTER_KEY"]
    ):
        return abort(403)

    return f(*args, **kwargs)


@volunteer.route("/cards/queue.json")
@print_key_required
def queue():
    queued_jobs = Card.query.filter_by(state="queued").all()
    serialised = [
        {
            "job_id": card.id,
            "state": card.state,
            "volunteer_number": card.volunteer_number,
            "printer": card.printer,
            "type": card.type,
            "name": card.name,
            "alias": card.alias,
            "pronouns": card.pronouns,
            "line_one": card.line_one,
            "line_two": card.line_two,
        }
        for card in queued_jobs
    ]

    return Response(json.dumps(serialised), mimetype="application/json")


@volunteer.route("/cards/<int:card_id>/set_state", methods=["POST"])
@print_key_required
def set_print_job_state(card_id: int):
    state = request.json["state"]  # type: ignore
    card = Card.query.get_or_404(card_id)
    card.state = state

    db.session.add(card)
    db.session.commit()

    return Response("ok", mimetype="application/json")
