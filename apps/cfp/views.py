from flask import (
    render_template,
    redirect,
    request,
    flash,
    url_for,
    abort,
    current_app as app,
    Markup,
    render_template_string,
)
from flask_login import current_user
from flask_mailman import EmailMessage
from wtforms.validators import DataRequired, ValidationError, URL
from wtforms import BooleanField, StringField, SubmitField, TextAreaField, SelectField
import collections

from sqlalchemy.exc import IntegrityError

from main import db, external_url
from models.user import User, UserDiversity
from models.cfp import (
    TalkProposal,
    WorkshopProposal,
    YouthWorkshopProposal,
    PerformanceProposal,
    InstallationProposal,
    LightningTalkProposal,
    Proposal,
    CFPMessage,
    LENGTH_OPTIONS,
    PROPOSAL_TIMESLOTS,
    LIGHTNING_TALK_SESSIONS,
)
from ..common import feature_flag, feature_enabled, create_current_user
from ..common.email import from_email
from ..common.forms import Form, TelField, EmailField
from ..common.irc import irc_send

from . import cfp


class ProposalForm(Form):
    name = StringField("Name", [DataRequired()])
    email = EmailField("Email")
    title = StringField("Title", [DataRequired()])
    description = TextAreaField("Description", [DataRequired()])
    requirements = TextAreaField("Additional Info")
    needs_help = BooleanField("Needs help")
    user_scheduled = BooleanField("User scheduled")
    notice_required = SelectField(
        "Required notice",
        default="1 week",
        choices=[
            ("1 week", "1 week"),
            ("1 month", "1 month"),
            ("> 1 month", "Longer than 1 month"),
            ("> 3 months", "Longer than 3 months"),
        ],
    )

    def validate_email(form, field):
        if current_user.is_anonymous and User.does_user_exist(field.data):
            field.was_duplicate = True
            cfp_url = url_for("cfp.main")

            msg = Markup(
                render_template_string(
                    """You already have an account.
                Please <a href="{{ url }}" target="_new">click here</a> to log in.""",
                    url=url_for("users.login", next=cfp_url, email=field.data),
                )
            )

            raise ValidationError(msg)


class TalkProposalForm(ProposalForm):
    model = TalkProposal
    length = SelectField("Duration", default="25-45 mins", choices=LENGTH_OPTIONS)


class WorkshopProposalForm(ProposalForm):
    model = WorkshopProposal
    length = StringField("Duration", [DataRequired()])
    attendees = StringField("Attendees", [DataRequired()])
    cost = StringField("Cost per attendee")
    participant_equipment = StringField("Attendee equipment")
    age_range = StringField("Age range")


class YouthWorkshopProposalForm(ProposalForm):
    model = YouthWorkshopProposal
    length = StringField("Duration", [DataRequired()])
    attendees = StringField("Attendees", [DataRequired()])
    cost = StringField("Cost per attendee")
    participant_equipment = StringField("Attendee equipment")
    age_range = StringField("Age range")
    valid_dbs = BooleanField("I have a valid DBS check")


class PerformanceProposalForm(ProposalForm):
    model = PerformanceProposal
    length = SelectField("Duration", default="25-45 mins", choices=LENGTH_OPTIONS)


class InstallationProposalForm(ProposalForm):
    model = InstallationProposal
    size = SelectField(
        "Physical size",
        default="medium",
        choices=[
            ("small", "Smaller than a wheelie bin"),
            ("medium", "Smaller than a car"),
            ("large", "Smaller than a lorry"),
            ("huge", "Bigger than a lorry"),
        ],
    )
    funds = SelectField(
        "Funding",
        choices=[
            ("0", "No money needed"),
            ("< £50", "Less than £50"),
            ("< £100", "Less than £100"),
            ("< £300", "Less than £300"),
            ("< £500", "Less than £500"),
            ("> £500", "More than £500"),
        ],
    )


