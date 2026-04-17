"""Views for attendees to manage their own content."""

from datetime import datetime, timedelta

from flask import current_app as app
from flask import (
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask.typing import ResponseReturnValue
from flask_login import current_user, login_required
from sqlalchemy import or_, select
from wtforms import (
    BooleanField,
    DecimalField,
    FieldList,
    FormField,
    IntegerField,
    SelectField,
    StringField,
    SubmitField,
    TextAreaField,
    TimeField,
)
from wtforms.validators import DataRequired, NumberRange, Optional

from apps.cfp_review.base import _convert_schedule_item
from apps.common.fields import HiddenIntegerField
from main import db, get_or_404
from models.content import (
    AGE_RANGE_OPTIONS,
    Occurrence,
    ScheduleItem,
    ScheduleItemType,
    Venue,
)
from models.user import User

from ..common import feature_flag
from ..common.forms import Form
from ..config import config
from . import schedule


def venues_for_user(user):
    # NB we use this for permissions, not ownership.
    # A user has create/edit access to all content scheduled in their village.
    # FIXME: enforce village role?
    venues = []

    if user.village:
        venues.extend(user.village.venues)

    public_venues = Venue.query.filter_by(village_id=None, allows_attendee_content=True).all()
    venues.extend(public_venues)

    return venues


class OccurrenceForm(Form):
    id = HiddenIntegerField("Occurrence ID", [DataRequired()])

    scheduled_duration = IntegerField("Duration", [DataRequired(), NumberRange(min=1)])

    scheduled_time_day = SelectField("Day", [DataRequired()])
    scheduled_time_time = TimeField("Start time", [DataRequired()])
    scheduled_venue_id = SelectField("Venue", [DataRequired()], coerce=int)

    # Attendees cannot set review themselves but we don't overwrite it if it's already set.
    video_privacy = SelectField(
        "Recording",
        default="public",
        choices=[
            ("public", "Stream and record"),
            ("review", "Do not stream, and do not publish until reviewed"),
            ("none", "Do not stream or record"),
        ],
    )

    def day_choices(self):
        d = config.event_start.date()
        end_date = config.event_end.date()

        choices = []
        while d <= end_date:
            choices.append((d.isoformat(), d.strftime("%A - %d-%m-%Y")))
            d += timedelta(days=1)

        return choices

    def load_choices(self, user: User, occurrence: Occurrence | None = None) -> None:
        if not occurrence or occurrence.video_privacy != "review":
            # Don't allow users to choose review themselves
            assert isinstance(self.video_privacy.choices, list)
            self.video_privacy.choices = [(c, _) for c, _ in self.video_privacy.choices if c != "review"]

        self.scheduled_time_day.choices = self.day_choices()
        self.scheduled_venue_id.choices = [(v.id, v.name) for v in venues_for_user(user)]

    def process(self, formdata=None, obj: Occurrence | None = None, data=None, **kwargs):  # type: ignore[no-untyped-def]
        super().process(formdata, obj, data, **kwargs)

        if formdata is None and obj is not None and obj.scheduled_time:
            self.scheduled_time_day.data = obj.scheduled_time.date().isoformat()
            self.scheduled_time_time.data = obj.scheduled_time.time()

    def populate_obj(self, obj):
        super().populate_obj(obj)
        assert self.scheduled_time_time.data is not None
        obj.scheduled_time = datetime.fromisoformat(
            f"{self.scheduled_time_day.data}T{self.scheduled_time_time.data.strftime('%H:%M')}"
        )


# See also cfp_review.forms.UpdateScheduleItemForm
class AttendeeContentForm(Form):
    type = SelectField(
        "Type of content",
        default="workshop",
        choices=[
            ("talk", "Talk"),
            ("performance", "Performance"),
            ("workshop", "Workshop"),
            ("youthworkshop", "Youth Workshop"),
        ],
    )
    # Attendees cannot hide or unhide schedule items but we still show the details
    state = SelectField(
        "State",
        choices=[("published", "Published"), ("unpublished", "Unpublished"), ("hidden", "Hidden")],
        default="published",
    )

    # Unlike UpdateScheduleItemForm we don't automatically populate, so there's no doxxing risk for names
    names = StringField("Name", [DataRequired()])
    pronouns = StringField("Pronouns")
    title = StringField("Title", [DataRequired()])
    description = TextAreaField("Description", [DataRequired()])
    short_description = StringField("Short description")

    # Attendees cannot set review themselves but we don't overwrite it if it's already set.
    default_video_privacy = SelectField(
        "Recording",
        default="public",
        choices=[
            ("public", "Stream and record"),
            ("review", "Do not stream, and do not publish until reviewed"),
            ("none", "Do not stream or record"),
        ],
    )

    # We're keeping these to official content only for now:

    # arrival_period
    # departure_period
    # available_times

    # contact_telephone
    # contact_eventphone

    # FIXME move attributes to another form
    # FIXME why do we ask for this?
    # attendees = IntegerField("Attendees", [Optional(), NumberRange(min=0)])
    participant_cost = DecimalField("Cost per attendee", [Optional(), NumberRange(min=0)], places=2)
    participant_equipment = StringField("Attendee equipment")
    age_range = SelectField("Age range", choices=AGE_RANGE_OPTIONS)

    acknowledge_conflicts = BooleanField("Acknowledge conflicts")

    occurrences = FieldList(FormField(OccurrenceForm))

    def load_choices(self, schedule_item: ScheduleItem | None = None) -> None:
        if not schedule_item or schedule_item.default_video_privacy != "review":
            # Don't allow users to choose review themselves
            assert isinstance(self.default_video_privacy.choices, list)
            self.default_video_privacy.choices = [
                (c, _) for c, _ in self.default_video_privacy.choices if c != "review"
            ]

        # Don't allow users to hide or unhide
        if not schedule_item or schedule_item.state != "hidden":
            assert isinstance(self.state.choices, list)
            self.state.choices = [(c, _) for c, _ in self.state.choices if c != "hidden"]
        elif schedule_item and schedule_item.state == "hidden":
            assert isinstance(self.state.choices, list)
            self.state.choices = [(c, _) for c, _ in self.state.choices if c == "hidden"]


@schedule.route("/attendee-content", methods=["GET", "POST"])
@login_required
@feature_flag("ATTENDEE_CONTENT")
def attendee_content() -> ResponseReturnValue:
    venue_ids = [v.id for v in venues_for_user(current_user)]

    # TODO: I don't really understand this logic, we only show
    # the user content they own if it's non-official - great.
    # But if something's scheduled in their venue we only show
    # it if they own it too? Why not show everything in the venue?
    # Or if we don't want to, why check the venue at all? Surely
    # they'd never own attendee content that isn't in their venue?
    # We also need to consider whether repeated content can be
    # scheduled into venues managed by different people, and if so
    # what permissions should they have? Do we use roles for this
    # instead?
    schedule_items = list(
        db.session.scalars(
            select(ScheduleItem).filter(
                ScheduleItem.user == current_user,
                or_(
                    ScheduleItem.official_content == False,
                    ScheduleItem.occurrences.any(
                        Occurrence.scheduled_venue_id.in_(venue_ids),
                    ),
                ),
            ),
        )
    )

    form = AttendeeContentForm()
    form.load_choices()

    if request.method != "POST":
        # We only allow one occurrence for now
        form.occurrences.append_entry()

    for field in form.occurrences:
        field.form.load_choices(current_user)
        del field.form.id

    if form.validate_on_submit():
        schedule_item_type: ScheduleItemType = form.type.data
        if schedule_item_type == "lightning":
            flash("Lightning talks cannot be added through this page")
            return redirect(url_for("schedule.attendee_content"))

        schedule_item = ScheduleItem(
            type=schedule_item_type,
            user=current_user,
            official_content=False,
        )

        occurrence = Occurrence(
            occurrence_num=1,
            state="scheduled",
            schedule_item=schedule_item,
        )

        form.populate_obj(schedule_item)

        conflicts = occurrence.get_conflicting_content()
        if len(conflicts) > 0 and form.acknowledge_conflicts.data is not True:
            return render_template(
                "schedule/attendee_content/index.html",
                schedule_items=schedule_items,
                form=form,
                conflicts=conflicts,
            )

        db.session.add(schedule_item)
        db.session.commit()

        return redirect(url_for("schedule.attendee_content"))

    return render_template(
        "schedule/attendee_content/index.html",
        schedule_items=schedule_items,
        form=form,
        action=url_for("schedule.attendee_content"),
    )


@schedule.route("/attendee-content/<int:schedule_item_id>/edit", methods=["GET", "POST"])
@login_required
@feature_flag("ATTENDEE_CONTENT")
def attendee_content_edit(schedule_item_id: int) -> ResponseReturnValue:
    schedule_item = db.session.scalar(select(ScheduleItem).filter_by(id=schedule_item_id))
    if not schedule_item:
        return redirect(url_for("schedule.attendee_content"))

    # TODO: See comment under attendee_content, this check makes more sense,
    # but doesn't take public venues into account. And they should match.
    in_user_managed_venue = False
    for occurrence in schedule_item.occurrences:
        if not occurrence.scheduled_venue:
            continue
        if occurrence.scheduled_venue.village_id == current_user.village.id:
            in_user_managed_venue = True

    if schedule_item.user != current_user and not in_user_managed_venue:
        return redirect(url_for("schedule.attendee_content"))

    form = AttendeeContentForm(obj=schedule_item)
    form.load_choices(schedule_item=schedule_item)

    occurrence_dict = {o.id: o for o in schedule_item.occurrences}
    for field in form.occurrences:
        f: OccurrenceForm = field.form
        if f.id.data not in occurrence_dict:
            f.id.data = None
            continue
        occurrence = occurrence_dict[f.id.data]
        f.load_choices(current_user, occurrence=occurrence)
        f._occurrence = occurrence

    if form.validate_on_submit():
        if form.type.data != schedule_item.type:
            _convert_schedule_item(schedule_item, form.type.data)

        form.populate_obj(schedule_item)

        for occurrence in schedule_item.occurrences:
            if (
                occurrence.state == "unscheduled"
                and occurrence.scheduled_duration
                and occurrence.scheduled_venue_id
                and occurrence.scheduled_time
            ):
                occurrence.state = "scheduled"

            # The attendee content form doesn't allow unscheduling

        conflicts = [c for o in schedule_item.occurrences for c in o.get_conflicting_content()]
        if any(conflicts) and form.acknowledge_conflicts.data is not True:
            return render_template(
                "schedule/attendee_content/edit.html",
                schedule_item=schedule_item,
                form=form,
                conflicts=conflicts,
            )

        db.session.commit()

        return redirect(url_for("schedule.attendee_content"))

    # form.day.data = schedule_item.scheduled_time.strftime("%Y-%m-%d")
    return render_template(
        "schedule/attendee_content/edit.html",
        schedule_item=schedule_item,
        form=form,
        action=url_for("schedule.attendee_content_edit", schedule_item_id=schedule_item_id),
    )


class DeleteAttendeeContentForm(Form):
    delete = SubmitField("Delete content")


@schedule.route("/attendee-content/<int:schedule_item_id>/delete", methods=["GET", "POST"])
@login_required
@feature_flag("ATTENDEE_CONTENT")
def attendee_content_delete(schedule_item_id):
    schedule_item = get_or_404(db, ScheduleItem, schedule_item_id)
    can_delete = schedule_item.user_id == current_user.id and not schedule_item.official_content
    if not can_delete:
        app.logger.warning(f"{current_user} cannot delete schedule item {schedule_item}")
        flash("You can't delete this content")
        return redirect(url_for("schedule.attendee_content"))

    form = DeleteAttendeeContentForm()

    if form.validate_on_submit():
        db.session.delete(schedule_item)
        db.session.commit()

        return redirect(url_for("schedule.attendee_content"))

    return render_template(
        "schedule/attendee_content/delete.html",
        schedule_item=schedule_item,
        form=form,
    )
