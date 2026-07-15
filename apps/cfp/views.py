from itertools import islice
from typing import get_args

from flask import (
    abort,
    flash,
    redirect,
    render_template,
    render_template_string,
    request,
    url_for,
)
from flask import (
    current_app as app,
)
from flask.typing import ResponseReturnValue
from flask_login import current_user, login_required
from flask_mailman import EmailMessage
from markupsafe import Markup
from sqlalchemy.exc import IntegrityError
from wtforms import BooleanField, FormField, SelectField, StringField, SubmitField, TextAreaField
from wtforms.validators import URL, DataRequired, ValidationError

from apps.cfp.date import MAIN_CONTENT_START_DAY, availability_time_ranges, content_timestamp
from main import db, external_url, get_or_404
from models.content import (
    AGE_RANGE_OPTIONS,
    DURATION_OPTIONS,
    PROPOSAL_INFOS,
    LightningTalk,
    Occurrence,
    Proposal,
    ProposalMessage,
    ProposalType,
    ScheduleItem,
    ScheduleItemType,
)
from models.content.schedule import ScheduleItemAvailability
from models.user import User

from ..common import create_current_user, feature_enabled, feature_flag
from ..common.fields import EmailField, TelField
from ..common.forms import DiversityForm, Form
from ..common.mattermost import mattermost_notify
from ..config import config
from . import cfp

LIGHTNING_TALK_LENGTH = 5  # in minutes


class ProposalForm(Form):
    # These first two don't exist on Proposal so should be ignored by populate_obj
    # TODO: move these out into a sibling form
    name = StringField("Name", [DataRequired()])
    email = EmailField("Email", [DataRequired()])

    title = StringField("Title", [DataRequired()])
    description = TextAreaField("Description", [DataRequired()])

    equipment_required = TextAreaField("Equipment required")
    funding_required = TextAreaField("Costs")
    notice_required = SelectField(
        "Required notice",
        default="1 month",
        choices=[
            ("< 1 month", "Less than 1 month"),
            ("> 1 month", "Longer than 1 month"),
            ("> 2 months", "Longer than 2 months"),
        ],
    )
    additional_info = TextAreaField("Additional info")
    needs_help = BooleanField("Needs help")

    def validate_email(form, field):
        if current_user.is_anonymous and User.does_user_exist(field.data):
            field.was_duplicate = True
            cfp_url = url_for("cfp.main")  # FIXME

            msg = Markup(
                render_template_string(
                    """You already have an account.
                Please <a href="{{ url }}" target="_new">click here</a> to log in.""",
                    url=url_for("users.login", next=cfp_url, email=field.data),
                )
            )

            raise ValidationError(msg)


class AttributesForm(Form):
    pass


class TalkAttributesForm(AttributesForm):
    pass


class PerformanceAttributesForm(AttributesForm):
    pass


class WorkshopAttributesForm(AttributesForm):
    participant_count = StringField("Attendees", [DataRequired()])
    age_range = SelectField(
        "Age range",
        default="all",
        choices=[
            (c, f"{t} (this may be considered for a Family Workshop)" if c in {"u5", "u12"} else t)
            for c, t in AGE_RANGE_OPTIONS
        ],
    )
    participant_cost = StringField("Cost per attendee")
    participant_equipment = StringField("Attendee equipment")


class FamilyWorkshopAttributesForm(AttributesForm):
    participant_count = StringField("Attendees", [DataRequired()])
    age_range = StringField("Age range")
    participant_cost = StringField("Cost per attendee")
    participant_equipment = StringField("Attendee equipment")


class InstallationAttributesForm(AttributesForm):
    grant_requested = SelectField(
        "Funding",
        choices=[
            ("0", "No money needed"),
            ("< £100", "Less than £100"),
            ("< £500", "Less than £500"),
            ("> £500", "More than £500"),
        ],
    )
    size = SelectField(
        "Physical size",
        default="medium",
        choices=[
            ("small", "Smaller than a microwave"),
            ("medium", "Smaller than a wheelie bin"),
            ("large", "Smaller than a car"),
            ("huge", "Bigger than a car"),
        ],
    )


ATTRIBUTES_FORM_TYPES: dict[ProposalType, type[AttributesForm]] = {
    "talk": TalkAttributesForm,
    "workshop": WorkshopAttributesForm,
    "familyworkshop": FamilyWorkshopAttributesForm,
    "performance": PerformanceAttributesForm,
    "installation": InstallationAttributesForm,
}


