import collections
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
from flask_login import current_user
from flask_mailman import EmailMessage
from markupsafe import Markup
from sqlalchemy.exc import IntegrityError
from wtforms import BooleanField, FormField, SelectField, StringField, SubmitField, TextAreaField
from wtforms.validators import URL, DataRequired, ValidationError

from main import db, external_url, get_or_404
from models.cfp import (
    AGE_RANGE_OPTIONS,
    DURATION_OPTIONS,
    PROPOSAL_INFOS,
    PROPOSAL_TIMESLOTS,
    Proposal,
    ProposalMessage,
    ProposalType,
    ProposalWorkshopAttributes,
    ProposalYouthWorkshopAttributes,
    ScheduleItem,
)
from models.user import User

from ..common import create_current_user, feature_enabled, feature_flag
from ..common.email import from_email
from ..common.fields import EmailField, TelField
from ..common.forms import DiversityForm, Form
from ..common.mattermost import mattermost_notify
from . import cfp


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
            (c, f"{t} (this may be considered for a Youth Workshop)" if c in {"u5", "u12"} else t)
            for c, t in AGE_RANGE_OPTIONS
        ],
    )
    participant_cost = StringField("Cost per attendee")
    participant_equipment = StringField("Attendee equipment")


class YouthWorkshopAttributesForm(AttributesForm):
    participant_count = StringField("Attendees", [DataRequired()])
    age_range = StringField("Age range")
    participant_cost = StringField("Cost per attendee")
    participant_equipment = StringField("Attendee equipment")
    valid_dbs = BooleanField("I have a valid DBS check")


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
    "youthworkshop": YouthWorkshopAttributesForm,
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
    elif proposal_type in {"workshop", "youthworkshop"}:
        ProposalFormWithAttributes.duration = StringField("Duration", [DataRequired()])

    ProposalFormWithAttributes.type_info = PROPOSAL_INFOS[proposal_type]

    return ProposalFormWithAttributes


# FIXME placeholder for new form
class LightningTalkForm(Form):
    name = StringField("Name", [DataRequired()])
    email = EmailField("Email", [DataRequired()])
    title = StringField("Title", [DataRequired()])
    description = TextAreaField("Description", [DataRequired()])

    slide_link = StringField("Link to your slides (PDF only)", [DataRequired(), URL()])
    session = SelectField("Choose the session you'd like to present at")

    def set_session_choices(self, remaining_lightning_slots):
        self.session.choices = []
        # for day_id, day_count in remaining_lightning_slots.items():
        raise NotImplementedError

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


# FIXME: orphan lightning talk implementation, awaiting the slot refactor
def get_days_with_slots():
    return {}


@cfp.route("/cfp")
def main():
    if not feature_enabled("CFP"):
        return render_template("cfp/holding-page.html")

    ignore_closed = "closed" in request.args

    if feature_enabled("CFP_CLOSED") and not ignore_closed:
        return render_template("cfp/closed.html")

    lightning_talks_closed = all([i <= 0 for i in get_days_with_slots().values()])

    return render_template(
        "cfp/main.html",
        ignore_closed=ignore_closed,
        lightning_talks_closed=lightning_talks_closed,
    )


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
        if proposal_type in {"talk", "performance", "workshop", "youthworkshop"}:
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
            from_email=from_email("CONTENT_EMAIL"),
            to=[current_user.email],
        )

        email.body = render_template("emails/cfp-submission.txt", proposal=proposal, new_user=new_user)
        email.send()

        if channel := app.config.get("MATTERMOST_CFP_CHANNEL"):
            msg = f"New {proposal.human_type} submission by {proposal.user.name}:\n"
            msg += (
                f"[{proposal.title}]({external_url('cfp_review.update_proposal', proposal_id=proposal.id)})"
            )
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
def complete():
    if current_user.is_anonymous:
        return redirect(url_for(".main"))

    form = DiversityForm(user=current_user)
    if form.validate_on_submit():
        form.update_user(current_user)
        db.session.commit()
        return redirect(url_for(".proposals"))

    form.set_from_user(current_user)

    return render_template("cfp/complete.html", form=form)


@cfp.route("/cfp/proposals")
@feature_flag("CFP")
def proposals():
    if current_user.is_anonymous:
        return redirect(url_for(".main"))

    proposals = current_user.proposals
    if not proposals:
        return redirect(url_for(".main"))

    return render_template("cfp/proposals.html", proposals=proposals)


