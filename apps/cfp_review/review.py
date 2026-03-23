import random
from datetime import timedelta

from flask import current_app as app
from flask import flash, redirect, render_template, session, url_for
from flask_login import current_user
from sqlalchemy import select
from sqlalchemy.orm import aliased
from sqlalchemy_continuum.utils import transaction_class, version_class

from main import db, get_or_404
from models import naive_utcnow
from models.cfp import Proposal, ProposalVote, StateTransitionException

from . import cfp_review, review_required
from .forms import ReviewListForm, VoteForm


@cfp_review.route("/review", methods=["GET", "POST"])
@review_required
def review_list():
    form = ReviewListForm()

    if form.validate_on_submit():
        app.logger.info("Clearing review order")
        session["review_order"] = None
        session["review_order_dt"] = naive_utcnow()
        return redirect(url_for(".review_list"))

    review_order_dt = session.get("review_order_dt")
    if review_order_dt:
        review_order_dt = review_order_dt.replace(tzinfo=None)

    last_visit = session.get("review_visit_dt")
    if not last_visit:
        # Make a guess from the last vote they placed
        ProposalVoteVersion = version_class(ProposalVote)
        Transaction = transaction_class(ProposalVote)
        last_vote_time = db.session.scalar(
            select(Transaction.issued_at)
            .join(ProposalVoteVersion.transaction)
            .where(Transaction.user == current_user)
            .order_by(Transaction.issued_at.desc())
        )

        if last_vote_time:
            last_visit = last_vote_time
            review_order_dt = last_vote_time
    else:
        last_visit = last_visit.replace(tzinfo=None)

    proposal_query = Proposal.query.filter(Proposal.state == "anonymised")

    if not current_user.has_permission("cfp_admin"):
        # reviewers shouldn't see their own proposals, and don't review installations
        # youth workshops are reviewed separately
        proposal_query = proposal_query.filter(
            Proposal.user_id != current_user.id, Proposal.type.in_(["talk", "workshop"])
        )

    to_review_again = []
    to_review_new = []
    to_review_old = []
    reviewed = []

    user_votes = aliased(ProposalVote, ProposalVote.query.filter_by(user_id=current_user.id).subquery())

    for proposal, vote in proposal_query.outerjoin(user_votes).with_entities(Proposal, user_votes).all():
        proposal.user_vote = vote
        if vote:
            if vote.state in ["new", "resolved", "stale"]:
                proposal.is_new = True
                to_review_again.append(proposal)
            else:
                reviewed.append(((vote.state, vote.vote or 0, vote.modified), proposal))
        else:
            # modified doesn't really describe when proposals are "new", but it's near enough
            if last_visit is None or review_order_dt is None or proposal.modified < review_order_dt:
                to_review_old.append(proposal)
            else:
                proposal.is_new = True
                to_review_new.append(proposal)

    reviewed = [p for o, p in sorted(reviewed, reverse=True)]

    review_order = session.get("review_order")
    if (
        review_order is None
        or not set([p.id for p in to_review_again]).issubset(review_order)
        or (to_review_new and (last_visit is None or naive_utcnow() - last_visit > timedelta(hours=1)))
    ):
        random.shuffle(to_review_again)
        random.shuffle(to_review_new)
        random.shuffle(to_review_old)

        to_review_max = 30

        # prioritise showing proposals that have been voted on before
        # after that, split new and old proportionally for fairness
        to_review = to_review_again[:]
        other_max = max(0, to_review_max - len(to_review))
        other_count = len(to_review_old) + len(to_review_new)
        if other_count:
            old_max = int(float(len(to_review_old)) / other_count * other_max)
            new_max = other_max - old_max
            to_review += to_review_new[:new_max] + to_review_old[:old_max]

        session["review_order"] = [p.id for p in to_review]
        session["review_order_dt"] = last_visit
        session["review_visit_dt"] = naive_utcnow()

    else:
        # Sort proposals based on the previous review order
        to_review_dict = dict((p.id, p) for p in to_review_again + to_review_new + to_review_old)
        to_review = [to_review_dict[i] for i in session["review_order"] if i in to_review_dict]

        session["review_visit_dt"] = naive_utcnow()

    return render_template("cfp_review/review_list.html", to_review=to_review, reviewed=reviewed, form=form)