def get_proposal_type_form(proposal_type: ProposalType) -> type[ProposalForm]:
    # A Form only processes incoming data when initialised,
    # so to modify a form you need to create a subclass.
    # We could use mixins or generics here instead.
    # https://wtforms.readthedocs.io/en/3.2.x/specific_problems/#dynamic-form-composition
    class ProposalFormWithAttributes(ProposalForm):
        pass

    ProposalFormWithAttributes.attributes = FormField(ATTRIBUTES_FORM_TYPES[proposal_type])

    if proposal_type in {"talk", "performance"}:
        ProposalFormWithAttributes.duration = SelectField(
            "Duration", default="25-45 mins", choices=DURATION_OPTIONS
        )
    elif proposal_type in {"workshop", "familyworkshop"}:
        ProposalFormWithAttributes.duration = StringField("Duration", [DataRequired()])

    ProposalFormWithAttributes.type_info = PROPOSAL_INFOS[proposal_type]

    return ProposalFormWithAttributes


# FIXME placeholder for new form
class LightningTalkForm(Form):
    title = StringField("Title", [DataRequired()])
    description = TextAreaField("Description", [DataRequired()])

    slide_link = StringField("Link to your slides (PDF only)", [DataRequired(), URL()])

    submit = SubmitField("Submit")


class CreateLightningTalkForm(LightningTalkForm):
    session = SelectField("Choose the session you'd like to present at")

    def set_session_choices(self):
        self.session.choices = []
        for day, occurrence_id in get_days_with_slots():
            self.session.choices.append((occurrence_id, day))


class EditLightningTalkForm(LightningTalkForm):
    # Skip the session stuff because it is too late to deal with dropdowns
    # instead give a cancel option and they can re-submit
    cancel = SubmitField("Cancel submission")


def get_occurrence_time_remaining(occurrence: Occurrence) -> int:
    allocated_time = LIGHTNING_TALK_LENGTH * len(occurrence.lightning_talks)
    total_duration = 0 if not occurrence.scheduled_duration else occurrence.scheduled_duration
    return total_duration - allocated_time


def get_days_with_slots() -> list[tuple[str, int]]:
    schedule_item = (
        db.session.query(ScheduleItem).filter(ScheduleItem.title == "Lightning Talks").one_or_none()
    )
    if not schedule_item:
        return []

    days_with_slots = []
    for occurrence in schedule_item.occurrences:
        if occurrence.cancelled:
            continue

        remaining_time = get_occurrence_time_remaining(occurrence)
        scheduled_time = occurrence.scheduled_time

        if not scheduled_time:
            continue

        if remaining_time > 0:
            day_of_week = scheduled_time.strftime("%A %H:%M")  # e.g. -> "Friday"
            days_with_slots.append((day_of_week, occurrence.id))

    return days_with_slots


@cfp.route("/cfp")
def main() -> ResponseReturnValue:
    if not feature_enabled("CFP"):
        return render_template("cfp/holding-page.html")

    ignore_closed = "closed" in request.args

    if feature_enabled("CFP_CLOSED") and not ignore_closed:
        return render_template("cfp/closed.html")

    lightning_talks_full = len(get_days_with_slots()) == 0

    proposal_infos_open = []
    proposal_infos_closed = []
    for ti in PROPOSAL_INFOS.values():
        human_type_plural = ti.human_type + "s"
        if feature_enabled(f"CFP_{ti.type.upper()}S_CLOSED"):
            proposal_infos_closed.append(human_type_plural)
        else:
            proposal_infos_open.append(human_type_plural)

    return render_template(
        "cfp/main.html",
        ignore_closed=ignore_closed,
        proposal_infos_open=proposal_infos_open,
        proposal_infos_closed=proposal_infos_closed,
        lightning_talks_full=lightning_talks_full,
    )


# TODO: remove this after 2026
@cfp.route("/cfp/youthworkshop", methods=["GET"])
@feature_flag("CFP")
def create_youthworkshop_proposal_redirect() -> ResponseReturnValue:
    return redirect(url_for(".create_proposal", proposal_type="familyworkshop"))


