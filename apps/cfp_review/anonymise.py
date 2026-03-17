from flask import redirect, url_for, request, render_template, current_app as app, abort
from flask_login import current_user
from models.cfp import Proposal

from main import db, get_or_404
from . import cfp_review, anon_required, sort_proposals, get_next_proposal_to
from .forms import AnonymiseProposalForm


@cfp_review.route("/anonymisation")
@anon_required
def anonymisation():
    proposals = Proposal.query.filter_by(state="checked").all()

    sort_proposals(proposals)

    non_sort_query_string = dict(request.args)
    if "sort_by" in non_sort_query_string:
        del non_sort_query_string["sort_by"]

    if "reverse" in non_sort_query_string:
        del non_sort_query_string["reverse"]

    return render_template(
        "cfp_review/anonymise_list.html",
        proposals=proposals,
        new_qs=non_sort_query_string,
    )


@cfp_review.route("/anonymisation/<int:proposal_id>", methods=["GET", "POST"])
@anon_required
def anonymise_proposal(proposal_id):
    proposal = get_or_404(db, Proposal, proposal_id)
    if proposal.state in ["new", "edit"]:
        # Make sure people only see proposals that are ready
        return abort(404)

    next_proposal = get_next_proposal_to(proposal, "checked")
    form = AnonymiseProposalForm()

    if proposal.state == "checked" and form.validate_on_submit():
        if form.reject.data:
            proposal.state = "anon-blocked"
            proposal.anonymiser_id = current_user.id
            db.session.commit()
            app.logger.info("Proposal %s cannot be anonymised", proposal_id)

        if form.anonymise.data:
            proposal.title = form.title.data
            proposal.description = form.description.data
            proposal.state = "anonymised"
            proposal.anonymiser_id = current_user.id
            db.session.commit()
            app.logger.info("Sending proposal %s for review", proposal_id)

        if not next_proposal:
            return redirect(url_for(".anonymisation"))
        return redirect(url_for(".anonymise_proposal", proposal_id=next_proposal.id))

    form.title.data = proposal.title
    form.description.data = proposal.description

    return render_template(
        "cfp_review/anonymise_proposal.html",
        proposal=proposal,
        form=form,
        next_proposal=next_proposal,
    )
