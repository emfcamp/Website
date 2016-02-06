# encoding=utf-8

from flask import (
    redirect, url_for, request, abort, render_template, flash,
    Blueprint, current_app as app
)
from flask.ext.login import current_user

from wtforms import SubmitField, StringField, FieldList, FormField, SelectField
from wtforms.validators import Required

from main import db
from .common import require_permission

cfp_review = Blueprint('cfp_review', __name__)
admin_required = require_permission('admin')  # Decorator to require admin permissions


from models.cfp import Proposal, ProposalCategory
from .common.forms import Form, HiddenIntegerField

@cfp_review.context_processor
def cfp_review_variables():
    return {
        'view_name': request.url_rule.endpoint.replace('cfp_review.', '.')
    }

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

    proposals = Proposal.query.filter_by(**query_dict).all()

    return render_template('cfp_review/proposals.html', proposals=proposals)


class UpdateProposalForm(Form):
    category = SelectField('Category', default=-1, coerce=int,
                           choices=[(-1, '--None--')])
    reject = SubmitField('Reject')
    anonymise = SubmitField('Anonymise')


@cfp_review.route('/proposals/<int:proposal_id>', methods=['GET', 'POST'])
@admin_required
def update_proposal(proposal_id):
    if current_user.has_permission('cfp_reviewer', False):
        # Prevent CfP reviewers from viewing non-anonymised submissions
        return abort(403)

    form = UpdateProposalForm()
    categories = [(c.id, c.name) for c in ProposalCategory.query.all()]
    form.category.choices.extend(categories)

    proposal = Proposal.query.get(proposal_id)

    if form.validate_on_submit():
        if form.reject.data:
            app.logger.info('Rejecting proposal %s', proposal_id)
            proposal.set_state('rejected')

        elif form.anonymise.data:
            if proposal.type == 'talk' and form.category.data == -1:
                form.category.errors.append('Required')
                return render_template('cfp_review/update_proposal.html',
                                        proposal=proposal, form=form)

            elif proposal.type == 'talk':
                proposal.category_id = form.category.data

            app.logger.info('Sending proposal %s for anonymisation', proposal_id)
            proposal.set_state('checked')

        db.session.commit()
        return redirect(url_for('.proposals'))

    if proposal.type == 'talk' and proposal.category_id:
        form.category.data = proposal.category_id

    return render_template('cfp_review/update_proposal.html',
                            proposal=proposal, form=form)