@cfp.route("/cfp/lightning-talk", methods=["GET", "POST"])
@feature_flag("CFP")
def create_lightning_talk() -> ResponseReturnValue:
    if not feature_enabled("LIGHTNING_TALKS"):
        return render_template("cfp/closed.html", proposal_type="lightning-talk")

    if not current_user.is_authenticated:
        return redirect(url_for("users.login", next=request.path))
    form = CreateLightningTalkForm()
    form.set_session_choices()

    if len(get_days_with_slots()) == 0:
        flash("Sorry all lightning talk sessions are now full")
        return redirect(url_for(".main"))

    if form.validate_on_submit():
        occurrence_id = form.session.data
        occurrence = get_or_404(db, Occurrence, occurrence_id)

        if get_occurrence_time_remaining(occurrence) <= 0:
            flash("Sorry that session is now full.")
            return redirect(url_for(".create_lightning_talk"))

        talk = LightningTalk(user_id=current_user.id, occurrence_id=occurrence_id)

        form.populate_obj(talk)

        db.session.add(talk)
        db.session.commit()
        app.logger.info(f"Added new lightning-talk '{talk.title}'")
        flash("Thank you for submitting a lightning talk!")
        return redirect(url_for(".edit_lightning_talk", lightning_talk_id=talk.id))

    return render_template("cfp/create_lightning_talk.html", form=form)


@cfp.route("/cfp/lightning-talk/<int:lightning_talk_id>", methods=["GET", "POST"])
@feature_flag("CFP")
def edit_lightning_talk(lightning_talk_id: int) -> ResponseReturnValue:
    if not feature_enabled("LIGHTNING_TALKS"):
        return render_template("cfp/closed.html", proposal_type="lightning-talk")

    if not current_user.is_authenticated:
        return redirect(url_for("users.login", next=request.path))

    form = EditLightningTalkForm()
    lightning_talk = get_or_404(db, LightningTalk, lightning_talk_id)

    if current_user.id != lightning_talk.user_id:
        return redirect(url_for("users.account"))

    if form.validate_on_submit():
        if form.cancel.data:
            db.session.delete(lightning_talk)
            db.session.commit()
            app.logger.info(f"Deleted lightning-talk '{lightning_talk.title}'")
            flash(f"Cancelled lightning talk, '{lightning_talk.title}'")
            return redirect(url_for(".main"))

        form.populate_obj(lightning_talk)
        db.session.commit()
        app.logger.info(f"Edited lightning-talk '{lightning_talk.title}'")
        flash(f"Updated lightning-talk '{lightning_talk.title}'")
        return redirect(url_for(".proposals", lightning_talk_id=lightning_talk.id))

    form.title.data = lightning_talk.title
    form.description.data = lightning_talk.description
    form.slide_link.data = lightning_talk.slide_link

    return render_template("cfp/edit_lightning_talk.html", form=form, lightning_talk=lightning_talk)


