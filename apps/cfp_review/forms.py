from itertools import chain
from typing import get_args

from dateutil.parser import parse as parse_date
from sqlalchemy import select
from wtforms import (
    BooleanField,
    DateTimeField,
    FieldList,
    FloatField,
    FormField,
    IntegerField,
    SelectField,
    SelectMultipleField,
    StringField,
    SubmitField,
    TextAreaField,
)
from wtforms.validators import DataRequired, NumberRange, Optional, ValidationError

from main import db
from models.content import (
    PROPOSAL_INFOS,
    PROPOSAL_STATE_TRANSITIONS,
    ProposalType,
    ScheduleItemState,
    ScheduleItemType,
    Venue,
)
from models.content.cfp import Proposal, ProposalState
from models.content.schedule import SLOT_DURATION
from models.user import User

from ..admin.users import NewUserForm
from ..common.fields import EmailField, HiddenIntegerField
from ..common.forms import Form, coerce_optional


# See also ProposalForm, etc in apps/cfp/views.py, but reviewers should be able to edit anything
class UpdateProposalForm(Form):
    state = SelectField(
        "State",
        choices={
            # see Proposal.is_editable
            "Editable": [("new", "New"), ("edit", "Edit"), ("manual-review", "Manual review")],
            "Pre-review": [("checked", "Checked")],
            "Review": [
                ("anonymised", "Anonymised"),
                ("anon-blocked", "Can't anonymise"),
            ],
            "Final": [
                ("accepted", "Accepted"),
                ("finalised", "Finalised"),
                ("rejected", "Rejected"),
                ("withdrawn", "Withdrawn"),
                ("conduct-blocked", "Blocked for conduct issues"),
            ],
        },
    )

    title = StringField("Title", [DataRequired()])
    description = TextAreaField("Description", [DataRequired()])
    duration = StringField("Duration")

    needs_help = BooleanField("Needs Help")
    equipment_required = TextAreaField("Equipment Required")
    funding_required = TextAreaField("Funding Required")
    notice_required = SelectField(
        "Required notice",
        choices=[
            ("< 1 month", "Less than 1 month"),
            ("> 1 month", "Longer than 1 month"),
            ("> 2 months", "Longer than 2 months"),
        ],
    )
    additional_info = TextAreaField("Additional Info")

    needs_money = BooleanField("Needs Money")
    one_day = BooleanField("One day only")
    # rejected_email_sent is internal

    # private_notes is managed by PrivateNotesForm

    user_will_have_ticket = BooleanField("Will have a ticket")

    update = SubmitField("Save changes")

    def validate_allowed_times(self, field):
        try:
            for p in field.data.split("\n"):
                if p:
                    start, end = p.split(" > ")
                    parse_date(start)
                    parse_date(end)
        except ValueError as e:
            raise ValidationError("Unparsable Allowed Times. Fmt: datetime > datetime per line") from e


# Mapping of which form fields are allowed for a specific target state
STATE_FIELDS: dict[ProposalState, set[str]] = {
    "accepted": {"accept"},
    "rejected": {"reject", "reject_with_message"},
    "checked": {"checked"},
    "conduct-blocked": {"conduct_issues"},
    "manual-review": {"manual_review"},
    "edit": {"edit"},
    "withdrawn": {"withdraw"},
}