@cfp.route("/cfp/proposals/<int:proposal_id>/edit", methods=["GET", "POST"])
@feature_flag("CFP")
def edit_proposal(proposal_id: int) -> ResponseReturnValue:
    if current_user.is_anonymous:
        return redirect(url_for("users.login", next=url_for(".edit_proposal", proposal_id=proposal_id)))

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

        if proposal.type in {"talk", "performance", "workshop", "youthworkshop"}:
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
    message = TextAreaField("If you're comfortable, please tell us why you're withdrawing")
    confirm_withdrawal = SubmitField("Confirm proposal withdrawal")


@cfp.route("/cfp/proposals/<int:proposal_id>/withdraw", methods=["GET", "POST"])
@feature_flag("CFP")
def withdraw_proposal(proposal_id):
    if current_user.is_anonymous:
        return redirect(url_for("users.login", next=url_for(".edit_proposal", proposal_id=proposal_id)))

    proposal = get_or_404(db, Proposal, proposal_id)
    if proposal.user != current_user:
        abort(404)

    form = WithdrawalForm()
    if form.validate_on_submit():
        if form.confirm_withdrawal.data:
            app.logger.info("Proposal %s is being withdrawn.", proposal_id)
            proposal.state = "withdrawn"

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
    state = SelectField(
        "State",
        default="published",
        choices=[
            ("published", "Published"),
            ("unpublished", "Unpublished"),
            ("hidden", "Hidden"),
        ],
    )

    names = StringField("Names for schedule", [DataRequired()])
    pronouns = StringField("Pronouns")
    title = StringField("Title", [DataRequired()])
    description = TextAreaField("Description", [DataRequired()])
    short_description = StringField("Short description")

    default_video_privacy = SelectField(
        "Recording",
        default="public",
        choices=[
            ("public", "I am happy for this to be streamed and recorded"),
            ("review", "Do not stream, and do not publish until reviewed"),
            ("none", "Do not stream or record"),
        ],
    )

    arrival_period = SelectField(
        "Estimated arrival time",
        default="fri am",
        choices=[
            ("thu pm", "Thursday pm (Only select this if you are arriving early)"),
            ("fri am", "Friday am"),
            ("fri pm", "Friday pm"),
            ("sat am", "Saturday am"),
            ("sat pm", "Saturday pm"),
            ("sun am", "Sunday am"),
            ("sun pm", "Sunday pm"),
        ],
    )
    departure_period = SelectField(
        "Estimated departure time",
        default="mon am",
        choices=[
            ("fri pm", "Friday pm"),
            ("sat am", "Saturday am"),
            ("sat pm", "Saturday pm"),
            ("sun am", "Sunday am"),
            ("sun pm", "Sunday pm"),
            ("mon am", "Monday am"),
        ],
    )
    _available_slots: list[str]

    contact_telephone = TelField("Telephone")
    contact_eventphone = TelField("On-site extension", min_length=3, max_length=5)

    # Fields from Proposal that we re-expose for convenience
    proposal_equipment_required = TextAreaField("Equipment Required")
    proposal_funding_required = TextAreaField("Funding Required")
    # No notice_required for finalised proposals
    proposal_additional_info = TextAreaField("Additional Information")

    def load_choices(self, schedule_item: ScheduleItem) -> None:
        if schedule_item.default_video_privacy != "review":
            # Don't allow users to choose review themselves
            assert isinstance(self.default_video_privacy.choices, list)
            self.default_video_privacy.choices = [
                (c, _) for c, _ in self.default_video_privacy.choices if c != "review"
            ]

        # Don't allow users to hide or unhide. They'll either be shown
        # publish/unpublish or just hidden with no other options.
        # TODO: should we actually just hide the field when hidden is set?
        if schedule_item.state != "hidden":
            assert isinstance(self.state.choices, list)
            self.state.choices = [(c, _) for c, _ in self.state.choices if c != "hidden"]
        elif schedule_item.state == "hidden":
            assert isinstance(self.state.choices, list)
            self.state.choices = [(c, _) for c, _ in self.state.choices if c == "hidden"]

    def get_availability_json(self):
        res = []
        for field_name in self._available_slots:
            field = getattr(self, field_name)

            if not field.data:
                continue
            res.append(field_name)
        return ", ".join(res)

    def set_from_availability_json(self, available_times):
        for field_name in self._available_slots:
            field = getattr(self, field_name)

            if field_name in available_times:
                field.data = True
            else:
                field.data = False

    def validate_departure_period(form, field):
        arr_day, arr_time = form.arrival_period.data.split()
        dep_day, dep_time = form.departure_period.data.split()

        arr_val = {"thu": 0, "fri": 1, "sat": 2, "sun": 3}[arr_day]
        dep_val = {"thu": 0, "fri": 1, "sat": 2, "sun": 3, "mon": 4}[dep_day]

        # Arrival day is before departure day; we're done here.
        if arr_val < dep_val:
            return

        # Arrival day is after departure
        if arr_val > dep_val:
            raise ValidationError("Departure must be after arrival")

        # Arrival day is same as departure day (might be 1 day ticket)
        # so only error in case of time-travel
        if dep_time == "am" and arr_time == "pm":
            raise ValidationError("Departure must be after arrival")


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


