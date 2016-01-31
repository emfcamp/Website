# encoding=utf-8

from flask import (
    abort, render_template, Blueprint, current_app as app
)
from flask.ext.login import current_user

from wtforms import SubmitField, StringField, FieldList, FormField
from wtforms.validators import Required

from main import db
from .common import require_permission

cfp_review = Blueprint('cfp_review', __name__)
admin_required = require_permission('admin')  # Decorator to require admin permissions


from models.cfp import Proposal, TalkCategory
from .common.forms import Form, HiddenIntegerField

class CategoryForm(Form):
    id = HiddenIntegerField('Category Id', [Required()])
    name = StringField('Category Name', [Required()])


class AllCategoriesForm(Form):
    categories = FieldList(FormField(CategoryForm))
    name = StringField('New Category Name')
    update = SubmitField('Update flags')


@cfp_review.route('/admin/cfp-categories', methods=['GET', 'POST'])
@admin_required
def cfp_categories():
    categories = {c.id: c for c in TalkCategory.query.all()}
    counts = {c.id: len(c.proposals) for c in categories.values()}
    form = AllCategoriesForm()

    if form.validate_on_submit():
        for cat in form.categories:
            cat_id = int(cat['id'].data)
            categories[cat_id].name = cat['name'].data
        db.session.commit()

        if len(form.name.data) > 0:
            app.logger.info('%s adding new category %s', current_user.name, form.name.data)
            new_category = TalkCategory()
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

    return render_template('cfp_review/cfp-categories.html', form=form, counts=counts)


@cfp_review.route('/admin/cfp-proposals', methods=['GET', 'POST'])
@admin_required
def cfp_proposals():
    if current_user.has_permission('cfp_reviewer', False):
        # Prevent CfP reviewers from viewing non-anonymised submissions
        return abort(403)

    proposals = Proposal.query.all()
    return render_template('cfp_review/cfp-proposals.html', proposals=proposals)