class LightningTalkProposalForm(ProposalForm):
    model = LightningTalkProposal
    slide_link = StringField("Link to your slides (PDF only)", [DataRequired(), URL()])
    # Choices for session field generated in line
    session = SelectField("Choose the session you'd like to present at")

    def set_session_choices(self, remaining_lightning_slots):
        self.session.choices = []
        for (day_id, day_count) in remaining_lightning_slots.items():
            if day_count <= 0:
                continue
            self.session.choices.append((day_id, LIGHTNING_TALK_SESSIONS[day_id]))


def get_cfp_type_form(cfp_type):
    form = None
    if cfp_type == "talk":
        form = TalkProposalForm()
    elif cfp_type == "performance":
        form = PerformanceProposalForm()
    elif cfp_type == "workshop":
        form = WorkshopProposalForm()
    elif cfp_type == "youthworkshop":
        form = YouthWorkshopProposalForm()
    elif cfp_type == "installation":
        form = InstallationProposalForm()
    elif cfp_type == "lightning":
        form = LightningTalkProposalForm()
    return form


@cfp.route("/cfp")
@feature_flag("CFP")
def main():
    ignore_closed = "closed" in request.args

    if feature_enabled("CFP_CLOSED") and not ignore_closed:
        return render_template("cfp/closed.html")

    lightning_talks_closed = all(
        [i <= 0 for i in LightningTalkProposal.get_remaining_lightning_slots().values()]
    )

    return render_template(
        "cfp/main.html",
        ignore_closed=ignore_closed,
        lightning_talks_closed=lightning_talks_closed,
    )


@cfp.route("/cfp/<string:cfp_type>", methods=["GET", "POST"])
@feature_flag("CFP")
def form(cfp_type="talk"):
    form = get_cfp_type_form(cfp_type)
    if not form:
        abort(404)

    ignore_closed = "closed" in request.args

    if feature_enabled("CFP_CLOSED") and not ignore_closed:
        return render_template("cfp/closed.html", cfp_type=cfp_type)

    if (
        cfp_type == "lightning"
        and not feature_enabled("LIGHTNING_TALKS")
        and not current_user.has_permission("cfp_admin")
    ):
        flash("We're not currently accepting Lightning Talks.")
        return redirect(url_for(".main"))

    remaining_lightning_slots = LightningTalkProposal.get_remaining_lightning_slots()
    # Require logged in users as you have to have a ticket to lightning talk
    if cfp_type == "lightning" and current_user.is_anonymous:
        return redirect(
            url_for("users.login", next=url_for(".form", cfp_type="lightning"))
        )
    elif cfp_type == "lightning":
        if all(
            [
                i <= 0
                for i in LightningTalkProposal.get_remaining_lightning_slots().values()
            ]
        ):
            flash("All lightning talk sessions are now full, sorry")
            return redirect(url_for(".main"))
        form.set_session_choices(remaining_lightning_slots)

    # If the user is already logged in set their name & email for the form
    if current_user.is_authenticated:
        form.email.data = current_user.email
        if current_user.name != current_user.email:
            form.name.data = current_user.name

    if request.method == "POST":
        app.logger.info(
            "Checking %s proposal for %s (%s)",
            cfp_type,
            form.name.data,
            form.email.data,
        )

    if form.validate_on_submit():
        new_user = False
        if current_user.is_anonymous:
            try:
                create_current_user(form.email.data, form.name.data)
                new_user = True
            except IntegrityError as e:
                app.logger.warn("Adding user raised %r, possible double-click", e)
                flash(
                    "An error occurred while creating an account for you. Please try again."
                )
                return redirect(url_for(".main"))

        elif current_user.name == current_user.email:
            current_user.name = form.name.data

        if cfp_type == "talk":
            cfp = TalkProposal()
            cfp.length = form.length.data

        elif cfp_type == "performance":
            cfp = PerformanceProposal()
            cfp.length = form.length.data

        elif cfp_type == "workshop":
            cfp = WorkshopProposal()
            cfp.length = form.length.data
            cfp.attendees = form.attendees.data
            cfp.cost = form.cost.data
            cfp.participant_equipment = form.participant_equipment.data
            cfp.age_range = form.age_range.data

        elif cfp_type == "youthworkshop":
            cfp = YouthWorkshopProposal()
            cfp.length = form.length.data
            cfp.attendees = form.attendees.data
            cfp.cost = form.cost.data
            cfp.participant_equipment = form.participant_equipment.data
            cfp.age_range = form.age_range.data
            cfp.valid_dbs = form.valid_dbs.data

        elif cfp_type == "installation":
            cfp = InstallationProposal()
            cfp.size = form.size.data
            cfp.funds = form.funds.data

        elif cfp_type == "lightning":
            if remaining_lightning_slots[form.session.data] <= 0:
                # Manually set this because otherwise we need to pass the
                # remaining_lightning_slots object to validate
                form.errors[
                    "sessions"
                ] = "That session is now full, sorry. Please select a different day"
                return render_template(
                    "cfp/new.html",
                    cfp_type=cfp_type,
                    form=form,
                    has_errors=bool(form.errors),
                    ignore_closed=ignore_closed,
                )

            cfp = LightningTalkProposal()
            cfp.slide_link = form.slide_link.data
            cfp.session = form.session.data

        cfp.user_id = current_user.id

        cfp.title = form.title.data
        cfp.requirements = form.requirements.data
        cfp.description = form.description.data
        cfp.notice_required = form.notice_required.data
        cfp.needs_help = form.needs_help.data

        db.session.add(cfp)
        db.session.commit()

        # Send confirmation message
        msg = EmailMessage(
            "Electromagnetic Field CFP Submission",
            from_email=from_email("CONTENT_EMAIL"),
            to=[current_user.email],
        )

        msg.body = render_template(
            "emails/cfp-submission.txt", proposal=cfp, new_user=new_user
        )
        msg.send()

        if channel := app.config.get("CONTENT_IRC_CHANNEL"):
            # WARNING: don't send personal information via this (the channel is public)
            irc_send(
                f"{channel} New CfP {cfp.human_type} submission: {external_url('cfp_review.update_proposal', proposal_id=cfp.id)}"
            )
        return redirect(url_for(".complete"))

    full_lightning_sessions = [
        LIGHTNING_TALK_SESSIONS[day]
        for (day, remaining) in remaining_lightning_slots.items()
        if remaining <= 0
    ]

    return render_template(
        "cfp/new.html",
        cfp_type=cfp_type,
        form=form,
        has_errors=bool(form.errors),
        ignore_closed=ignore_closed,
        full_lightning_sessions=full_lightning_sessions,
    )


