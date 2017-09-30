# encoding=utf-8
from flask import (
    render_template, redirect, request, flash,
    url_for, abort, current_app as app, Blueprint,
    Markup, render_template_string,
)
from flask.ext.login import current_user
from flask_mail import Message
from wtforms.validators import Required, Email, ValidationError
from wtforms import (
    BooleanField, StringField, SubmitField,
    TextAreaField, SelectField,
)

from sqlalchemy.exc import IntegrityError

from main import db, mail
from models.user import User, UserDiversity
from models.product import ProductGroup
from models.cfp import (
    TalkProposal, WorkshopProposal, InstallationProposal, Proposal, CFPMessage, Venue
)
from .common import feature_flag, create_current_user
from .common.forms import Form, TelField


cfp = Blueprint('cfp', __name__)

class ProposalForm(Form):
    name = StringField("Name", [Required()])
    email = StringField("Email", [Email(), Required()])
    title = StringField("Title", [Required()])
    description = TextAreaField("Description", [Required()])
    requirements = StringField("Requirements")
    needs_help = BooleanField("Needs help")
    notice_required = SelectField("Required notice", default="1 week",
                          choices=[('1 week', '1 week'),
                                   ('1 month', '1 month'),
                                   ('> 1 month', 'Longer than 1 month'),
                                  ])

    def validate_email(form, field):
        if current_user.is_anonymous and User.does_user_exist(field.data):
            field.was_duplicate = True
            cfp_url = url_for('cfp.main', cfp_type=form.active_cfp_type)

            msg = Markup(render_template_string('''You already have an account.
                Please <a href="{{ url }}" target="_new">click here</a> to log in.''',
                url=url_for('users.login', next=cfp_url, email=field.data)))

            raise ValidationError(msg)


class TalkProposalForm(ProposalForm):
    type = 'talk'
    length = SelectField("Duration", default='25-45 mins',
                         choices=[('< 10 mins', "Shorter than 10 minutes"),
                                  ('10-25 mins', "10-25 minutes"),
                                  ('25-45 mins', "25-45 minutes"),
                                  ('> 45 mins', "Longer than 45 minutes"),
                                  ])


class WorkshopProposalForm(ProposalForm):
    type = 'workshop'
    length = StringField("Duration", [Required()])
    attendees = StringField("Attendees", [Required()])
    cost = StringField("Cost per attendee")


class InstallationProposalForm(ProposalForm):
    type = 'installation'
    size = SelectField('Physical size', default="medium",
                                        choices=[('small', 'Smaller than a wheelie bin'),
                                                 ('medium', 'Smaller than a car'),
                                                 ('large', 'Smaller than a lorry'),
                                                 ('huge', 'Bigger than a lorry'),
                                                ])
    funds = SelectField('Funding', choices=[         ('0', 'No money needed'),
                                                     (u'< £50', u'Less than £50'),
                                                     (u'< £100', u'Less than £100'),
                                                     (u'< £300', u'Less than £300'),
                                                     (u'< £500', u'Less than £500'),
                                                     (u'> £500', u'More than £500'),
                                                    ])