@cfp.route("/cfp/<string:proposal_type>", methods=["GET", "POST"])
@feature_flag("CFP")
def create_proposal(proposal_type: ProposalType = "talk") -> ResponseReturnValue:
    if proposal_type not in get_args(ProposalType):
        abort(404)

    ignore_closed = "closed" in request.args or (
        current_user.is_authenticated and current_user.is_invited_speaker
    )

    if feature_enabled("CFP_CLOSED") and not ignore_closed:
        return render_template("cfp/closed.html", proposal_type=proposal_type)

    Form = get_proposal_type_form(proposal_type)
    form = Form()

    # FIXME: ick
    if feature_enabled(f"CFP_{proposal_type.upper()}S_CLOSED") and not ignore_closed:
        flash(
            Markup(
                render_template_string(
                    """Sorry, we're not accepting new {{ type }} proposals, if you have been told to submit something please <a href="{{ url }}">click here</a>""",
                    type=PROPOSAL_INFOS[proposal_type].human_type,
                    url=url_for(".create_proposal", proposal_type=proposal_type, closed=True),
                )
            )
        )
        return redirect(url_for(".main"))

    # If the user is already logged in set their name & email for the form
    if current_user.is_authenticated:
        form.email.data = current_user.email
        if current_user.name != current_user.email:
            form.name.data = current_user.name

    if request.method == "POST":
        app.logger.info(
            "Checking %s proposal for %s (%s)",
            proposal_type,
            form.name.data,
            form.email.data,
        )

    if form.validate_on_submit():
        assert form.name.data is not None  # Form.name is DataRequired()
        assert form.email.data is not None  # Form.email is DataRequired()

        new_user = False
        if current_user.is_anonymous:
            try:
                create_current_user(form.email.data, form.name.data)
                new_user = True
            except IntegrityError as e:
                app.logger.warning("Adding user raised %r, possible double-click", e)
                flash("An error occurred while creating an account for you. Please try again.")
                return redirect(url_for(".main"))

        elif current_user.name == current_user.email:
            current_user.name = form.name.data

        # Delete to hide from populate_obj
        del form.name
        del form.email

        proposal = Proposal(
            type=proposal_type,
            user=current_user,
        )
        if proposal_type in {"talk", "performance", "workshop", "familyworkshop"}:
            proposal.duration = form.duration.data
        else:
            proposal.duration = None

        form.populate_obj(proposal)

        if current_user.is_invited_speaker:
            proposal.state = "manual-review"
            proposal.private_notes = current_user.cfp_invite_reason

        db.session.add(proposal)
        db.session.commit()

        # Send confirmation message
        email = EmailMessage(
            "Electromagnetic Field CFP Submission",
            from_email=config.from_email("CONTENT_EMAIL"),
            to=[current_user.email],
        )

        email.body = render_template("emails/cfp-submission.txt", proposal=proposal, new_user=new_user)
        email.send()

        if channel := app.config.get("MATTERMOST_CFP_CHANNEL"):
            msg = f"New {proposal.human_type} submission by {proposal.user.name}:\n"
            msg += f"[{proposal.title}]({external_url('cfp_review.proposal', proposal_id=proposal.id)})"
            if form.needs_help.data:
                msg += "\nCalls for aid (they've clicked 'needs help') 🚨"
            mattermost_notify(channel, msg)

        return redirect(url_for(".complete"))

    return render_template(
        "cfp/new.html",
        proposal_type=proposal_type,
        form=form,
        has_errors=bool(form.errors),
        ignore_closed=ignore_closed,
    )


@cfp.route("/cfp/complete", methods=["GET", "POST"])
@feature_flag("CFP")
@login_required
def complete() -> ResponseReturnValue:
    form = DiversityForm(user=current_user)
    if form.validate_on_submit():
        form.update_user(current_user)
        db.session.commit()
        return redirect(url_for(".proposals"))

    form.set_from_user(current_user)

    return render_template("cfp/complete.html", form=form)


@cfp.route("/cfp/proposals")
@feature_flag("CFP")
@login_required
def proposals() -> ResponseReturnValue:
    proposals = current_user.proposals
    lightning_talks = current_user.lightning_talks
    if not proposals and not lightning_talks:
        return redirect(url_for(".main"))

    return render_template("cfp/proposals.html", proposals=proposals, lightning_talks=lightning_talks)


@cfp.route("/cfp/proposals/<int:proposal_id>/edit", methods=["GET", "POST"])
@feature_flag("CFP")
@login_required
def edit_proposal(proposal_id: int) -> ResponseReturnValue:
    proposal: Proposal = get_or_404(db, Proposal, proposal_id)

    if proposal.user != current_user:
        abort(404)

    Form = get_proposal_type_form(proposal.type)
    form = Form(obj=proposal)
    del form.name
    del form.email

    if form.validate_on_submit():
        if not proposal.is_editable:
            flash("This submission can no longer be edited.")
            return redirect(url_for(".proposals"))

        app.logger.info("Proposal %s edited", proposal.id)

        if proposal.type in {"talk", "performance", "workshop", "familyworkshop"}:
            proposal.duration = form.duration.data
        elif proposal.type in {"installation"}:
            # Installations don't currently have a duration
            proposal.duration = None

        form.populate_obj(proposal)

        db.session.commit()
        flash("Your proposal has been updated")

        return redirect(url_for(".edit_proposal", proposal_id=proposal_id))

    return render_template("cfp/edit.html", proposal=proposal, form=form)


class WithdrawalForm(Form):
    message = TextAreaField("If you're comfortable, please tell us why you're withdrawing", default="")
    confirm_withdrawal = SubmitField("Confirm proposal withdrawal")


