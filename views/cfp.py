from main import app, db, mail
from views import Form, feature_flag
from models.ticket import TicketType
from models.cfp import (
    TalkProposal, WorkshopProposal,
    InstallationProposal, ProposalDiversity,
)

from flask import (
    render_template, redirect, request,
    url_for, abort,
)
from flask.ext.login import current_user
from flask_mail import Message

from wtforms.validators import Required, Email
from wtforms import (
    BooleanField, StringField,
    FormField, TextAreaField, SelectField,
)

class DiversityForm(Form):
    age = StringField('Age')
    gender = StringField('Gender')
    ethnicity = StringField('Ethnicity')

class ProposalForm(Form):
    name = StringField("Name", [Required()])
    email = StringField("Email", [Email(), Required()])
    title = StringField("Title", [Required()])
    description = TextAreaField("Description", [Required()])
    # days = SelectMultipleField("I can only attend on some days",
    #                            choices=[('fri', 'Friday'),
    #                                     ('sat', 'Saturday'),
    #                                     ('sun', 'Sunday'),
    #                                     ])
    need_finance = BooleanField("I can't afford to buy a ticket without financial support")

    diversity = FormField(DiversityForm)

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


@app.route('/cfp')
@app.route('/cfp/<string:cfp_type>', methods=['GET', 'POST'])
@feature_flag('CFP')
def cfp(cfp_type='talk'):
    if cfp_type not in ['talk', 'workshop', 'installation']:
        abort(404)

    forms = [TalkProposalForm(), WorkshopProposalForm(), InstallationProposalForm()]
    (form,) = [f for f in forms if f.type == cfp_type]

    if request.method == 'POST':
        app.logger.info('Checking %s proposal for %s (%s)', cfp_type, form.name.data, form.email.data)

    if form.validate_on_submit():
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

        cfp.name = form.name.data
        cfp.email = form.email.data
        cfp.title = form.title.data
        cfp.description = form.description.data
        cfp.need_finance = form.need_finance.data

        cfp.diversity = ProposalDiversity()
        cfp.diversity.age = form.diversity.age.data
        cfp.diversity.gender = form.diversity.gender.data
        cfp.diversity.ethnicity = form.diversity.ethnicity.data

        db.session.add(cfp)
        db.session.commit()

        # Send confirmation message
        msg = Message('Electromagnetic Field CFP Submission',
                     sender=app.config['CONTENT_EMAIL'],
                     recipients=[cfp.email])

        msg.body = render_template('emails/cfp-submission.txt', cfp=cfp, type=cfp_type)
        mail.send(msg)

        return redirect(url_for('cfp_complete'))

    if current_user.is_authenticated():
        form.name.data = current_user.name
        form.email.data = current_user.email

    full_price = TicketType.query.get('full').get_price('GBP')

    return render_template('cfp.html', full_price=full_price,
        forms=forms, active_cfp_type=cfp_type, has_errors=bool(form.errors))

@app.route('/cfp/complete')
@feature_flag('CFP')
def cfp_complete():
    return render_template('cfp_complete.html')