def can_review_proposal(proposal):
    if proposal.state != "anonymised":
        return False

    if current_user.has_permission("cfp_admin"):
        return True

    if proposal.user == current_user:
        return False

    if proposal.type == "installation":
        # Only admins can review installations currently
        return False

    return True


def get_next_review_proposal(proposal_id):
    review_order = session.get("review_order")
    if proposal_id not in review_order:
        return None

    for i in review_order[review_order.index(proposal_id) + 1 :]:
        proposal = Proposal.query.get(i)
        if can_review_proposal(proposal):
            return i

    return None


@cfp_review.route("/review/<int:proposal_id>/next")
@review_required
def review_proposal_next(proposal_id):
    next_proposal_id = get_next_review_proposal(proposal_id)
    if next_proposal_id is None:
        return redirect(url_for(".review_list"))

    return redirect(url_for(".review_proposal", proposal_id=next_proposal_id))


@cfp_review.route("/review/<int:proposal_id>", methods=["GET", "POST"])
@review_required
def review_proposal(proposal_id):
    prop = get_or_404(db, Proposal, proposal_id)

    if not can_review_proposal(prop):
        app.logger.warning("Cannot review proposal %s", proposal_id)
        flash(f"Cannot review proposal {proposal_id}, continuing to next proposal")
        return redirect(url_for(".review_proposal_next", proposal_id=proposal_id))

    session["review_visit_dt"] = naive_utcnow()

    next_proposal_id = get_next_review_proposal(proposal_id)
    if next_proposal_id is not None:
        review_order = session.get("review_order")
        remaining = len(review_order) - review_order.index(next_proposal_id)
    else:
        remaining = 0

    form = VoteForm()

    vote = db.session.scalar(select(ProposalVote).filter_by(proposal_id=prop.id, user_id=current_user.id))

    if form.validate_on_submit():
        # Make a new vote if need-be
        if not vote:
            vote = ProposalVote(current_user, prop)
            db.session.add(vote)

        # If there's a note add it (will replace the old one but it's versioned)
        if form.note.data:
            vote.note = form.note.data
            vote.has_been_read = False
        else:
            vote.note = None
            vote.has_been_read = True

        vote_value = (
            2 if form.vote_excellent.data else 1 if form.vote_ok.data else 0 if form.vote_poor.data else None
        )

        try:
            # Update vote state
            message = "error"
            if vote_value is not None:
                vote.vote = vote_value
                vote.set_state("voted")

                message = "You voted: " + (["Poor", "OK", "Excellent"][vote_value])

            elif form.recuse.data:
                vote.set_state("recused")
                message = "You declared a conflict of interest"

            elif form.block.data:
                vote.set_state("blocked")
                message = "You marked the proposal as blocked"

            elif form.change.data:
                vote.set_state("resolved")
                message = "Proposal re-opened for review"

            flash(message, "info")
            db.session.commit()
            if next_proposal_id is None:
                return redirect(url_for(".review_list"))
            return redirect(url_for(".review_proposal", proposal_id=next_proposal_id))

        except StateTransitionException as e:
            app.logger.warning("Cannot set state: %s", e)
            flash(f"Your vote could not be updated: {e}")
            return redirect(url_for(".review_proposal", proposal_id=proposal_id))

    if vote and vote.note:
        form.note.data = vote.note
    return render_template(
        "cfp_review/review_proposal.html",
        form=form,
        proposal=prop,
        previous_vote=vote,
        remaining=remaining,
    )