@cfp.route("/cfp/proposals/<int:proposal_id>/withdraw", methods=["GET", "POST"])
@feature_flag("CFP")
@login_required
def withdraw_proposal(proposal_id: int) -> ResponseReturnValue:
    proposal = get_or_404(db, Proposal, proposal_id)
    if proposal.user != current_user:
        abort(404)

    form = WithdrawalForm()
    if form.validate_on_submit() and form.confirm_withdrawal.data:
        app.logger.info("Proposal %s is being withdrawn.", proposal_id)
        proposal.withdraw()

        if form.message.data:
            msg = ProposalMessage()
            msg.is_to_admin = True
            msg.from_user_id = current_user.id
            msg.proposal_id = proposal_id
            msg.message = form.message.data

            db.session.add(msg)

        db.session.commit()
        flash(f"We've withdrawn your {proposal.human_type}, {proposal.title}.")

        return redirect(url_for("cfp.proposals"))

    return render_template("cfp/withdraw.html", form=form, proposal=proposal)


class FinaliseForm(Form):
    names = StringField("Names for schedule", [DataRequired()])
    pronouns = StringField("Pronouns")
    title = StringField("Title", [DataRequired()])
    description = TextAreaField("Description", [DataRequired()])
    short_description = StringField("Short description")

    video_privacy = SelectField(
        "Recording",
        default="public",
        choices=[
            ("public", "I am happy for this to be streamed and recorded"),
            ("review", "Do not stream, and do not publish until reviewed"),
            ("none", "Do not stream or record"),
        ],
    )

    contact_telephone = TelField("Telephone")

    # Fields from Proposal that we re-expose for convenience
    proposal_equipment_required = TextAreaField("Equipment Required")

    def load_choices(self, schedule_item: ScheduleItem) -> None:
        if schedule_item.video_privacy != "review":
            # Don't allow users to choose review themselves
            assert isinstance(self.video_privacy.choices, list)
            self.video_privacy.choices = [(c, _) for c, _ in self.video_privacy.choices if c != "review"]


class FinaliseAttributesForm(Form):
    pass


class FinaliseTalkAttributesForm(FinaliseAttributesForm):
    content_note = TextAreaField("Content note")
    needs_laptop = BooleanField("I will need to borrow a laptop for slides")
    family_friendly = BooleanField("Family friendly")


class FinalisePerformanceAttributesForm(FinaliseAttributesForm):
    pass


class FinaliseWorkshopAttributesForm(FinaliseAttributesForm):
    age_range = StringField("Age range")
    participant_cost = StringField("Cost per attendee")
    participant_equipment = StringField("Attendee equipment")
    content_note = TextAreaField("Content note")
    family_friendly = BooleanField("Family friendly")
    proposal_participant_count = StringField("Attendees")


class FinaliseFamilyWorkshopAttributesForm(FinaliseAttributesForm):
    age_range = StringField("Age range")
    participant_cost = StringField("Cost per attendee")
    participant_equipment = StringField("Attendee equipment")
    content_note = TextAreaField("Content note")
    proposal_participant_count = StringField("Attendees")


FINALISE_ATTRIBUTES_FORM_TYPES: dict[ScheduleItemType, type[FinaliseAttributesForm]] = {
    "talk": FinaliseTalkAttributesForm,
    "performance": FinalisePerformanceAttributesForm,
    "workshop": FinaliseWorkshopAttributesForm,
    "familyworkshop": FinaliseFamilyWorkshopAttributesForm,
}


def get_finalise_form(schedule_item_type: ScheduleItemType) -> type[FinaliseForm]:
    class FinaliseFormWithAttributes(FinaliseForm):
        pass

    if schedule_item_type in FINALISE_ATTRIBUTES_FORM_TYPES:
        FinaliseFormWithAttributes.attributes = FormField(FINALISE_ATTRIBUTES_FORM_TYPES[schedule_item_type])

    return FinaliseFormWithAttributes