@cfp.route('/cfp')
@cfp.route('/cfp/<string:cfp_type>', methods=['GET', 'POST'])
@feature_flag('CFP')
def main(cfp_type='talk'):
    if cfp_type not in ['talk', 'workshop', 'installation']:
        abort(404)

    ignore_closed = 'closed' in request.args

    if app.config.get('CFP_CLOSED') and not ignore_closed:
        return render_template('cfp/closed.html')

    forms = [TalkProposalForm(prefix="talk"),
             WorkshopProposalForm(prefix="workshop"),
             InstallationProposalForm(prefix="installation")]
    (form,) = [f for f in forms if f.type == cfp_type]
    form.active_cfp_type = cfp_type

    # If the user is already logged in set their name & email for the form
    if current_user.is_authenticated:
        form.name.data = current_user.name
        form.email.data = current_user.email

    if request.method == 'POST':
        app.logger.info('Checking %s proposal for %s (%s)', cfp_type,
                        form.name.data, form.email.data)

    if form.validate_on_submit():
        new_user = False
        if current_user.is_anonymous:
            try:
                create_current_user(form.email.data, form.name.data)
                new_user = True
            except IntegrityError as e:
                app.logger.warn('Adding user raised %r, possible double-click', e)
                flash('An error occurred while creating an account for you. Please try again.')
                return redirect(url_for('.main'))

        if cfp_type == 'talk':
            cfp = TalkProposal()
            cfp.length = form.length.data

        elif cfp_type == 'workshop':
            cfp = WorkshopProposal()
            cfp.length = form.length.data
            cfp.attendees = form.attendees.data
            cfp.cost = form.cost.data

        elif cfp_type == 'installation':
            cfp = InstallationProposal()
            cfp.size = form.size.data
            cfp.funds = form.funds.data

        cfp.user_id = current_user.id

        cfp.title = form.title.data
        cfp.requirements = form.requirements.data
        cfp.description = form.description.data
        cfp.notice_required = form.notice_required.data
        cfp.needs_help = form.needs_help.data

        db.session.add(cfp)
        db.session.commit()

        # Send confirmation message
        msg = Message('Electromagnetic Field CFP Submission',
                      sender=app.config['CONTENT_EMAIL'],
                      recipients=[current_user.email])

        msg.body = render_template('emails/cfp-submission.txt',
                                   cfp=cfp, type=cfp_type, new_user=new_user)
        mail.send(msg)

        return redirect(url_for('.complete'))

    full_price = ProductGroup.get_price_cheapest_full()

    return render_template('cfp/main.html', full_price=full_price,
                           forms=forms, active_cfp_type=cfp_type,
                           has_errors=bool(form.errors), ignore_closed=ignore_closed)


class DiversityForm(Form):
    age = StringField('Age')
    gender = StringField('Gender')
    ethnicity = StringField('Ethnicity')


@cfp.route('/cfp/complete', methods=['GET', 'POST'])
@feature_flag('CFP')
def complete():
    if current_user.is_anonymous:
        return redirect(url_for('.main'))
    form = DiversityForm()
    if form.validate_on_submit():
        if not current_user.diversity:
            current_user.diversity = UserDiversity()
            current_user.diversity.user_id = current_user.id
            db.session.add(current_user.diversity)

        current_user.diversity.age = form.age.data
        current_user.diversity.gender = form.gender.data
        current_user.diversity.ethnicity = form.ethnicity.data

        db.session.commit()
        return redirect(url_for('.proposals'))

    return render_template('cfp/complete.html', form=form)


@cfp.route('/cfp/proposals')
@feature_flag('CFP')
def proposals():
    if current_user.is_anonymous:
        return redirect(url_for('.main'))

    proposals = current_user.proposals.all()
    if not proposals:
        return redirect(url_for('.main'))

    for proposal in proposals:
        if proposal.scheduled_venue:
            proposal.scheduled_venue_name = Venue.query.filter_by(id=proposal.scheduled_venue).one().name

    return render_template('cfp/proposals.html', proposals=proposals)


@cfp.route('/cfp/proposals/<int:proposal_id>/edit', methods=['GET', 'POST'])
@feature_flag('CFP')
def edit_proposal(proposal_id):
    if current_user.is_anonymous:
        return redirect(url_for('users.login', next=url_for('.edit_proposal',
                                                           proposal_id=proposal_id)))

    proposal = Proposal.query.get_or_404(proposal_id)
    if proposal.user != current_user:
        abort(404)

    form = TalkProposalForm() if proposal.type == 'talk' else \
           WorkshopProposalForm() if proposal.type == 'workshop' else \
           InstallationProposalForm()

    del form.name
    del form.email

    if form.validate_on_submit():
        if proposal.state not in ['new', 'edit']:
            flash('This submission can no longer be edited.')
            return redirect(url_for('.proposals'))

        app.logger.info('Proposal %s edited', proposal.id)

        if proposal.type == 'talk':
            proposal.length = form.length.data

        elif proposal.type == 'workshop':
            proposal.length = form.length.data
            proposal.attendees = form.attendees.data
            proposal.cost = form.cost.data

        elif proposal.type == 'installation':
            proposal.size = form.size.data
            proposal.funds = form.funds.data

        proposal.title = form.title.data
        proposal.description = form.description.data
        proposal.requirements = form.requirements.data
        proposal.notice_required = form.notice_required.data
        proposal.needs_help = form.needs_help.data

        db.session.commit()
        flash("Your proposal has been updated")

        return redirect(url_for('.edit_proposal', proposal_id=proposal_id))

    if request.method != 'POST' and proposal.state in ['new', 'edit']:
        if proposal.type == 'talk':
            form.length.data = proposal.length

        elif proposal.type == 'workshop':
            form.length.data = proposal.length
            form.attendees.data = proposal.attendees
            form.cost.data = proposal.cost

        elif proposal.type == 'installation':
            form.size.data = proposal.size
            form.funds.data = proposal.funds

        form.title.data = proposal.title
        form.description.data = proposal.description
        form.requirements.data = proposal.requirements
        form.notice_required.data = proposal.notice_required
        form.needs_help.data = proposal.needs_help

    if proposal.scheduled_venue:
        proposal.scheduled_venue_name = Venue.query.filter_by(id=proposal.scheduled_venue).one().name

    return render_template('cfp/edit.html', proposal=proposal, form=form)