class DiversityForm(Form):
    age = StringField("Age")
    gender = StringField("Gender")
    ethnicity = StringField("Ethnicity")


@cfp.route("/cfp/complete", methods=["GET", "POST"])
@feature_flag("CFP")
def complete():
    if current_user.is_anonymous:
        return redirect(url_for(".main"))
    form = DiversityForm()
    if form.validate_on_submit():
        if not current_user.diversity:
            current_user.diversity = UserDiversity()

        current_user.diversity.age = form.age.data
        current_user.diversity.gender = form.gender.data
        current_user.diversity.ethnicity = form.ethnicity.data

        db.session.commit()
        return redirect(url_for(".proposals"))

    return render_template("cfp/complete.html", form=form)


@cfp.route("/cfp/proposals")
@feature_flag("CFP")
def proposals():
    if current_user.is_anonymous:
        return redirect(url_for(".main"))

    proposals = current_user.proposals
    if not proposals:
        return redirect(url_for(".main"))

    for proposal in proposals:
        if proposal.scheduled_venue:
            proposal.scheduled_venue_name = proposal.scheduled_venue.name

    return render_template("cfp/proposals.html", proposals=proposals)


@cfp.route("/cfp/proposals/<int:proposal_id>/edit", methods=["GET", "POST"])
@feature_flag("CFP")
def edit_proposal(proposal_id):
    if current_user.is_anonymous:
        return redirect(
            url_for(
                "users.login", next=url_for(".edit_proposal", proposal_id=proposal_id)
            )
        )

    proposal = Proposal.query.get_or_404(proposal_id)
    if proposal.user != current_user:
        abort(404)

    form = get_cfp_type_form(proposal.type)
    del form.name
    del form.email

    if form.validate_on_submit():
        if proposal.state not in ["new", "edit"]:
            flash("This submission can no longer be edited.")
            return redirect(url_for(".proposals"))

        app.logger.info("Proposal %s edited", proposal.id)

        if proposal.type in ("talk", "performance"):
            proposal.length = form.length.data

        elif proposal.type == "workshop":
            proposal.length = form.length.data
            proposal.attendees = form.attendees.data
            proposal.cost = form.cost.data
            proposal.participant_equipment = form.participant_equipment.data
            proposal.age_range = form.age_range.data

        elif proposal.type == "youthworkshop":
            proposal.length = form.length.data
            proposal.attendees = form.attendees.data
            proposal.cost = form.cost.data
            proposal.participant_equipment = form.participant_equipment.data
            proposal.age_range = form.age_range.data
            proposal.valid_dbs = form.valid_dbs.data

        elif proposal.type == "installation":
            proposal.size = form.size.data
            proposal.funds = form.funds.data

        elif proposal.type == "lightning":
            proposal.slide_link = form.slide_link.data
            proposal.allowed_times = form.session.data

        proposal.title = form.title.data
        proposal.description = form.description.data
        proposal.requirements = form.requirements.data
        proposal.notice_required = form.notice_required.data
        proposal.needs_help = form.needs_help.data

        db.session.commit()
        flash("Your proposal has been updated")

        return redirect(url_for(".edit_proposal", proposal_id=proposal_id))

    if request.method != "POST" and proposal.state in ["new", "edit"]:
        if proposal.type in ("talk", "performance"):
            form.length.data = proposal.length

        elif proposal.type == "workshop":
            form.length.data = proposal.length
            form.attendees.data = proposal.attendees
            form.cost.data = proposal.cost
            form.participant_equipment.data = proposal.participant_equipment
            form.age_range.data = proposal.age_range

        elif proposal.type == "youthworkshop":
            form.length.data = proposal.length
            form.attendees.data = proposal.attendees
            form.cost.data = proposal.cost
            form.participant_equipment.data = proposal.participant_equipment
            form.age_range.data = proposal.age_range
            form.valid_dbs.data = proposal.valid_dbs

        elif proposal.type == "installation":
            form.size.data = proposal.size
            form.funds.data = proposal.funds

        elif proposal.type == "lightning":
            form.slide_link.data = proposal.slide_link

            remaining_lightning_slots = (
                LightningTalkProposal.get_remaining_lightning_slots()
            )
            # Make sure that their previously selected session is a choice
            if remaining_lightning_slots[proposal.session] <= 0:
                remaining_lightning_slots[proposal.session] = 1
            form.set_session_choices(remaining_lightning_slots)
            form.session.data = proposal.session

        form.title.data = proposal.title
        form.description.data = proposal.description
        form.requirements.data = proposal.requirements
        form.notice_required.data = proposal.notice_required
        form.needs_help.data = proposal.needs_help

    if proposal.scheduled_venue:
        proposal.scheduled_venue_name = proposal.scheduled_venue.name

    return render_template("cfp/edit.html", proposal=proposal, form=form)


