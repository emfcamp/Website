from flask import (
    render_template, redirect, request, flash,
    url_for, abort, current_app as app, Blueprint
)
from flask.ext.login import current_user
from flask_mail import Message
from wtforms.validators import Required, Email, ValidationError
from wtforms import (
    BooleanField, StringField,
    FormField, TextAreaField, SelectField,
)

from sqlalchemy.exc import IntegrityError

from main import db, mail
from models.user import User, UserDiversity
from models.ticket import TicketType
from models.cfp import TalkProposal, WorkshopProposal, InstallationProposal
from .common import feature_flag, create_current_user
from .common.forms import Form

cfp = Blueprint('cfp', __name__)


class DiversityForm(Form):
    age = StringField('Age')
    gender = StringField('Gender')
    ethnicity = StringField('Ethnicity')


class ProposalForm(Form):
    name = StringField("Name", [Required()])
    email = StringField("Email", [Email(), Required()])
    title = StringField("Title", [Required()])
    description = TextAreaField("Description", [Required()])
    need_finance = BooleanField("I can't afford to buy a ticket without financial support")

    diversity = FormField(DiversityForm)

    def validate_email(form, field):
        if current_user.is_anonymous() and User.does_user_exist(field.data):
            field.was_duplicate = True
            raise ValidationError('Account already exists')


class TalkProposalForm(ProposalForm):
    type = 'talk'
    length = SelectField("Duration", default='30',
                         choices=[('< 10 mins', "Shorter than 10 minutes"),
                                  ('10 mins', "10 minutes"),
                                  ('30 mins', "30 minutes"),
                                  ('45 mins', "45 minutes"),
                                  ('> 45 mins', "Longer than 45 minutes"),
                                  ])
    experience = SelectField("Have you given a talk before?",
                             choices=[('none', "It's my first time"),
                                      ('some', "I've talked before"),
                                      ('repeat', "I've given this talk before"),
                                      ])
    one_day = BooleanField("I can only attend for the day I give my talk")


class WorkshopProposalForm(ProposalForm):
    type = 'workshop'
    length = StringField("Duration", [Required()])
    attendees = StringField("Attendees", [Required()])
    one_day = BooleanField("I can only attend for the day I give my workshop")


class InstallationProposalForm(ProposalForm):
    type = 'installation'
    size = StringField("Physical size", [Required()])


@cfp.route('/cfp')
@cfp.route('/cfp/<string:cfp_type>', methods=['GET', 'POST'])
@feature_flag('CFP')
def main(cfp_type='talk'):
    if cfp_type not in ['talk', 'workshop', 'installation']:
        abort(404)

    forms = [TalkProposalForm(), WorkshopProposalForm(), InstallationProposalForm()]
    (form,) = [f for f in forms if f.type == cfp_type]

    # If the user is already logged in set their name & email for the form
    if current_user.is_authenticated():
        form.name.data = current_user.name
        form.email.data = current_user.email

    if request.method == 'POST':
        app.logger.info('Checking %s proposal for %s (%s)', cfp_type,
                        form.name.data, form.email.data)

    if form.validate_on_submit():
        new_user = False
        if current_user.is_anonymous():
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
            cfp.experience = form.experience.data
            cfp.one_day = form.one_day.data
        elif cfp_type == 'workshop':
            cfp = WorkshopProposal()
            cfp.length = form.length.data
            cfp.attendees = form.attendees.data
            cfp.one_day = form.one_day.data
        elif cfp_type == 'installation':
            cfp = InstallationProposal()
            cfp.size = form.size.data

        cfp.user_id = current_user.id

        cfp.title = form.title.data
        cfp.description = form.description.data
        cfp.need_finance = form.need_finance.data

        db.session.add(cfp)
        db.session.commit()

        if not current_user.diversity and any(form.diversity.data.values()):
            diversity = UserDiversity()
            diversity.age = form.diversity.age.data
            diversity.gender = form.diversity.gender.data
            diversity.user_id = current_user.id
            diversity.ethnicity = form.diversity.ethnicity.data

            db.session.add(diversity)
            db.session.commit()

        # Send confirmation message
        msg = Message('Electromagnetic Field CFP Submission',
                      sender=app.config['CONTENT_EMAIL'],
                      recipients=[current_user.email])

        msg.body = render_template('emails/cfp-submission.txt',
                                   cfp=cfp, type=cfp_type, new_user=new_user)
        mail.send(msg)

        return redirect(url_for('.complete'))

    full_price = TicketType.get_price_cheapest_full()

    return render_template('cfp.html', full_price=full_price,
                           forms=forms, active_cfp_type=cfp_type,
                           has_errors=bool(form.errors))


@cfp.route('/cfp/complete')
@feature_flag('CFP')
def complete():
    return render_template('cfp_complete.html')


@cfp.route('/cfp/proposals')
@feature_flag('CFP')
def proposals():
    if current_user.is_anonymous():
        return redirect(url_for('.main'))

    proposals = current_user.proposals.all()
    if not proposals:
        return redirect(url_for('.main'))

    return render_template('cfp_proposals.html', proposals=proposals)
