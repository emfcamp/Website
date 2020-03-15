from flask import redirect, url_for, request, render_template, current_app as app, abort
from flask_login import current_user
from models.cfp import Proposal

from main import db
from . import (
    cfp_review,
    anon_required,
    get_proposal_sort_dict,
    get_next_proposal_to,
    get_permission_namespace,
)
from .forms import AnonymiseProposalForm


@cfp_review.route("/anonymisation")
@anon_required
def anonymisation():
    type_ns = get_permission_namespace(current_user, "cfp_anonymiser")

    if type_ns:
        proposals = Proposal.query.filter_by(state="checked", type=type_ns).all()
    else:
        proposals = Proposal.query.filter_by(state="checked").all()

    sort_dict = get_proposal_sort_dict(request.args)
    proposals.sort(**sort_dict)

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
    type_ns = get_permission_namespace(current_user, "cfp_anonymiser")
    prop = Proposal.query.get_or_404(proposal_id)
    if prop.state != "checked" or (type_ns and type_ns != prop.type):
        # Make sure people only see proposals that are ready
        return abort(404)

    next_prop = get_next_proposal_to(prop, "checked", type_ns)
    form = AnonymiseProposalForm()

    if prop.state == "checked" and form.validate_on_submit():
        if form.reject.data:
            prop.set_state("anon-blocked")
            prop.anonymiser_id = current_user.id
            db.session.commit()
            app.logger.info("Proposal %s cannot be anonymised", proposal_id)

        if form.anonymise.data:
            prop.title = form.title.data
            prop.description = form.description.data
            prop.set_state("anonymised")
            prop.anonymiser_id = current_user.id
            db.session.commit()
            app.logger.info("Sending proposal %s for review", proposal_id)

        if not next_prop:
            return redirect(url_for(".anonymisation"))
        return redirect(url_for(".anonymise_proposal", proposal_id=next_prop.id))

    form.title.data = prop.title
    form.description.data = prop.description

    return render_template(
        "cfp_review/anonymise_proposal.html",
        proposal=prop,
        form=form,
        next_proposal=next_prop,
    )
