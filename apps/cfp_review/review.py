import random
from datetime import datetime, timedelta
from typing import Any

from datetype import NaiveDateTime, naive
from flask import current_app as app
from flask import flash, redirect, render_template, session, url_for
from flask.typing import ResponseReturnValue
from flask_login import current_user
from sqlalchemy import and_, select

from main import db, get_or_404
from models import naive_utcnow
from models.content import PROPOSAL_INFOS, Proposal, ProposalVote, ReviewType, StateTransitionException

from . import cfp_review, review_required
from .forms import ReviewListForm, VoteForm


def get_naive_session_dt(name: str) -> NaiveDateTime | None:
    # datetimes seem to be deserialised as UTC, so let's strip it off
    dt: datetime | None = session.get(name)
    if dt is None:
        return None
    return naive(dt.replace(tzinfo=None))


def _split_by_review_count(proposals: list[Proposal], well_reviewed_threshold: int) -> list[Proposal]:
    under = []
    over = []
    for p in proposals:
        if len([v for v in p.votes if v.state != "blocked"]) >= well_reviewed_threshold:
            over.append(p)
        else:
            under.append(p)

    return under + over


@cfp_review.route("/review", methods=["GET", "POST"])
@review_required
def review_list() -> ResponseReturnValue:
    form = ReviewListForm()

    if form.validate_on_submit():
        app.logger.info("Clearing review order")
        session["review_order"] = None
        session["review_order_dt"] = naive_utcnow()
        return redirect(url_for(".review_list"))

    review_order_dt = get_naive_session_dt("review_order_dt")
    last_visit = get_naive_session_dt("review_visit_dt")

    if last_visit is None:
        # Make a guess from the last vote they placed.
        # These are naive datetimes.
        last_vote_time = db.session.scalar(
            select(ProposalVote.modified)
            .where(ProposalVote.user == current_user)
            .order_by(ProposalVote.modified.desc())
        )

        if last_vote_time:
            last_visit = naive(last_vote_time)
            review_order_dt = naive(last_vote_time)

    proposal_query = select(Proposal).where(Proposal.state == "anonymised")

    if not current_user.has_permission("cfp_admin"):
        anonymous_review_types = [
            ti.type for ti in PROPOSAL_INFOS.values() if ti.review_type == ReviewType.anonymous
        ]
        proposal_query = proposal_query.where(
            Proposal.user_id != current_user.id, Proposal.type.in_(anonymous_review_types)
        )

    proposal_vote_query = proposal_query.outerjoin(
        ProposalVote, and_(ProposalVote.proposal_id == Proposal.id, ProposalVote.user_id == current_user.id)
    ).add_columns(ProposalVote)

    to_review_again: list[Proposal] = []
    to_review_new: list[Proposal] = []
    to_review_old: list[Proposal] = []
    reviewed_with_order: list[tuple[Any, Proposal]] = []

    for proposal, vote in db.session.execute(proposal_vote_query):
        proposal.user_vote = vote
        if vote:
            if vote.state in ["new", "resolved", "stale"]:
                proposal.is_new = True
                to_review_again.append(proposal)
            else:
                reviewed_with_order.append(((vote.state, vote.vote or 0, vote.modified), proposal))
        else:
            # modified doesn't really describe when proposals are "new", but it's near enough
            if last_visit is None or review_order_dt is None or proposal.modified < review_order_dt:
                to_review_old.append(proposal)
            else:
                proposal.is_new = True
                to_review_new.append(proposal)

    reviewed = [p for _, p in sorted(reviewed_with_order, reverse=True)]

    review_order: list[int] | None = session.get("review_order")
    if last_visit is None:
        new_visit = True
    else:
        new_visit = naive_utcnow() - last_visit > timedelta(hours=1)

    to_review: list[Proposal]
    if (
        review_order is None
        or not set([p.id for p in to_review_again]).issubset(review_order)
        or (to_review_new and new_visit)
    ):
        random.shuffle(to_review_again)
        random.shuffle(to_review_new)
        random.shuffle(to_review_old)

        well_reviewed_threshold = 10
        to_review_new = _split_by_review_count(to_review_new, well_reviewed_threshold)
        to_review_old = _split_by_review_count(to_review_old, well_reviewed_threshold)

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


def can_review_proposal(proposal: Proposal) -> bool:
    if proposal.state != "anonymised":
        return False

    if current_user.has_permission("cfp_admin"):
        return True

    if proposal.user == current_user:
        return False

    if proposal.type_info.review_type != ReviewType.anonymous:
        return False

    return True


def get_next_review_proposal_id(proposal_id: int) -> int | None:
    review_order: list[int] | None = session.get("review_order")
    if not review_order:
        return None

    if proposal_id not in review_order:
        return None
    cur_index = review_order.index(proposal_id)

    for next_proposal_id in review_order[cur_index + 1 :]:
        proposal = db.session.get_one(Proposal, next_proposal_id)
        # TODO: use proposal_query logic from above?
        if can_review_proposal(proposal):
            return next_proposal_id

    return None


@cfp_review.route("/review/<int:proposal_id>/next")
@review_required
def review_proposal_next(proposal_id: int) -> ResponseReturnValue:
    next_proposal_id = get_next_review_proposal_id(proposal_id)
    if next_proposal_id is None:
        return redirect(url_for(".review_list"))

    return redirect(url_for(".review_proposal", proposal_id=next_proposal_id))


@cfp_review.route("/review/<int:proposal_id>", methods=["GET", "POST"])
@review_required
def review_proposal(proposal_id: int) -> ResponseReturnValue:
    proposal = get_or_404(db, Proposal, proposal_id)

    if not can_review_proposal(proposal):
        app.logger.warning("Cannot review proposal %s", proposal_id)
        flash(f"Cannot review proposal {proposal_id}, continuing to next proposal")
        return redirect(url_for(".review_proposal_next", proposal_id=proposal_id))

    session["review_visit_dt"] = naive_utcnow()

    remaining_count = 0
    next_proposal_id = get_next_review_proposal_id(proposal_id)
    if next_proposal_id is not None:
        review_order: list[int] | None = session.get("review_order")
        if review_order is not None:
            # get_next_review_proposal_id only returns ids from review_order
            remaining_count = len(review_order) - review_order.index(next_proposal_id)

    form = VoteForm()

    vote = db.session.scalar(select(ProposalVote).filter_by(proposal_id=proposal.id, user_id=current_user.id))

    if form.validate_on_submit():
        # Make a new vote if need-be
        if not vote:
            vote = ProposalVote(current_user, proposal)
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
        proposal=proposal,
        previous_vote=vote,
        remaining_count=remaining_count,
    )
