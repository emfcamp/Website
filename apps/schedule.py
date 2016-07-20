# encoding=utf-8
from flask import (
    render_template, Blueprint, redirect, url_for, request, flash
)
from flask.ext.login import current_user

from main import db

from .common import feature_flag
from .common.forms import Form
from models.cfp import Proposal

schedule = Blueprint('schedule', __name__)

@schedule.route('/line-up')
@feature_flag('SCHEDULE')
def line_up():
    proposals = Proposal.query.filter_by(state='finished').all()

    return render_template('schedule/line-up.html', proposals=proposals)

class FavouriteProposalForm(Form):
    pass

@schedule.route('/line-up/<int:proposal_id>', methods=['GET', 'POST'])
@feature_flag('SCHEDULE')
def line_up_proposal(proposal_id):
    proposal = Proposal.query.get_or_404(proposal_id)
    form = FavouriteProposalForm()

    if not current_user.is_anonymous():
        is_fave = proposal in current_user.favourites
    else:
        is_fave = False

    # Use the form for CSRF token but explicitly check for post requests as
    # an empty form is always valid
    if (request.method == "POST") and not current_user.is_anonymous():
        if is_fave:
            current_user.favourites.remove(proposal)
            msg = 'Removed "%s" from favourites' % proposal.title
        else:
            current_user.favourites.append(proposal)
            msg = 'Added "%s" to favourites' % proposal.title
        db.session.commit()
        flash(msg)
        return redirect(url_for('.line_up_proposal', proposal_id=proposal.id))

    return render_template('schedule/line-up-proposal.html', form=form,
                           proposal=proposal, is_fave=is_fave)
