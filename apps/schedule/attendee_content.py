""" Views for attendees to manage their own content."""

from models.cfp import PYTHON_CFP_TYPES, Proposal, Venue, AGE_RANGE_OPTIONS
from sqlalchemy import or_, and_
from flask_login import login_required, current_user
from flask import (
    current_app as app,
    render_template,
    redirect,
    url_for,
    request,
)
from wtforms import (
    StringField,
    TextAreaField,
    SelectField,
    IntegerField,
    DecimalField,
    TimeField,
    BooleanField,
    SubmitField,
)
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
            private_venues = Venue.query.filter_by(
                village_id=user.village.id
            ).all()
            venues.extend(private_venues)

        public_venues = Venue.query.filter_by(
            village_id=None, scheduled_content_only=False
        ).all()
        venues.extend(public_venues)

        return [(v.id, v.name) for v in venues]

    def populate_choices(self, user):
        self.day.choices = self.day_choices()
        self.venue.choices = self.venues_for_user(user)

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
    published_names = StringField("Name", [DataRequired()])
    title = StringField("Title", [DataRequired()])
    description = TextAreaField("Description", [DataRequired()])
    day = SelectField(
        "Day",
    )
    scheduled_time = TimeField("Start time", [DataRequired()])
    scheduled_duration = IntegerField("Length", [DataRequired(), NumberRange(min=1)])
    attendees = IntegerField("Attendees", [Optional(), NumberRange(min=0)])
    cost = DecimalField("Cost per attendee", [Optional(), NumberRange(min=0)], places=2)
    participant_equipment = StringField("Attendee equipment")
    age_range = SelectField("Age range", choices=AGE_RANGE_OPTIONS)
    acknowledge_conflicts = BooleanField("Acknowledge conflicts")


def populate(proposal, form):
    proposal.type = form.type.data
    proposal.scheduled_venue_id = form.venue.data
    proposal.published_names = form.published_names.data
    proposal.title = proposal.published_title = form.title.data
    proposal.description = proposal.published_description = form.description.data
    proposal.scheduled_time = datetime.fromisoformat(
        "{}T{}".format(form.day.data, form.scheduled_time.data.strftime("%H:%M"))
    )
    proposal.length = proposal.scheduled_duration = form.scheduled_duration.data
    proposal.attendees = form.attendees.data
    proposal.cost = proposal.published_cost = form.cost.data
    proposal.age_range = proposal.published_age_range = form.age_range.data
    proposal.participant_equipment = (
        proposal.published_participant_equipment
    ) = form.participant_equipment.data


@schedule.route("/attendee_content", methods=["GET", "POST"])
@login_required
@feature_flag("ATTENDEE_CONTENT")
def attendee_content():
    # Yes, this is probably awful Python.
    venues = [venue.id for venue in Venue.query.filter_by(village_id=current_user.village.id).all()]
    content = Proposal.query.filter(
        or_(
            and_(Proposal.user_id == current_user.id, Proposal.user_scheduled == True),
            Proposal.scheduled_venue_id.in_(venues)
        ),
        Proposal.state.in_(["accepted", "finished"])
    ).all()

    form = ContentForm()
    form.populate_choices(current_user)

    if request.method == "POST" and form.validate():
        proposal = PYTHON_CFP_TYPES[form.type.data]()
        if proposal.user_id is None:
            proposal.user_id = current_user.id
            proposal.user_scheduled = True
            proposal.state = "finished"
        populate(proposal, form)

        conflicts = proposal.get_conflicting_content()
        if len(conflicts) > 0 and form.acknowledge_conflicts.data is not True:
            return render_template(
                "schedule/attendee_content/index.html",
                content=content,
                form=form,
                conflicts=conflicts,
            )

        db.session.add(proposal)
        db.session.commit()

        return redirect(url_for("schedule.attendee_content"))

    return render_template(
        "schedule/attendee_content/index.html",
        content=content,
        form=form,
        action=url_for("schedule.attendee_content"),
    )


@schedule.route("/attendee_content/<int:id>/edit", methods=["GET", "POST"])
@login_required
@feature_flag("ATTENDEE_CONTENT")
def attendee_content_edit(id):
    proposal = Proposal.query.filter_by(id=id).first()
    if not proposal or (proposal.user_id != current_user.id and proposal.scheduled_venue.village_id != current_user.village.id):
        return redirect(url_for("schedule.attendee_content"))

    form = ContentForm(obj=proposal)
    form.populate_choices(current_user)
    if request.method == "POST" and form.validate():
        populate(proposal, form)

        conflicts = proposal.get_conflicting_content()
        if len(conflicts) > 0 and form.acknowledge_conflicts.data is not True:
            return render_template(
                "schedule/attendee_content/index.html",
                form=form,
                conflicts=conflicts,
            )

        db.session.add(proposal)
        db.session.commit()

        return redirect(url_for("schedule.attendee_content"))

    return render_template(
        "schedule/attendee_content/edit.html",
        proposal=proposal,
        form=form,
        action=url_for("schedule.attendee_content_edit", id=id),
    )


class DeleteAttendeeContentForm(Form):
    delete = SubmitField("Delete content")


@schedule.route("/attendee_content/<int:id>/delete", methods=["GET", "POST"])
@login_required
@feature_flag("ATTENDEE_CONTENT")
def attendee_content_delete(id):
    proposal = Proposal.query.filter_by(id=id).first()
    if not proposal or proposal.user_id != current_user.id:
        return redirect(url_for("schedule.attendee_content"))

    form = DeleteAttendeeContentForm()

    if form.validate_on_submit():
        db.session.delete(proposal)
        db.session.commit()

        return redirect(url_for("schedule.attendee_content"))

    return render_template(
        "schedule/attendee_content/delete.html",
        proposal=proposal,
        form=form,
    )