class AcceptedForm(Form):
    name = StringField('Names for schedule', [Required()])
    title = StringField('Title', [Required()])
    description = TextAreaField('Description', [Required()])
    telephone_number = TelField('Telephone')

    may_record = BooleanField('I am happy for this to be recorded', default=True)
    needs_laptop = BooleanField('I will need to borrow a laptop for slides')
    requirements = TextAreaField('Requirements')
    arrival_period = SelectField('Estimated arrival time', default='fri pm',
                                choices=[('fri am', 'Friday am'),
                                         ('fri pm', 'Friday pm'),
                                         ('sat am', 'Saturday am'),
                                         ('sat pm', 'Saturday pm'),
                                         ('sun am', 'Sunday am'),
                                         ('sun pm', 'Sunday pm'),
                                         ])
    departure_period = SelectField('Estimated departure time', default='mon am',
                                  choices=[('fri pm', 'Friday pm'),
                                           ('sat am', 'Saturday am'),
                                           ('sat pm', 'Saturday pm'),
                                           ('sun am', 'Sunday am'),
                                           ('sun pm', 'Sunday pm'),
                                           ('mon am', 'Monday am'),
                                           ])
    _available_slots = tuple()

    def get_availability_json(self):
        res = []
        for field_name in self._available_slots:
            field = getattr(self, field_name)

            if not field.data:
                continue
            res.append(field_name)
        return ', '.join(res)

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

        arr_val = {'fri': 0, 'sat': 1, 'sun': 2}[arr_day]
        dep_val = {'fri': 0, 'sat': 1, 'sun': 2, 'mon': 3}[dep_day]

        # Arrival day is before departure day; we're done here.
        if arr_val < dep_val:
            return

        # Arrival day is after departure
        if arr_val > dep_val:
            raise ValidationError('Departure must be after arrival')

        # Arrival day is same as departure day (might be 1 day ticket)
        # so only error in case of time-travel
        if dep_time == 'am' and arr_time == 'pm':
            raise ValidationError('Departure must be after arrival')


class DaytimeAcceptedForm(AcceptedForm):
    # Availability times
    fri_13_16 = BooleanField(default=True)
    fri_16_20 = BooleanField(default=True)
    sat_10_13 = BooleanField(default=True)
    sat_13_16 = BooleanField(default=True)
    sat_16_20 = BooleanField(default=True)
    sun_10_13 = BooleanField(default=True)
    sun_13_16 = BooleanField(default=True)
    sun_16_20 = BooleanField(default=True)
    _available_slots = (             'fri_13_16', 'fri_16_20',
                        'sat_10_13', 'sat_13_16', 'sat_16_20',
                        'sun_10_13', 'sun_13_16', 'sun_16_20')


class EveningAcceptedForm(AcceptedForm):
    fri_20_22 = BooleanField(default=True)
    fri_22_24 = BooleanField(default=True)
    sat_20_22 = BooleanField(default=True)
    sat_22_24 = BooleanField(default=True)
    sun_20_22 = BooleanField(default=True)
    sun_22_24 = BooleanField(default=True)
    _available_slots = ('fri_20_22', 'fri_22_24',
                        'sat_20_22', 'sat_22_24',
                        'sun_20_22', 'sun_22_24')


