# encoding=utf-8

from flask import (
    redirect, url_for, request, abort, render_template,
    flash, Blueprint, current_app as app
)
from flask.ext.login import current_user

from sqlalchemy import or_

from wtforms import (
    SubmitField, StringField, FieldList, FormField, SelectField, TextAreaField
)
from wtforms.validators import Required

from main import db
from .common import require_permission, send_template_email

from models.cfp import Proposal, ProposalCategory, CFPMessage, CFP_STATES
from .common.forms import Form, HiddenIntegerField

cfp_review = Blueprint('cfp_review', __name__)
admin_required = require_permission('admin')  # Decorator to require admin permissions
anon_required = require_permission('cfp_anonymiser')
review_required = require_permission('cfp_reviewer')

@cfp_review.context_processor
def cfp_review_variables():
    unread_count = CFPMessage.query.filter(
        # is_to_admin AND (has_been_read IS null OR has_been_read IS false)
        or_(CFPMessage.has_been_read.is_(False),
            CFPMessage.has_been_read.is_(None)),
        CFPMessage.is_to_admin.is_(True)
    ).count()

    proposal_counts = {state: Proposal.query.filter_by(state=state).count()
                                                        for state in CFP_STATES}

    return {
        'unread_count': unread_count,
        'proposal_counts': proposal_counts,
        'view_name': request.url_rule.endpoint.replace('cfp_review.', '.')
    }

@cfp_review.route('')
def main():
    if current_user.has_permission('admin'):
        return redirect(url_for('.proposals'))

    if current_user.has_permission('cfp_anonymiser'):
        return redirect(url_for('.anonymisation'))

    if current_user.has_permission('cfp_reviewer'):
        return redirect(url_for('.review'))

    abort(404)

class CategoryForm(Form):
    id = HiddenIntegerField('Category Id', [Required()])
    name = StringField('Category Name', [Required()])


class AllCategoriesForm(Form):
    categories = FieldList(FormField(CategoryForm))
    name = StringField('New Category Name')
    update = SubmitField('Update Categories')


@cfp_review.route('/categories', methods=['GET', 'POST'])
@admin_required
def categories():
    categories = {c.id: c for c in ProposalCategory.query.all()}
    counts = {c.id: len(c.proposals) for c in categories.values()}
    form = AllCategoriesForm()

    if form.validate_on_submit():
        for cat in form.categories:
            cat_id = int(cat['id'].data)
            categories[cat_id].name = cat['name'].data
        db.session.commit()

        if len(form.name.data) > 0:
            app.logger.info('%s adding new category %s', current_user.name, form.name.data)
            new_category = ProposalCategory()
            new_category.name = form.name.data

            db.session.add(new_category)
            db.session.commit()
            # import ipdb; ipdb.set_trace()
            categories[new_category.id] = new_category
            counts[new_category.id] = 0
            form.name.data = ''

    for old_field in range(len(form.categories)):
        form.categories.pop_entry()

    for cat in sorted(categories.values(), key=lambda x: x.name):
        form.categories.append_entry()
        form.categories[-1]['id'].data = cat.id
        form.categories[-1]['name'].data = cat.name

    return render_template('cfp_review/categories.html', form=form, counts=counts)


def convert_category_id(val):
    if val is None:
        return None

    if hasattr(val, 'lower') and val.lower() == 'null':
        return None

    return int(val)


def build_query_dict(parameters):
    res = {}
    fields = [('type', str), ('category_id', convert_category_id),
              ('state', str), ('needs_help', bool), ('needs_money', bool)]

    for (field_name, field_type) in fields:
        # if this can't convert to the correct type it will return None
        val = parameters.get(field_name, None)

        if val is not None:
            try:
                val = field_type(val)
            except ValueError:
                flash('Invalid parameter value (%r) for parameter %s' % (val, field_name))
                continue
            res[field_name] = val

    return res


@cfp_review.route('/proposals')
@admin_required
def proposals():
    if current_user.has_permission('cfp_reviewer', False):
        # Prevent CfP reviewers from viewing non-anonymised submissions
        return abort(403)

    query_dict = build_query_dict(request.args)

    proposals = Proposal.query.filter_by(**query_dict)\
                              .order_by('state', 'modified', 'id').all()

    return render_template('cfp_review/proposals.html', proposals=proposals,
                           link_target='.update_proposal')


class CheckProposalForm(Form):
    category = SelectField('Category', default=-1, coerce=int, choices=[(-1, '--None--')])
    reject = SubmitField('Reject')
    checked = SubmitField('Send for Anonymisation')


@cfp_review.route('/proposals/<int:proposal_id>', methods=['GET', 'POST'])
@admin_required
def update_proposal(proposal_id):
    if current_user.has_permission('cfp_reviewer', False):
        # Prevent CfP reviewers from viewing non-anonymised submissions
        return abort(403)

    form = CheckProposalForm()
    categories = [(c.id, c.name) for c in ProposalCategory.query.all()]
    form.category.choices.extend(categories)

    prop = Proposal.query.get(proposal_id)

    next_prop = Proposal.query.filter(
        Proposal.id != prop.id,
        Proposal.state == prop.state,
        Proposal.modified >= prop.modified # ie find something after this one
    ).order_by('modified', 'id').first()

    if form.validate_on_submit():
        if form.reject.data:
            app.logger.info('Rejecting proposal %s', proposal_id)
            prop.set_state('rejected')

        elif form.checked.data:
            if prop.type == 'talk' and form.category.data == -1:
                form.category.errors.append('Required')
                return render_template('cfp_review/update_proposal.html',
                                        proposal=prop, form=form,
                                        next_proposal=next_prop)

            elif prop.type == 'talk':
                prop.category_id = form.category.data

            app.logger.info('Sending proposal %s for anonymisation', proposal_id)
            prop.set_state('checked')

        db.session.commit()

    if prop.type == 'talk' and prop.category_id:
        form.category.data = prop.category_id

    return render_template('cfp_review/update_proposal.html',
                            proposal=prop, form=form, next_proposal=next_prop)