class TimeRangesHandler:
    """Manages the form fields for CfP submitters to submit and modify time ranges, outside of WTForms."""

    # This is more straightforward and self-contained than any approach I managed to achieve with
    # WTForms but it still seems like a ridiculously large amount of code to handle 9
    # checkboxes.

    def __init__(self, schedule_item: ScheduleItem):
        self.schedule_item = schedule_item
        self._ranges = availability_time_ranges(schedule_item.type)
        self._days = list(islice(config.event_days, MAIN_CONTENT_START_DAY, None))
        self._result_lookup = {}

        result = {}
        for day in self._days:
            fields = []
            for start, end in self._ranges:
                start_dt = content_timestamp(day, start)
                end_dt = content_timestamp(day, end)
                field_name = start_dt.strftime("%Y-%m-%d-%H-%M")
                fields.append(field_name)
                self._result_lookup[field_name] = (start_dt, end_dt)
            result[day.strftime("%A %d %B")] = fields
        self.fields = result

        self.enabled = {}
        if len(schedule_item.availability) == 0:
            for name in self._result_lookup:
                self.enabled[name] = True
        else:
            for range in schedule_item.availability:
                for name, (start_time, end_time) in self._result_lookup.items():
                    if range.start == start_time and range.end == end_time:
                        self.enabled[name] = True

    @property
    def range_names(self) -> list[str]:
        return [f"{start.strftime('%H:%M')}-{end.strftime('%H:%M')}" for start, end in self._ranges]

    @property
    def days(self) -> list[str]:
        return [day.strftime("%A %d %B") for day in self._days]

    def get_results(self):
        ranges = []
        for field, (start_dt, end_dt) in self._result_lookup.items():
            if request.form.get(field):
                ranges.append((start_dt, end_dt))
        return ranges

    def validate(self):
        if len(self.get_results()) == 0:
            flash("Please provide at least one time range when you are available")
            return False
        return True

    def save(self):
        existing = set((a.start, a.end) for a in self.schedule_item.availability)
        new = set(self.get_results())

        changed = False

        for start, end in new - existing:
            self.schedule_item.availability.append(ScheduleItemAvailability(start=start, end=end))
            changed = True

        for start, end in existing - new:
            obj = (
                db.session.query(ScheduleItemAvailability)
                .filter(
                    ScheduleItemAvailability.schedule_item == self.schedule_item,
                    ScheduleItemAvailability.start == start,
                    ScheduleItemAvailability.end == end,
                )
                .one()
            )
            db.session.delete(obj)
            changed = True

        return changed


@cfp.route("/cfp/proposals/<int:proposal_id>/finalise", methods=["GET", "POST"])
@feature_flag("CFP")
@login_required
def finalise_proposal(proposal_id: int) -> ResponseReturnValue:
    """
    Finalise the details for the schedule, including names, pronouns, and availability.
    This can be done any time after accepting the talk, but is also done in bulk when
    the scheduled_duration is set on the schedule_item, and after the talk is scheduled.
    (Obviously setting availability is a bit late after it's been scheduled.)
    """
    proposal = get_or_404(db, Proposal, proposal_id)
    if proposal.user != current_user:
        abort(404)

    if not feature_enabled("CFP_FINALISE"):
        return redirect(url_for(".edit_proposal", proposal_id=proposal_id))

    if proposal.schedule_item is None:
        app.logger.warning("Attempt to finalise proposal without schedule item")
        abort(404)

    schedule_item = proposal.schedule_item

    if proposal.state not in {"accepted", "finalised"}:
        return redirect(url_for(".edit_proposal", proposal_id=proposal_id))

    # The ScheduleItem type can differ from the Proposal type!
    Form = get_finalise_form(proposal.schedule_item.type)
    form = Form(obj=schedule_item)
    form.load_choices(schedule_item)

    time_ranges = TimeRangesHandler(schedule_item)

    if form.validate_on_submit() and time_ranges.validate():
        # Should be impossible outside of races
        assert not (form.video_privacy.data == "review" and schedule_item.video_privacy != "review")

        proposal.equipment_required = form.proposal_equipment_required.data
        del form.proposal_equipment_required

        # For convenience, we ask them to update their participant_count,
        # but this isn't exposed on the ScheduleItem
        if (
            hasattr(form, "attributes")
            and hasattr(form.attributes, "proposal_participant_count")
            and hasattr(proposal.attributes, "participant_count")
        ):
            proposal.attributes.participant_count = form.attributes.proposal_participant_count.data
            # Now delete this, or populate_obj will try to add it
            del form.attributes.form.proposal_participant_count

        availability_changed = time_ranges.save()
        # Proposers can change their availability after finalisation and are notified of this
        # this in the scheduling emails. We need to know this in order to re-run scheduling.
        has_been_through_scheduler = any(
            o.potential_time or o.scheduled_time for o in schedule_item.occurrences
        )
        if availability_changed and has_been_through_scheduler:
            # TODO: surface this in the admin pages somewhere?
            if channel := app.config.get("MATTERMOST_CFP_CHANNEL"):
                mattermost_notify(
                    channel,
                    f"🗓️🚨 **Submitter changed their availability for scheduled {proposal.schedule_item.human_type}**: "
                    f"[{proposal.title}]({external_url('cfp_review.message_proposer', proposal_id=proposal_id)})",
                )

        form.populate_obj(schedule_item)

        if schedule_item.state == "unpublished":
            schedule_item.state = "published"

        proposal.state = "finalised"

        db.session.commit()
        app.logger.info("Finalised proposal %s", proposal_id)
        flash("Thank you for finalising your details!")

        return redirect(url_for(".edit_proposal", proposal_id=proposal_id))

    if request.method != "POST":
        # These proxy to the proposal, so it doesn't matter if schedule_item exists
        form.proposal_equipment_required.data = proposal.equipment_required
        if (
            hasattr(form, "attributes")
            and hasattr(form.attributes, "proposal_participant_count")
            and hasattr(proposal.attributes, "participant_count")
        ):
            form.attributes.proposal_participant_count.data = proposal.attributes.participant_count

    return render_template(
        "cfp/finalise.html",
        form=form,
        proposal=proposal,
        time_ranges=time_ranges,
    )