class ProposalStateForm(Form):
    """Form displayed to admins which only shows the appropriate actions for a proposal in this state."""

    checked = SubmitField("Mark as checked", render_kw={"class": "btn btn-primary"})
    conduct_issues = SubmitField("Has conduct issues", render_kw={"class": "btn btn-primary"})

    manual_review = SubmitField("Send to manual review", render_kw={"class": "btn btn-primary"})
    withdraw = SubmitField("Mark as withdrawn", render_kw={"class": "btn btn-primary"})

    edit = SubmitField("Make editable by user", render_kw={"class": "btn btn-primary"})

    accept = SubmitField("Accept and send email", render_kw={"class": "btn btn-primary"})
    reject = SubmitField("Reject without telling user", render_kw={"class": "btn btn-danger"})
    reject_with_message = SubmitField("Reject and send email", render_kw={"class": "btn btn-danger"})

    _allowed_fields: set[str]

    def __init__(self, proposal: Proposal) -> None:
        super().__init__()
        allowed_states = PROPOSAL_STATE_TRANSITIONS.get(proposal.state, set())

        self._allowed_fields = set(
            chain.from_iterable(STATE_FIELDS.get(state, {}) for state in allowed_states)
        )
        for field in list(self):
            if field.name not in self._allowed_fields:
                delattr(self, field.name)

        if "checked" in allowed_states and proposal.state != "new":
            if proposal.type_info.review_type == "anonymous":
                self.checked.label.text = "Send to anonymisation"
            else:
                # We already have the "send to manual review" button which will do the same thing as "checked"
                del self.checked

    def result(self) -> ProposalState:
        for field in self._allowed_fields:
            if getattr(self, field) and getattr(self, field).data:
                for k, v in STATE_FIELDS.items():
                    if field in v:
                        return k
        raise ValueError("No result for ProposalStateForm")


class ConvertProposalForm(Form):
    new_type = SelectField("Destination type")
    convert = SubmitField("Convert")


class ScheduleItemForm(Form):
    state = SelectField("State", choices=[(s, s.title()) for s in get_args(ScheduleItemState)])

    # Allow blank values so an item can be published without doxxing
    names = StringField("Names")
    pronouns = StringField("Pronouns")
    title = StringField("Title", [DataRequired()])
    description = TextAreaField("Description", [DataRequired()])
    short_description = StringField("Short description")

    official_content = SelectField(
        "Official content",
        choices=[("official", "Official content"), ("attendee", "Attendee content")],
        coerce=lambda v: v == "official",
    )

    video_privacy = SelectField(
        "Recording",
        choices=[
            ("public", "Stream and record"),
            ("review", "Do not stream, and do not publish until reviewed"),
            ("none", "Do not stream or record"),
        ],
        default="public",
    )

    contact_telephone = StringField("Telephone")


class UpdateScheduleItemForm(ScheduleItemForm):
    update = SubmitField("Update")


class ConvertScheduleItemForm(Form):
    new_type = SelectField("Destination type")
    convert = SubmitField("Convert")


class UpdateAvailabilityForm(Form):
    update = SubmitField("Update")


# The forms below should match the Attribute subclasses in the model.
# TODO: maybe we could replace this all with some generic fields and type annotation.
class UpdateAttributesForm(Form):
    pass


class UpdateScheduleItemTalkAttributesForm(UpdateAttributesForm):
    content_note = StringField("Content note")
    needs_laptop = SelectField(
        "Needs laptop",
        choices=[
            (0, "Is providing their own laptop"),
            (1, "Needs to borrow a laptop for the talk"),
        ],
        coerce=int,
        validators=[Optional()],
    )
    family_friendly = BooleanField("Family Friendly")


class UpdateScheduleItemPerformanceAttributesForm(UpdateAttributesForm):
    pass


class UpdateScheduleItemWorkshopAttributesForm(UpdateAttributesForm):
    age_range = StringField("Age range")
    participant_cost = StringField("Cost per attendee")
    participant_equipment = StringField("Attendee equipment")
    content_note = StringField("Content note")
    family_friendly = BooleanField("Family Friendly")


class UpdateScheduleItemFamilyWorkshopAttributesForm(UpdateAttributesForm):
    age_range = StringField("Age range")
    participant_cost = StringField("Cost per attendee")
    participant_equipment = StringField("Attendee equipment")
    content_note = StringField("Content note")


class UpdateScheduleItemLightningTalkAttributesForm(UpdateAttributesForm):
    session = StringField("Day")
    slide_link = StringField("Link")


class UpdateScheduleItemFilmForm(UpdateAttributesForm):
    classification = StringField("Classification")


# And now the additional Proposal-only fields.
class UpdateProposalTalkAttributesForm(UpdateScheduleItemTalkAttributesForm):
    pass