class FinaliseYouthWorkshopAttributesForm(FinaliseAttributesForm):
    age_range = StringField("Age range")
    participant_cost = StringField("Cost per attendee")
    participant_equipment = StringField("Attendee equipment")
    content_note = TextAreaField("Content note")
    proposal_participant_count = StringField("Attendees")
    proposal_valid_dbs = BooleanField("I have a valid DBS check")


# This feels like something that should be on the proposal, not just finalisation
class FinaliseInstallationAttributesForm(FinaliseAttributesForm):
    size = StringField("Size")


FINALISE_ATTRIBUTES_FORM_TYPES: dict[ProposalType, type[FinaliseAttributesForm]] = {
    "talk": FinaliseTalkAttributesForm,
    "performance": FinalisePerformanceAttributesForm,
    "workshop": FinaliseWorkshopAttributesForm,
    "youthworkshop": FinaliseYouthWorkshopAttributesForm,
    "installation": FinaliseInstallationAttributesForm,
}


def get_finalise_form(proposal_type: ProposalType) -> type[FinaliseForm]:
    class FinaliseFormWithAttributes(FinaliseForm):
        pass

    FinaliseFormWithAttributes.attributes = FormField(FINALISE_ATTRIBUTES_FORM_TYPES[proposal_type])

    if proposal_type in {"talk", "performance", "workshop", "youthworkshop"}:
        FinaliseFormWithAttributes._available_slots = PROPOSAL_TIMESLOTS[proposal_type]
        for timeslot in FinaliseFormWithAttributes._available_slots:
            setattr(FinaliseFormWithAttributes, timeslot, BooleanField(default=True))

    return FinaliseFormWithAttributes