class WithdrawalForm(Form):
    message = TextAreaField(
        "If you're comfortable, please tell us why you're withdrawing"
    )
    confirm_withdrawal = SubmitField("Confirm proposal withdrawal")


@cfp.route("/cfp/proposals/<int:proposal_id>/withdraw", methods=["GET", "POST"])
@feature_flag("CFP")
def withdraw_proposal(proposal_id):
    if current_user.is_anonymous:
        return redirect(
            url_for(
                "users.login", next=url_for(".edit_proposal", proposal_id=proposal_id)
            )
        )

    proposal = Proposal.query.get_or_404(proposal_id)
    if proposal.user != current_user:
        abort(404)

    form = WithdrawalForm()
    if form.validate_on_submit():
        if form.confirm_withdrawal.data:

            app.logger.info("Proposal %s is being withdrawn.", proposal_id)
            proposal.set_state("withdrawn")

            msg = CFPMessage()
            msg.is_to_admin = True
            msg.from_user_id = current_user.id
            msg.proposal_id = proposal_id
            msg.message = form.message.data

            db.session.add(msg)
            db.session.commit()
            flash("We've withdrawn your {0.type}, {0.title}.".format(proposal))

            return redirect(url_for("cfp.proposals"))

    return render_template("cfp/withdraw.html", form=form, proposal=proposal)