class UpdateProposalPerformanceAttributesForm(UpdateScheduleItemPerformanceAttributesForm):
    pass


class UpdateProposalWorkshopAttributesForm(UpdateScheduleItemWorkshopAttributesForm):
    participant_count = StringField("Attendees", [DataRequired()])


class UpdateProposalFamilyWorkshopAttributesForm(UpdateScheduleItemFamilyWorkshopAttributesForm):
    participant_count = StringField("Attendees", [DataRequired()])


class UpdateProposalInstallationAttributesForm(UpdateAttributesForm):
    size = StringField("Size", [DataRequired()])
    grant_requested = StringField("Installation Grant Requested")


# Lightning talks don't exist as Proposals


UPDATE_PROPOSAL_ATTRIBUTES_FORM_TYPES: dict[ProposalType, type[UpdateAttributesForm]] = {
    "talk": UpdateProposalTalkAttributesForm,
    "workshop": UpdateProposalWorkshopAttributesForm,
    "familyworkshop": UpdateProposalFamilyWorkshopAttributesForm,
    "performance": UpdateProposalPerformanceAttributesForm,
    "installation": UpdateProposalInstallationAttributesForm,
}

UPDATE_SCHEDULE_ITEM_ATTRIBUTES_FORM_TYPES: dict[ScheduleItemType, type[UpdateAttributesForm]] = {
    "talk": UpdateScheduleItemTalkAttributesForm,
    "workshop": UpdateScheduleItemWorkshopAttributesForm,
    "familyworkshop": UpdateScheduleItemFamilyWorkshopAttributesForm,
    "performance": UpdateScheduleItemPerformanceAttributesForm,
    "lightning": UpdateScheduleItemLightningTalkAttributesForm,
    "film": UpdateScheduleItemFilmForm,
}


class ResolveVoteForm(Form):
    id = HiddenIntegerField("Vote Id")
    resolve = BooleanField("Set to 'resolved'")


class UpdateVotesForm(Form):
    votes_to_resolve = FieldList(FormField(ResolveVoteForm))
    include_recused = BooleanField("Also set 'recused' votes to 'stale'")
    set_all_stale = SubmitField("Set all votes to 'stale'")
    resolve_all = SubmitField("Set all 'blocked' votes to 'resolved'")
    update = SubmitField("Set selected votes to 'resolved'")
    set_all_read = SubmitField("Set all notes to read")


class AnonymiseProposalForm(Form):
    title = StringField("Title", [DataRequired()])
    description = TextAreaField("Description", [DataRequired()])
    anonymise = SubmitField("Send to review and go to next")
    reject = SubmitField("I cannot anonymise this proposal")


class VoteForm(Form):
    vote_poor = SubmitField("Poor")
    vote_ok = SubmitField("OK")
    vote_excellent = SubmitField("Excellent")

    note = TextAreaField("Message")

    change = SubmitField("I'd like to change my response")
    recuse = SubmitField("I can identify the submitter (do not vote)")
    block = SubmitField("Raise an issue with this proposal")

    def validate_note(form, field):
        if not field.data and form.recuse.data:
            raise ValidationError(
                "Please tell us why you're not voting. If you can identify the submitter, please tell us who it is."
            )
        if not field.data and form.block.data:
            raise ValidationError("Please let us know what the issue is")


class CloseRoundForm(Form):
    min_votes = IntegerField("Minimum number of votes", default=10, validators=[NumberRange(min=1)])
    close_round = SubmitField("Close this round...")
    confirm = SubmitField("Confirm")
    cancel = SubmitField("Cancel")


class AcceptanceForm(Form):
    min_score = FloatField("Minimum score for acceptance")
    set_score = SubmitField("Preview proposals to be selected...")
    confirm_type = SelectField(
        "Messaging",
        choices=[
            (
                "accepted_unaccepted",
                "Email accepted, notify unaccepted about the next round",
            ),
            ("accepted", "Email accepted, do not email unaccepted"),
            ("nobody", "Email nobody"),
            ("accepted_reject", "Email accepted, reject all unaccepted"),
        ],
        default="accepted_unaccepted",
    )
    confirm = SubmitField("Confirm")
    cancel = SubmitField("Cancel")


