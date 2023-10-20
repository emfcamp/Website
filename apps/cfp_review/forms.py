import dateutil
from wtforms import (
    SubmitField,
    StringField,
    FieldList,
    FormField,
    RadioField,
    SelectField,
    TextAreaField,
    BooleanField,
    IntegerField,
    FloatField,
)
from wtforms.validators import DataRequired, Optional, NumberRange, ValidationError

from models.cfp import Venue, ORDERED_STATES
from models.cfp_tag import Tag
from ..common.forms import Form, HiddenIntegerField, EmailField

from dateutil.parser import parse as parse_date


class UpdateProposalForm(Form):
    # Admin can change anything
    state = SelectField("State", choices=[(s, s) for s in ORDERED_STATES])
    title = StringField("Title", [DataRequired()])
    description = TextAreaField("Description", [DataRequired()])
    tags = StringField("Tags")
    requirements = TextAreaField("Requirements")
    length = StringField("Length")
    notice_required = SelectField(
        "Required notice",
        choices=[
            ("1 week", "1 week"),
            ("1 month", "1 month"),
            ("> 1 month", "Longer than 1 month"),
            ("> 3 months", "Longer than 3 months"),
        ],
    )
    needs_help = BooleanField("Needs Help")
    needs_money = BooleanField("Needs Money")
    one_day = BooleanField("One day only")
    will_have_ticket = BooleanField("Will have a ticket")
    user_scheduled = BooleanField("User Scheduled")

    published_names = StringField("Published names")
    published_pronouns = StringField("Published pronouns")
    published_title = StringField("Published title")
    published_description = TextAreaField("Published description")
    arrival_period = StringField("Arrival time")
    departure_period = StringField("Departure time")
    telephone_number = StringField("Telephone")
    eventphone_number = StringField("On-site extension")
    may_record = BooleanField("May record")
    needs_laptop = RadioField(
        "Needs laptop",
        choices=[
            (0, "Is providing their own laptop"),
            (1, "Needs to borrow a laptop for the talk"),
        ],
        coerce=int,
        validators=[Optional()],
    )
    available_times = StringField("Available times")

    content_note = StringField("Content note")
    family_friendly = BooleanField("Family Friendly")

    hide_from_schedule = BooleanField("Hide from schedule")
    allowed_venues = StringField("Allowed Venues")
    allowed_times = TextAreaField("Allowed Time Periods")
    scheduled_duration = StringField("Duration")
    scheduled_time = StringField("Scheduled Time")
    scheduled_venue = StringField("Scheduled Venue")
    potential_time = StringField("Potential Time")
    potential_venue = StringField("Potential Venue")

    update = SubmitField("Update")
    reject = SubmitField("Reject without telling user")
    checked = SubmitField("Mark as checked")
    accept = SubmitField("Accept and send email")
    reject_with_message = SubmitField("Reject and send email")

    def validate_allowed_times(self, field):
        try:
            for p in field.data.split("\n"):
                if p:
                    start, end = p.split(" > ")
                    parse_date(start)
                    parse_date(end)
        except ValueError:
            raise ValidationError(
                "Unparsable Allowed Times. Fmt: datetime > datetime per line"
            )

    def update_proposal(self, proposal):
        proposal.title = self.title.data
        proposal.description = self.description.data
        proposal.tags = Tag.parse_serialised_tags(self.tags.data)
        proposal.requirements = self.requirements.data
        proposal.length = self.length.data
        proposal.notice_required = self.notice_required.data
        proposal.needs_help = self.needs_help.data
        proposal.needs_money = self.needs_money.data
        proposal.one_day = self.one_day.data
        proposal.user.will_have_ticket = self.will_have_ticket.data
        proposal.user_scheduled = self.user_scheduled.data

        proposal.hide_from_schedule = self.hide_from_schedule.data

        # Just talks? Weird to have here

        if self.needs_laptop.raw_data:
            proposal.needs_laptop = self.needs_laptop.data
        if self.may_record.raw_data:
            proposal.may_record = self.may_record.data

        # All these if statements are because this will nuke the data if you
        # change the state when the fields are currently hidden, so changing
        # from finalised -> cancelled -> finalised will wipe it all oh no

        # Finalisation details
        if self.published_names.raw_data:
            proposal.published_names = self.published_names.data
        if self.published_pronouns.raw_data:
            proposal.published_pronouns = self.published_pronouns.data
        if self.published_title.raw_data:
            proposal.published_title = self.published_title.data
        if self.published_description.raw_data:
            proposal.published_description = self.published_description.data
        if self.content_note.raw_data:
            proposal.content_note = self.content_note.data
        if self.family_friendly.raw_data:
            proposal.family_friendly = self.family_friendly.data

        # Finalising schedule details
        if self.telephone_number.raw_data:
            proposal.telephone_number = self.telephone_number.data
        if self.eventphone_number.raw_data:
            proposal.eventphone_number = self.eventphone_number.data
        if self.arrival_period.raw_data:
            proposal.arrival_period = self.arrival_period.data
        if self.departure_period.raw_data:
            proposal.departure_period = self.departure_period.data
        if self.available_times.raw_data:
            proposal.available_times = self.available_times.data

        if self.scheduled_duration.data:
            proposal.scheduled_duration = self.scheduled_duration.data
        else:
            proposal.scheduled_duration = None

        # Windows users :(
        stripped_allowed_times = self.allowed_times.data.strip().replace("\r\n", "\n")
        if (
            proposal.get_allowed_time_periods_serialised().strip()
            != stripped_allowed_times
        ):
            if stripped_allowed_times:
                proposal.allowed_times = stripped_allowed_times
            else:
                proposal.allowed_times = None

        if self.scheduled_time.data:
            proposal.scheduled_time = dateutil.parser.parse(self.scheduled_time.data)
        else:
            proposal.scheduled_time = None

        if self.scheduled_venue.data:
            proposal.scheduled_venue = Venue.query.filter(
                Venue.name == self.scheduled_venue.data.strip()
            ).one()
        else:
            proposal.scheduled_venue = None

        if self.potential_time.data:
            proposal.potential_time = dateutil.parser.parse(self.potential_time.data)
        else:
            proposal.potential_time = None

        if self.potential_venue.data:
            proposal.potential_venue = Venue.query.filter(
                Venue.name == self.potential_venue.data.strip()
            ).one()
        else:
            proposal.potential_venue = None

        # Only set this if we're overriding the default
        if (
            proposal.get_allowed_venues_serialised().strip()
            != self.allowed_venues.data.strip()
        ):
            proposal.allowed_venues = self.allowed_venues.data.strip()
            # Validates the new data. Bit nasty.
            proposal.get_allowed_venues()