class AcceptedForm(Form):
    name = StringField("Names for schedule", [DataRequired()])
    pronouns = StringField("Pronouns")
    title = StringField("Title", [DataRequired()])
    description = TextAreaField("Description", [DataRequired()])
    age_range = StringField("Age Range")
    cost = StringField("Cost Per Attendee")
    participant_equipment = StringField("Attendee Equipment")
    telephone_number = TelField("Telephone")
    eventphone_number = TelField("On-site extension", min_length=3, max_length=5)

    may_record = BooleanField("I am happy for this to be recorded", default=True)
    needs_laptop = BooleanField("I will need to borrow a laptop for slides")
    requirements = TextAreaField("Requirements")
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
    _available_slots: tuple = tuple()

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


@cfp.route("/cfp/proposals/<int:proposal_id>/finalise", methods=["GET", "POST"])
@feature_flag("CFP")
@feature_flag("CFP_FINALISE")
def finalise_proposal(proposal_id):
    if current_user.is_anonymous:
        return redirect(
            url_for(
                "users.login",
                next=url_for(".finalise_proposal", proposal_id=proposal_id),
            )
        )

    proposal = Proposal.query.get_or_404(proposal_id)
    if proposal.user != current_user:
        abort(404)

    if proposal.state not in ("accepted", "finished"):
        return redirect(url_for(".edit_proposal", proposal_id=proposal_id))

    # This is horrendous, but is a lot cleaner than having shitloads of classes and fields
    # http://wtforms.simplecodes.com/docs/1.0.1/specific_problems.html#dynamic-form-composition
    slot_times = slot_titles = day_form_slots = None

    class F(AcceptedForm):
        pass

    if proposal.type in ("talk", "workshop", "youthworkshop", "performance"):
        F._available_slots = PROPOSAL_TIMESLOTS[proposal.type]
        for timeslot in F._available_slots:
            setattr(F, timeslot, BooleanField(default=True))

    form = F()

    if proposal.scheduled_venue:
        proposal.scheduled_venue_name = proposal.scheduled_venue.name

    if form.validate_on_submit():
        proposal.published_names = form.name.data
        proposal.published_pronouns = form.pronouns.data
        proposal.published_title = form.title.data
        proposal.published_description = form.description.data
        proposal.telephone_number = form.telephone_number.data
        proposal.eventphone_number = form.eventphone_number.data

        proposal.may_record = form.may_record.data
        proposal.needs_laptop = form.needs_laptop.data
        proposal.requirements = form.requirements.data

        proposal.arrival_period = form.arrival_period.data
        proposal.departure_period = form.departure_period.data

        if proposal.type == "workshop" or proposal.type == "youthworkshop":
            proposal.published_age_range = form.age_range.data
            proposal.published_cost = form.cost.data
            proposal.published_participant_equipment = form.participant_equipment.data

        proposal.available_times = form.get_availability_json()
        proposal.set_state("finished")

        db.session.commit()
        app.logger.info("Finished proposal %s", proposal_id)
        flash("Thank you for finalising your details!")

        return redirect(url_for(".edit_proposal", proposal_id=proposal_id))

    elif proposal.state == "finished":
        if proposal.published_names:
            form.name.data = proposal.published_names
        else:
            form.name.data = current_user.name

        form.pronouns.data = proposal.published_pronouns
        form.title.data = proposal.published_title
        form.description.data = proposal.published_description
        form.telephone_number.data = proposal.telephone_number
        form.eventphone_number.data = proposal.eventphone_number

        form.may_record.data = proposal.may_record
        form.needs_laptop.data = proposal.needs_laptop
        form.requirements.data = proposal.requirements

        if proposal.type == "workshop" or proposal.type == "youthworkshop":
            form.age_range.data = proposal.published_age_range
            form.cost.data = proposal.published_cost
            form.participant_equipment.data = proposal.published_participant_equipment

        # We do this here because we're about to generate form elements
        if proposal.available_times:
            form.set_from_availability_json(proposal.available_times)

        form.arrival_period.data = proposal.arrival_period
        form.departure_period.data = proposal.departure_period

    else:
        form.name.data = current_user.name
        form.title.data = proposal.title
        form.description.data = proposal.description

        if proposal.type == "workshop" or proposal.type == "youthworkshop":
            form.age_range.data = proposal.age_range
            form.cost.data = proposal.cost
            form.participant_equipment.data = proposal.participant_equipment

    # This just sorts out the headings / columns for the form
    headings = {}
    day_form_slots = collections.defaultdict(collections.OrderedDict)
    for slot in F._available_slots:
        day, start, end = slot.split("_")
        slot_hour_str = "%s_%s" % (start, end)
        day_form_slots[day][slot_hour_str] = getattr(form, slot)(class_="form-control")
        headings[int(start)] = (int(start), int(end))

    slot_times = []
    slot_titles = []
    for start in sorted(headings.keys()):
        start, end = headings[start]
        slot_times.append("%s_%s" % (start, end))

        start_ampm = end_ampm = "am"
        if start > 12:
            start_ampm = "pm"
            start -= 12
        if end > 12:
            end_ampm = "pm"
            end -= 12
        slot_titles.append("%s%s - %s%s" % (start, start_ampm, end, end_ampm))

    return render_template(
        "cfp/accepted.html",
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
    proposal = Proposal.query.get_or_404(proposal_id)
    if proposal.user_id != current_user.id:
        abort(404)

    form = MessagesForm()

    if form.validate_on_submit():
        if form.send.data:
            msg = CFPMessage()
            msg.is_to_admin = True
            msg.from_user_id = current_user.id
            msg.proposal_id = proposal_id
            msg.message = form.message.data

            db.session.add(msg)
            db.session.commit()
            if channel := app.config.get("CONTENT_IRC_CHANNEL"):
                # WARNING: don't send personal information via this (the channel is public)
                irc_send(
                    f"{channel} New CfP message for {proposal.human_type}: {external_url('cfp_review.message_proposer', proposal_id=proposal_id)}"
                )

        count = proposal.mark_messages_read(current_user)
        db.session.commit()
        app.logger.info(
            "Marked %s messages to admin on proposal %s as read" % (count, proposal.id)
        )

        return redirect(url_for(".proposal_messages", proposal_id=proposal_id))

    messages = (
        CFPMessage.query.filter_by(proposal_id=proposal_id).order_by("created").all()
    )

    return render_template(
        "cfp/messages.html", proposal=proposal, messages=messages, form=form
    )


@cfp.route("/cfp/messages")
@feature_flag("CFP")
def all_messages():
    if current_user.is_anonymous:
        return redirect(url_for(".main"))

    proposal_with_message = (
        Proposal.query.join(CFPMessage)
        .filter(
            Proposal.id == CFPMessage.proposal_id, Proposal.user_id == current_user.id
        )
        .order_by(CFPMessage.has_been_read, CFPMessage.created.desc())
        .all()
    )

    proposal_with_message.sort(
        key=lambda x: (x.get_unread_count(current_user) > 0, x.created), reverse=True
    )

    return render_template(
        "cfp/all_messages.html", proposal_with_message=proposal_with_message
    )


@cfp.route("/cfp/guidance")
def guidance():
    return render_template("cfp/guidance.html")


@cfp.route("/cfp/installation-support")
def installation_support():
    return render_template("cfp/installation_support.html")