class ReviewListForm(Form):
    show_proposals = SubmitField("Show me some more proposals")
    reload_proposals = SubmitField("Show some different proposals")


class SendMessageForm(Form):
    message = TextAreaField("New Message")
    send = SubmitField("Send Message")
    mark_read = SubmitField("Mark all as read")

    def validate_message(form, field):
        if form.mark_read.data and field.data:
            raise ValidationError("Cannot mark as read with a draft reply")

        if form.send.data and not field.data:
            raise ValidationError("Message is required")


class PrivateNotesForm(Form):
    private_notes = TextAreaField("Private notes")
    update = SubmitField("Update notes")

    def __init__(self, proposal: Proposal) -> None:
        super().__init__(data={"private_notes": proposal.private_notes})


class ChangeProposalOwner(Form):
    user_email = EmailField("Email address to associate this proposal with", [DataRequired()])
    user_name = StringField("User name (if creating new user)")
    submit = SubmitField("Change proposal owner")

    def validate_user_name(form, field):
        form._user = db.session.scalar(select(User).where(User.email == form.user_email.data))
        if form._user and form.user_name.data:
            raise ValidationError("User already exists, please check and remove name if correct")

        if not form._user and not form.user_name.data:
            raise ValidationError("New user requires a name")


class ChangeScheduleItemOwner(Form):
    user_email = EmailField("Email address to associate this schedule item with", [DataRequired()])
    user_name = StringField("User name (if creating new user)")
    submit = SubmitField("Change schedule item owner")

    def validate_user_name(form, field):
        form._user = db.session.scalar(select(User).where(User.email == form.user_email.data))
        if form._user and form.user_name.data:
            raise ValidationError("User already exists, please check and remove name if correct")

        if not form._user and not form.user_name.data:
            raise ValidationError("New user requires a name")


class ReversionForm(Form):
    revert = SubmitField("Revert to this version")


class InviteSpeakerForm(NewUserForm):
    invite_reason = StringField("Why are they being invited?", [DataRequired()])
    proposal_type = SelectField(
        "Proposal Type",
        choices=[(t.type, t.human_type) for t in PROPOSAL_INFOS.values()],
    )


class CreateOccurrenceForm(Form):
    create = SubmitField("Create new occurrence")


def valid_venue(form, field):
    if not field.data:
        return
    count = Venue.query.filter_by(name=field.data).count()
    if count != 1:
        raise ValidationError("Cannot identify venue")


class UpdateOccurrenceForm(Form):
    occurrence_num = IntegerField("Occurrence number")

    manually_scheduled = BooleanField("Manually scheduled")
    scheduled_duration = IntegerField("Duration in minutes", [Optional()])

    # allowed_venues is an association so we need to assign Venues
    allowed_venue_ids = SelectMultipleField("Allowed venues", coerce=int)
    scheduled_venue_id = SelectField("Scheduled venue", coerce=coerce_optional(int))
    scheduled_time = DateTimeField("Scheduled time", [Optional(strip_whitespace=True)])

    c3voc_url = StringField("C3VOC video URL")
    youtube_url = StringField("YouTube URL")
    thumbnail_url = StringField("Video thumbnail URL")
    video_recording_lost = BooleanField("Video recording lost")

    update = SubmitField("Update")

    def validate_scheduled_duration(form, field):
        duration_minutes = SLOT_DURATION.total_seconds() / 60

        if field.data % duration_minutes != 0:
            raise ValidationError(f"Must be a multiple of {duration_minutes} minutes")


class LotteryForm(Form):
    state = SelectField(
        "Lottery state",
        choices=[
            ("closed", "Closed"),
            ("allow-entry", "Allow entry"),
            # running-lottery
            ("completed", "Completed"),
            ("first-come-first-served", "First come first served"),
        ],
    )
    total_tickets = IntegerField("Total tickets")
    reserved_tickets = IntegerField("Reserved (non-lottery) tickets")
    max_tickets_per_entry = IntegerField("Max tickets per user")