@cfp.route("/cfp/proposals/<int:proposal_id>/finalise", methods=["GET", "POST"])
@feature_flag("CFP")
def finalise_proposal(proposal_id: int) -> ResponseReturnValue:
    """
    Finalise the details for the schedule, including names, pronouns, and availability.
    This can be done any time after accepting the talk, but is also done in bulk when
    the scheduled_duration is set on the schedule_item, and after the talk is scheduled.
    (Obviously setting availability is a bit late after it's been scheduled.)
    """
    if current_user.is_anonymous:
        return redirect(
            url_for(
                "users.login",
                next=url_for(".finalise_proposal", proposal_id=proposal_id),
            )
        )

    proposal = get_or_404(db, Proposal, proposal_id)
    if proposal.user != current_user:
        abort(404)

    if proposal.schedule_item is None:
        app.logger.warning("Attempt to finalise proposal without schedule item")
        abort(404)

    schedule_item: ScheduleItem = proposal.schedule_item

    if proposal.state not in {"accepted", "finalised"}:
        return redirect(url_for(".edit_proposal", proposal_id=proposal_id))

    Form = get_finalise_form(proposal.type)
    form = Form(obj=schedule_item)
    form.load_choices(schedule_item)

    if form.validate_on_submit():
        # Should be impossible outside of races
        assert not (
            form.default_video_privacy.data == "review" and schedule_item.default_video_privacy != "review"
        )
        assert not (form.state.data == "hidden" and schedule_item.state != "hidden")
        assert not (form.state.data != "hidden" and schedule_item.state == "hidden")

        # For convenience, we ask them to update their participant_count
        # and valid_dbs, but these aren't exposed on the ScheduleItem
        if isinstance(proposal.attributes, ProposalWorkshopAttributes):
            proposal.attributes.participant_count = form.attributes.proposal_participant_count.data
            # Now delete this, or populate_obj will try to add it
            del form.attributes.form.proposal_participant_count

        elif isinstance(proposal.attributes, ProposalYouthWorkshopAttributes):
            proposal.attributes.participant_count = form.attributes.proposal_participant_count.data
            proposal.attributes.valid_dbs = form.attributes.proposal_valid_dbs.data
            # Now delete these, or populate_obj will try to add them
            del form.attributes.form.proposal_participant_count
            del form.attributes.form.valid_dbs

        # Proposers can change their availability after finalisation and are notified of this
        # this in the scheduling emails. We need to know this in order to re-run scheduling.
        new_availability = form.get_availability_json()
        has_been_through_scheduler = any(
            o.potential_time or o.scheduled_time for o in schedule_item.occurrences
        )
        if new_availability != schedule_item.available_times and has_been_through_scheduler:
            # TODO: surface this in the admin pages somewhere?
            if channel := app.config.get("MATTERMOST_CFP_CHANNEL"):
                mattermost_notify(
                    channel,
                    f"🗓️🚨 **ScheduleItem availability changed** for {proposal.human_type}: "
                    f"[{proposal.title}]({external_url('cfp_review.message_proposer', proposal_id=proposal_id)})",
                )
        schedule_item.available_times = new_availability

        form.populate_obj(schedule_item)

        db.session.commit()
        app.logger.info("Finalised proposal %s", proposal_id)
        flash("Thank you for finalising your details!")

        return redirect(url_for(".edit_proposal", proposal_id=proposal_id))

    if request.method == "POST":
        # Don't overwrite user submitted data
        pass

    else:
        # Default to publishing the schedule item
        if schedule_item.state == "unpublished":
            form.proposal.data = "published"

        # These proxy to the proposal, so it doesn't matter if schedule_item exists
        form.proposal_equipment_required.data = proposal.equipment_required
        form.proposal_funding_required.data = proposal.funding_required
        form.proposal_additional_info.data = proposal.additional_info

        if isinstance(proposal.attributes, ProposalWorkshopAttributes):
            form.attributes.proposal_participant_count.data = proposal.attributes.participant_count

        elif isinstance(proposal.attributes, ProposalYouthWorkshopAttributes):
            form.attributes.proposal_participant_count.data = proposal.attributes.participant_count
            form.attributes.proposal_valid_dbs.data = proposal.attributes.valid_dbs

        # Most of the form will have been populated already by Form(schedule_item)
        if schedule_item.available_times:
            form.set_from_availability_json(schedule_item.available_times)

    # This just sorts out the headings / columns for the form
    headings = {}
    day_form_slots: dict[str, dict[str, Markup]] = collections.defaultdict(dict)
    for slot in Form._available_slots:
        day_str, start_str, end_str = slot.split("_")
        slot_hour_str = f"{start_str}_{end_str}"
        day_form_slots[day_str][slot_hour_str] = getattr(form, slot)(class_="form-control")
        headings[int(start_str)] = (int(start_str), int(end_str))

    slot_times = []
    slot_titles = []
    for start in sorted(headings.keys()):
        start, end = headings[start]
        slot_times.append(f"{start}_{end}")

        start_ampm = end_ampm = "am"
        if start > 12:
            start_ampm = "pm"
            start -= 12
        if end > 12:
            end_ampm = "pm"
            end -= 12
        slot_titles.append(f"{start}{start_ampm} - {end}{end_ampm}")

    return render_template(
        "cfp/finalise.html",
        form=form,
        proposal=proposal,
        slot_times=slot_times,
        slot_titles=slot_titles,
        day_form_slots=day_form_slots,
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
def proposal_messages(proposal_id):
    if current_user.is_anonymous:
        return redirect(
            url_for(
                "users.login",
                next=url_for(".proposal_messages", proposal_id=proposal_id),
            )
        )
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

    messages = ProposalMessage.query.filter_by(proposal_id=proposal_id).order_by("created").all()

    return render_template("cfp/proposal-messages.html", proposal=proposal, messages=messages, form=form)


@cfp.route("/cfp/messages")
@feature_flag("CFP")
def messages():
    if current_user.is_anonymous:
        return redirect(url_for(".main"))

    proposal_with_message = (
        Proposal.query.join(ProposalMessage)
        .filter(Proposal.id == ProposalMessage.proposal_id, Proposal.user_id == current_user.id)
        .order_by(ProposalMessage.has_been_read, ProposalMessage.created.desc())
        .all()
    )

    proposal_with_message.sort(key=lambda x: (x.get_unread_count(current_user) > 0, x.created), reverse=True)

    return render_template("cfp/messages.html", proposal_with_message=proposal_with_message)


@cfp.route("/cfp/guidance")
def guidance():
    return render_template("cfp/guidance.html")


@cfp.route("/cfp/installation-support")
def installation_support():
    return render_template("cfp/installation_support.html")
