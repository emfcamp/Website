""" Views for attendees to manage their own content."""

from models.cfp import PYTHON_CFP_TYPES, Proposal, Venue, AGE_RANGE_OPTIONS
from flask_login import login_required, current_user
from flask import (
    current_app as app,
    render_template,
    redirect,
    url_for,
    request,
)
from wtforms import StringField, TextAreaField, SelectField, IntegerField, DecimalField
from wtforms.validators import DataRequired, Optional, NumberRange
from datetime import date, datetime, timedelta

from main import db

from ..common.forms import Form
from ..common import feature_flag

from . import schedule


class ContentForm(Form):
    def day_choices(self):
        d = date.fromisoformat(app.config["EVENT_START"].split(" ")[0])
        end_date = date.fromisoformat(app.config["EVENT_END"].split(" ")[0])

        choices = []
        while d <= end_date:
            choices.append((d.isoformat(), d.strftime("%A - %d-%m-%Y")))
            d += timedelta(days=1)

        return choices

    def venues_for_user(self, user):
        venues = []

        if user.village:
            private_venues = Venue.query.filter_by(village_id=user.village.id).all()
            venues.extend(private_venues)

        public_venues = Venue.query.filter_by(
            village_id=None, scheduled_content_only=False
        ).all()
        venues.extend(public_venues)

        return [(v.id, v.name) for v in venues]

    type = SelectField(
        "Type of content",
        default="workshop",
        choices=[
            ("workshop", "Workshop"),
            ("youthworkshop", "Youth Workshop"),
            ("talk", "Talk"),
            ("performance", "Performance"),
        ],
    )
    venue = SelectField("Venue", [DataRequired()], coerce=int)
    name = StringField("Name", [DataRequired()])
    title = StringField("Title", [DataRequired()])
    description = TextAreaField("Description", [DataRequired()])
    day = SelectField(
        "Day",
    )
    start_time = StringField("Start time", [DataRequired()])
    length = IntegerField("Length", [DataRequired(), NumberRange(min=1)])
    attendees = IntegerField("Attendees", [Optional(), NumberRange(min=0)])
    cost = DecimalField("Cost per attendee", [Optional(), NumberRange(min=0)], places=2)
    participant_equipment = StringField("Attendee equipment")
    age_range = SelectField("Age range", choices=AGE_RANGE_OPTIONS)


@schedule.route("/attendee_content", methods=["GET", "POST"])
@login_required
@feature_flag("LINE_UP")
def attendee_content():
    content = Proposal.query.filter_by(
        user_id=current_user.id, user_scheduled=True
    ).all()

    form = ContentForm()
    form.day.choices = form.day_choices()
    form.venue.choices = form.venues_for_user(current_user)

    if request.method == "POST":
        if form.validate_on_submit():
            p = PYTHON_CFP_TYPES[form.type.data]()
            p.user_id = current_user.id
            p.user_scheduled = True
            p.state = "finished"
            p.type = form.type.data
            p.scheduled_venue_id = form.venue.data
            p.published_names = form.name.data
            p.title = p.published_title = form.title.data
            p.description = p.published_description = form.description.data
            p.scheduled_time = datetime.fromisoformat(
                "{}T{}".format(form.day.data, form.start_time.data)
            )
            p.length = p.scheduled_duration = form.length.data
            p.attendees = form.attendees.data
            p.cost = p.published_cost = form.cost.data
            p.age_range = p.published_age_range = form.age_range.data
            p.participant_equipment = (
                p.published_participant_equipment
            ) = form.participant_equipment.data

            db.session.add(p)
            db.session.commit()

            return redirect(url_for("schedule.attendee_content"))

    return render_template(
        "schedule/attendee_content/index.html",
        content=content,
        form=form,
    )