class ConvertProposalForm(Form):
    new_type = SelectField("Destination type")
    convert = SubmitField("Convert")


class UpdateTalkForm(UpdateProposalForm):
    pass


class UpdatePerformanceForm(UpdateProposalForm):
    pass


class UpdateLightningTalkForm(UpdateProposalForm):
    session = StringField("Day")
    slide_link = StringField("Link")

    def update_proposal(self, proposal):
        if self.session.raw_data:
            proposal.session = self.session.data
        if self.slide_link.raw_data:
            proposal.slide_link = self.slide_link.data
        super(UpdateLightningTalkForm, self).update_proposal(proposal)


class UpdateWorkshopForm(UpdateProposalForm):
    attendees = StringField("Attendees", [DataRequired()])
    cost = StringField("Cost per attendee")
    participant_equipment = StringField("Attendee equipment")
    age_range = StringField("Age range")
    published_cost = StringField("Attendee cost")
    published_participant_equipment = StringField("Attendee equipment")
    published_age_range = StringField("Attendee age range")

    def update_proposal(self, proposal):
        if self.attendees.raw_data:
            proposal.attendees = self.attendees.data
        if self.cost.raw_data:
            proposal.cost = self.cost.data
        if self.participant_equipment.raw_data:
            proposal.participant_equipment = self.participant_equipment.data
        if self.age_range.raw_data:
            proposal.age_range = self.age_range.data
        if self.published_cost.raw_data:
            proposal.published_cost = self.published_cost.data
        if self.published_participant_equipment.raw_data:
            proposal.published_participant_equipment = (
                self.published_participant_equipment.data
            )
        if self.published_age_range.raw_data:
            proposal.published_age_range = self.published_age_range.data
        super(UpdateWorkshopForm, self).update_proposal(proposal)


class UpdateYouthWorkshopForm(UpdateProposalForm):
    attendees = StringField("Attendees", [DataRequired()])
    cost = StringField("Cost per attendee")
    participant_equipment = StringField("Attendee equipment")
    age_range = StringField("Age range")
    published_cost = StringField("Attendee cost")
    published_participant_equipment = StringField("Attendee equipment")
    published_age_range = StringField("Attendee age range")
    valid_dbs = BooleanField("Has a valid DBS check")

    def update_proposal(self, proposal):
        if self.attendees.raw_data:
            proposal.attendees = self.attendees.data
        if self.cost.raw_data:
            proposal.cost = self.cost.data
        if self.participant_equipment.raw_data:
            proposal.participant_equipment = self.participant_equipment.data
        if self.age_range.raw_data:
            proposal.age_range = self.age_range.data
        if self.published_cost.raw_data:
            proposal.published_cost = self.published_cost.data
        if self.published_participant_equipment.raw_data:
            proposal.published_participant_equipment = (
                self.published_participant_equipment.data
            )
        if self.published_age_range.raw_data:
            proposal.published_age_range = self.published_age_range.data
        if self.valid_dbs.raw_data:
            proposal.valid_dbs = self.valid_dbs.data
        super(UpdateYouthWorkshopForm, self).update_proposal(proposal)


class UpdateInstallationForm(UpdateProposalForm):
    funds = StringField("Funds")
    size = StringField("Size", [DataRequired()])

    def update_proposal(self, proposal):
        if self.size.raw_data:
            proposal.size = self.size.data
        if self.funds.raw_data:
            proposal.funds = self.funds.data
        super(UpdateInstallationForm, self).update_proposal(proposal)


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
    question = SubmitField("I need more information")

    def validate_note(form, field):
        if not field.data and form.recuse.data:
            raise ValidationError(
                "Please tell us why you're not voting. If you can identify the submitter, please tell us who it is."
            )
        if not field.data and form.question.data:
            raise ValidationError("Please let us know what's unclear")


class CloseRoundForm(Form):
    min_votes = IntegerField(
        "Minimum number of votes", default=10, validators=[NumberRange(min=1)]
    )
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
        default="accepted",
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


class AddNoteForm(Form):
    notes = TextAreaField("Notes")
    send = SubmitField("Update notes")


class ChangeProposalOwner(Form):
    user_email = EmailField(
        "Which email address to associate this proposal with", [DataRequired()]
    )
    user_name = StringField("User name (if creating new user)")
    submit = SubmitField("Change proposal owner")


class ReversionForm(Form):
    proposal_id = HiddenIntegerField("Proposal ID")
    txn_id = HiddenIntegerField("Transaction ID")
    revert = SubmitField("Revert to this version")