@cfp.route('/cfp/proposals/<int:proposal_id>/finalise', methods=['GET', 'POST'])
@feature_flag('CFP')
@feature_flag('CFP_FINALISE')
def finalise_proposal(proposal_id):
    if current_user.is_anonymous:
        return redirect(url_for('users.login', next=url_for('.edit_proposal',
                                                           proposal_id=proposal_id)))

    proposal = Proposal.query.get_or_404(proposal_id)
    if proposal.user != current_user:
        abort(404)

    if proposal.state not in ('accepted', 'finished'):
        return redirect(url_for('.edit_proposal', proposal_id=proposal_id))

    form = DaytimeAcceptedForm() if proposal.type in ('talk', 'workshop') else \
           EveningAcceptedForm() if proposal.type == 'performance' else \
           AcceptedForm()

    if proposal.scheduled_venue:
        proposal.scheduled_venue_name = Venue.query.filter_by(id=proposal.scheduled_venue).one().name

    if form.validate_on_submit():
        proposal.published_names = form.name.data
        proposal.title = form.title.data
        proposal.description = form.description.data
        proposal.telephone_number = form.telephone_number.data

        proposal.may_record = form.may_record.data
        proposal.needs_laptop = form.needs_laptop.data
        proposal.requirements = form.requirements.data

        proposal.arrival_period = form.arrival_period.data
        proposal.departure_period = form.departure_period.data

        proposal.available_times = form.get_availability_json()
        proposal.set_state('finished')

        db.session.commit()
        app.logger.info('Finished proposal %s', proposal_id)
        flash('Thank you for finalising your details!')

        return redirect(url_for('.edit_proposal', proposal_id=proposal_id))


    else:
        if proposal.published_names:
            form.name.data = proposal.published_names
        else:
            form.name.data = current_user.name

        form.title.data = proposal.title
        form.description.data = proposal.description
        form.telephone_number.data = proposal.telephone_number

        form.may_record.data = proposal.may_record
        form.needs_laptop.data = proposal.needs_laptop
        form.requirements.data = proposal.requirements

        form.arrival_period.data = proposal.arrival_period
        form.departure_period.data = proposal.departure_period

        if proposal.available_times:
            form.set_from_availability_json(proposal.available_times)

    return render_template('cfp/accepted.html', form=form, proposal=proposal)


class MessagesForm(Form):
    message = TextAreaField('Message')
    send = SubmitField('Send Message')
    mark_read = SubmitField('Mark all messages as read')


@cfp.route('/cfp/proposals/<int:proposal_id>/messages', methods=['GET', 'POST'])
@feature_flag('CFP')
def proposal_messages(proposal_id):
    if current_user.is_anonymous:
        return redirect(url_for('users.login', next=url_for('.proposal_messages',
                                                           proposal_id=proposal_id)))
    proposal = Proposal.query.get_or_404(proposal_id)
    if proposal.user_id != current_user.id:
        abort(404)

    form = MessagesForm()

    if request.method == 'POST':
        if form.send.data and form.message.data:
            msg = CFPMessage()
            msg.is_to_admin = True
            msg.from_user_id = current_user.id
            msg.proposal_id = proposal_id
            msg.message = form.message.data

            db.session.add(msg)
            db.session.commit()

        if form.mark_read or form.send.data:
            count = proposal.mark_messages_read(current_user)
            app.logger.info('Marked %s messages to admin on proposal %s as read' % (count, proposal.id))

        return redirect(url_for('.proposal_messages', proposal_id=proposal_id))

    messages = CFPMessage.query.filter_by(
        proposal_id=proposal_id
    ).order_by('created').all()

    return render_template('cfp/messages.html',
                           proposal=proposal, messages=messages, form=form)

@cfp.route('/cfp/messages')
@feature_flag('CFP')
def all_messages():
    if current_user.is_anonymous:
        return redirect(url_for('.main'))

    proposal_with_message = Proposal.query\
        .join(CFPMessage)\
        .filter(Proposal.id == CFPMessage.proposal_id,
                Proposal.user_id == current_user.id)\
        .order_by(CFPMessage.has_been_read, CFPMessage.created.desc())\
        .all()

    proposal_with_message.sort(key=lambda x: (x.get_unread_count(current_user) > 0,
                                              x.created), reverse=True)

    return render_template('cfp/all_messages.html',
                           proposal_with_message=proposal_with_message)

@cfp.route('/cfp/guidance')
def guidance():
    return render_template('cfp/guidance.html')