@cfp_review.route('/messages')
@admin_required
def all_messages():
    # FIXME this is probably not needed as admin should never be reviewers
    if current_user.has_permission('cfp_reviewer', False):
        # Prevent CfP reviewers from viewing non-anonymised submissions
        return abort(403)

    # TODO add search
    # Query from the proposal because that's actually what we display
    proposal_with_message = Proposal.query\
        .join(CFPMessage)\
        .filter(Proposal.id == CFPMessage.proposal_id)\
        .order_by(CFPMessage.has_been_read, CFPMessage.created.desc())\
        .all()

    proposal_with_message.sort(key=lambda x: (x.get_unread_count(current_user) > 0,
                                              x.created), reverse=True)

    return render_template('cfp_review/all_messages.html',
                           proposal_with_message=proposal_with_message)


class SendMessageForm(Form):
    message = TextAreaField('New Message')
    send = SubmitField('Send Message')
    mark_read = SubmitField('Mark all as read')


@cfp_review.route('/proposals/<int:proposal_id>/message', methods=['GET', 'POST'])
@admin_required
def message_proposer(proposal_id):
    # FIXME this is probably not needed as admin should never be reviewers
    if current_user.has_permission('cfp_reviewer', False):
        # Prevent CfP reviewers from viewing non-anonymised submissions
        return abort(403)

    form = SendMessageForm()
    proposal = Proposal.query.get(proposal_id)

    if request.method == 'POST' and form.send.data and form.message.data:
        msg = CFPMessage()
        msg.is_to_admin = False
        msg.from_user_id = current_user.id
        msg.proposal_id = proposal_id
        msg.message = form.message.data

        db.session.add(msg)
        db.session.commit()

        app.logger.info('Sending message from %s to %s', current_user.id, proposal.user_id)

        send_template_email('New message about your EMF proposal',
                            proposal.user.email, app.config['CONTENT_EMAIL'],
                            'cfp_review/email/new_message.txt', url=url_for('.anonymisation'),
                            to_user=proposal.user, from_user=current_user,
                            proposal=proposal)

        # Unset the text field
        form.message.data = ''

    should_mark_read = form.mark_read.data or form.send.data
    if request.method == 'POST' and should_mark_read:
        count = proposal.mark_messages_read(current_user)
        app.logger.info('Marked %d messages to admin on proposal %d as read' % (count, proposal.id))

    # Admin can see all messages sent in relation to a proposal
    messages = CFPMessage.query.filter_by(
        proposal_id=proposal_id
    ).order_by('created').all()

    return render_template('cfp_review/message_proposer.html',
                           form=form, messages=messages, proposal=proposal)


@cfp_review.route('/anonymisation')
@anon_required
def anonymisation():
    if current_user.has_permission('cfp_reviewer', False):
        # Prevent CfP reviewers from viewing non-anonymised submissions
        return abort(403)

    proposals = Proposal.query.filter_by(state='checked').order_by('modified', 'id').all()

    return render_template('cfp_review/proposals.html', proposals=proposals,
                           link_target='.anonymise_proposal')


class AnonymiseProposalForm(Form):
    title = StringField('Title', [Required()])
    description = TextAreaField('Description', [Required()])
    anonymise = SubmitField('Send to review and go to next')
    reject = SubmitField('I cannot anonymise this proposal')


@cfp_review.route('/anonymisation/<int:proposal_id>', methods=['GET', 'POST'])
@anon_required
def anonymise_proposal(proposal_id):
    if current_user.has_permission('cfp_reviewer', False):
        # Prevent CfP reviewers from viewing non-anonymised submissions
        return abort(403)

    form = AnonymiseProposalForm()

    prop = Proposal.query.get(proposal_id)
    next_prop = Proposal.query.filter(
        Proposal.id != prop.id,
        Proposal.state == 'checked',
        Proposal.modified >= prop.modified
    ).order_by('modified', 'id').first()

    if form.validate_on_submit():
        if form.reject.data:
            prop.set_state('anon-blocked')
            db.session.commit()
            app.logger.info('Proposal %s cannot be anonymised', proposal_id)

        if form.anonymise.data:
            prop.title = form.title.data
            prop.description = form.description.data
            prop.set_state('anonymised')
            db.session.commit()
            app.logger.info('Sending proposal %s for review', proposal_id)

        if not next_prop:
            return redirect(url_for('.anonymisation'))
        return redirect(url_for('.anonymise_proposal', proposal_id=next_prop.id))


    form.title.data = prop.title
    form.description.data = prop.description

    return render_template('cfp_review/anonymise_proposal.html',
                           proposal=prop, form=form, next_proposal=next_prop)


@cfp_review.route('/review')
@review_required
def review():
    return 'hello review-world'