class MessagesForm(Form):
    message = TextAreaField("Message")
    send = SubmitField("Send Message")
    mark_read = SubmitField("Mark all messages as read")

    def validate_message(form, field):
        if form.mark_read.data and field.data:
            raise ValidationError("Cannot mark as read with a draft reply")

        if form.send.data and not field.data:
            raise ValidationError("Message is required")


@cfp.route("/cfp/proposals/<int:proposal_id>/messages", methods=["GET", "POST"])
@feature_flag("CFP")
@login_required
def proposal_messages(proposal_id: int) -> ResponseReturnValue:
    proposal = get_or_404(db, Proposal, proposal_id)
    if proposal.user_id != current_user.id:
        abort(404)

    form = MessagesForm()

    if form.validate_on_submit():
        # The user is replying, mark any outstanding messages as read
        count = proposal.mark_messages_read(current_user)
        db.session.commit()
        app.logger.info(f"Marked {count} messages from admin on proposal {proposal.id} as read")

        if form.send.data:
            assert form.message.data
            msg = ProposalMessage()
            msg.is_to_admin = True
            msg.from_user_id = current_user.id
            msg.proposal_id = proposal_id
            msg.message = form.message.data

            db.session.add(msg)
            db.session.commit()
            if channel := app.config.get("MATTERMOST_CFP_CHANNEL"):
                mattermost_notify(
                    channel,
                    f"✉️ Message for {proposal.human_type} proposal: "
                    f"[{proposal.title}]({external_url('cfp_review.message_proposer', proposal_id=proposal_id)})",
                )

        return redirect(url_for(".proposal_messages", proposal_id=proposal_id))

    messages = db.session.query(ProposalMessage).filter_by(proposal_id=proposal_id).order_by("created").all()

    return render_template("cfp/proposal-messages.html", proposal=proposal, messages=messages, form=form)


@cfp.route("/cfp/messages")
@feature_flag("CFP")
@login_required
def messages() -> ResponseReturnValue:
    proposal_with_message = (
        db.session.query(Proposal)
        .join(ProposalMessage)
        .filter(Proposal.id == ProposalMessage.proposal_id, Proposal.user_id == current_user.id)
        .order_by(ProposalMessage.has_been_read, ProposalMessage.created.desc())
        .all()
    )

    proposal_with_message.sort(key=lambda x: (x.get_unread_count(current_user) > 0, x.created), reverse=True)

    return render_template("cfp/messages.html", proposal_with_message=proposal_with_message)


@cfp.route("/cfp/guidance")
def guidance() -> ResponseReturnValue:
    return render_template("cfp/guidance.html")


@cfp.route("/cfp/proposal-advice")
def proposal_advice() -> ResponseReturnValue:
    return render_template("cfp/proposal_advice.html")


@cfp.route("/cfp/installation-support")
def installation_support() -> ResponseReturnValue:
    return render_template("cfp/installation_support.html")
