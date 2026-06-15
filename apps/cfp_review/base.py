from collections import Counter, defaultdict
from collections.abc import Callable
from typing import Any, Literal, get_args

from flask import (
    abort,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask import current_app as app
from flask.typing import ResponseReturnValue
from flask_login import current_user
from flask_mailman import EmailMessage
from sqlalchemy import desc, func, select
from sqlalchemy.orm import joinedload, selectinload
from sqlalchemy_continuum.utils import version_class

from apps.common import get_next_url
from main import db, external_url, get_or_404
from models.content import (
    Occurrence,
    Proposal,
    ProposalMessage,
    ProposalRound,
    ProposalType,
    ProposalVote,
    Round,
    ScheduleItem,
    Tag,
)
from models.content.schedule import ScheduleItemType
from models.permission import Permission
from models.purchase import AdmissionTicket
from models.user import User

from ..config import config
from . import admin_required, bool_qs, cfp_review, schedule_required, sort_proposals
from .email import send_email_for_proposal
from .estimation import get_cfp_estimate
from .forms import AcceptanceForm, CloseRoundForm, InviteSpeakerForm, ReversionForm, SendMessageForm
from .majority_judgement import calculate_max_normalised_score


@cfp_review.route("/")
def main() -> ResponseReturnValue:
    if current_user.is_anonymous:
        return redirect(url_for("users.login", next=url_for(".main")))

    if current_user.has_permission("cfp_admin"):
        return redirect(url_for(".proposals"))

    if current_user.has_permission("cfp_anonymiser"):
        return redirect(url_for(".anonymisation"))

    if current_user.has_permission("cfp_reviewer"):
        return redirect(url_for(".review_list"))

    abort(404)


@cfp_review.route("help")
def help():
    if current_user.is_anonymous:
        return redirect(url_for("users.login", next=url_for(".main")))
    return render_template("cfp_review/help.html")


def filter_proposal_request() -> tuple[list[Proposal], bool]:
    proposal_query = select(Proposal)
    is_filtered = False

    bool_names: list[str] = ["one_day", "needs_help", "needs_money"]
    bool_vals = [request.args.get(n, type=bool_qs) for n in bool_names]
    bool_dict = {n: v for n, v in zip(bool_names, bool_vals, strict=True) if v is not None}
    if bool_dict:
        is_filtered = True
        proposal_query = proposal_query.filter_by(**bool_dict)

    types = request.args.getlist("type")
    if types:
        is_filtered = True
        proposal_query = proposal_query.where(Proposal.type.in_(types))

    states = request.args.getlist("state")
    if states:
        is_filtered = True
        proposal_query = proposal_query.where(Proposal.state.in_(states))

    needs_ticket = request.args.get("needs_ticket", type=bool_qs)
    if needs_ticket is True:
        is_filtered = True
        proposal_query = proposal_query.where(
            ~Proposal.user.has(User.will_have_ticket.is_(True)),
            ~Proposal.user.has(
                User.owned_admission_tickets.any(AdmissionTicket.state.in_(["paid", "payment-pending"]))
            ),
        )

    tags = request.args.getlist("tags")
    if "untagged" in tags:
        if len(tags) > 1:
            flash("'untagged' in 'tags' arg, other tags ignored")
        is_filtered = True
        proposal_query = proposal_query.where(~Proposal._tags.any())

    elif tags:
        is_filtered = True
        proposal_query = proposal_query.where(Proposal._tags.any(Tag.tag.in_(tags)))

    has_notes = request.args.get("has_notes", type=bool_qs)
    if has_notes:
        is_filtered = True
        proposal_query = proposal_query.where(Proposal.private_notes.is_not(None))

    proposal_query = proposal_query.options(
        selectinload(Proposal.user).selectinload(User.owned_tickets)
    ).options(selectinload(Proposal._tags))
    proposals = list(db.session.scalars(proposal_query))

    proposals = sort_proposals(proposals)

    return proposals, is_filtered


def sort_messages(messages: list[Proposal]) -> None:
    sort_keys: dict[str, Callable[[Proposal], Any]] = {
        "unread": lambda p: (p.get_unread_count(current_user) > 0, p.messages[-1].created),
        "date": lambda p: p.messages[-1].created,
        "from": lambda p: p.user.name,
        "title": lambda p: p.title,
        "count": lambda p: len(p.messages),
    }

    sort_by_key = request.args.get("sort_by", "unread")
    reverse = bool(request.args.get("reverse"))
    # If unread sort order we have to have unread on top which means reverse sort
    if sort_by_key is None or sort_by_key == "unread":
        reverse = True

    messages.sort(
        key=sort_keys.get(sort_by_key, sort_keys["unread"]),
        reverse=reverse,
    )


@cfp_review.route("/messages")
@admin_required
def messages():
    proposals_with_messages_query = (
        select(Proposal)
        .join(Proposal.messages)
        .order_by(ProposalMessage.has_been_read, ProposalMessage.created.desc())
        .options(joinedload(Proposal.messages))
    )

    filter_type = request.args.get("type")
    if filter_type:
        proposals_with_messages_query = proposals_with_messages_query.filter(Proposal.type == filter_type)
    else:
        filter_type = "all"

    proposals_with_messages = list(db.session.scalars(proposals_with_messages_query).unique())

    sort_messages(proposals_with_messages)

    return render_template(
        "cfp_review/messages.html",
        proposals_with_messages=proposals_with_messages,
        type=filter_type,
    )


VersionedEntityType = Literal["proposal", "schedule-item", "occurrence"]


@cfp_review.route("/versions/<entity_type>")
@admin_required
def entity_changelog(entity_type: VersionedEntityType) -> ResponseReturnValue:
    if entity_type == "proposal":
        version_cls = version_class(Proposal)
    elif entity_type == "schedule-item":
        version_cls = version_class(ScheduleItem)
    elif entity_type == "occurrence":
        version_cls = version_class(Occurrence)
    else:
        abort(404)

    size = int(request.args.get("size", "100"))
    versions = db.session.query(version_cls).order_by(
        version_cls.transaction_id.desc(), version_cls.modified.desc()
    )
    paged_versions = db.paginate(versions, per_page=size, error_out=False)

    return render_template(
        "cfp_review/entity_changelog.html", versions=paged_versions, entity_type=entity_type
    )


@cfp_review.route("/versions/<entity_type>/<int:entity_id>")
@admin_required
def entity_latest_version(entity_type: VersionedEntityType, entity_id: int) -> ResponseReturnValue:
    entity: Proposal | ScheduleItem | Occurrence
    if entity_type == "proposal":
        entity = get_or_404(db, Proposal, entity_id)
    elif entity_type == "schedule-item":
        entity = get_or_404(db, ScheduleItem, entity_id)
    elif entity_type == "occurrence":
        entity = get_or_404(db, Occurrence, entity_id)
    else:
        abort(404)

    last_txn_id = list(entity.versions)[-1].transaction_id  # type: ignore[union-attr]
    return redirect(
        url_for(".entity_version", entity_type=entity_type, entity_id=entity_id, txn_id=last_txn_id)
    )


@cfp_review.route("/versions/<entity_type>/<int:entity_id>/<int:txn_id>", methods=["GET", "POST"])
@admin_required
def entity_version(entity_type: VersionedEntityType, entity_id: int, txn_id: int) -> ResponseReturnValue:
    entity: Proposal | ScheduleItem | Occurrence
    if entity_type == "proposal":
        entity = get_or_404(db, Proposal, entity_id)
    elif entity_type == "schedule-item":
        entity = get_or_404(db, ScheduleItem, entity_id)
    elif entity_type == "occurrence":
        entity = get_or_404(db, Occurrence, entity_id)
    else:
        abort(404)

    form = ReversionForm()
    version = entity.versions.filter_by(transaction_id=txn_id).one()  # type: ignore[union-attr]

    if form.validate_on_submit():
        app.logger.info(f"Reverting {entity_type} {entity_id} to transaction {txn_id}")
        version.revert()
        db.session.commit()
        return redirect(url_for(".entity_latest_version", entity_type=entity_type, entity_id=entity_id))

    return render_template(
        "cfp_review/entity_version.html",
        form=form,
        entity_type=entity_type,
        entity=entity,
        version=version,
    )


@cfp_review.route("/message-batch", methods=["GET", "POST"])
@admin_required
def message_batch():
    proposals, _is_filtered = filter_proposal_request()

    form = SendMessageForm()
    if form.validate_on_submit():
        if form.send.data:
            for proposal in proposals:
                msg = ProposalMessage()
                msg.is_to_admin = False
                msg.from_user_id = current_user.id
                msg.proposal_id = proposal.id
                msg.message = form.message.data

                db.session.add(msg)
                db.session.commit()

                app.logger.info("Sending message from %s to %s", current_user.id, proposal.user_id)

                msg_url = external_url("cfp.proposal_messages", proposal_id=proposal.id)
                msg = EmailMessage(
                    "New message about your EMF proposal",
                    from_email=config.from_email("CONTENT_EMAIL"),
                    to=[proposal.user.email],
                )
                msg.body = render_template(
                    "cfp_review/email/new_message.txt",
                    url=msg_url,
                    to_user=proposal.user,
                    from_user=current_user,
                    proposal=proposal,
                )
                msg.send()

            flash(f"Messaged {len(proposals)} proposals", "info")
            return redirect(url_for(".proposals", **request.args))

    return render_template("cfp_review/message_batch.html", form=form, proposals=proposals)


def sort_for_vote_summary(proposals_with_state_counts: list[tuple[Proposal, dict[str, int]]]) -> None:
    sort_keys: dict[str, Callable[[tuple[Proposal, dict[str, int]]], Any]] = {
        # Notes == unread first then by date
        "notes": lambda p: (
            p[0].get_unread_vote_note_count() > 0,
            p[0].get_total_vote_note_count(),
        ),
        "date": lambda p: p[0].created,
        "title": lambda p: p[0].title.lower(),
        "votes": lambda p: p[1].get("voted", 0),
        "blocked": lambda p: p[1].get("blocked", 0),
        "recused": lambda p: p[1].get("recused", 0),
    }

    proposals_with_state_counts.sort(
        key=sort_keys.get(request.args.get("sort_by", "notes"), sort_keys["notes"]),
        reverse=bool(request.args.get("reverse")),
    )


@cfp_review.route("/votes")
@admin_required
def vote_summary() -> ResponseReturnValue:
    proposal_query = select(Proposal).options(joinedload(Proposal.votes)).order_by("modified")
    if not request.args.get("all", None):
        proposal_query = proposal_query.where(Proposal.state == "anonymised")

    proposals = list(db.session.scalars(proposal_query).unique())

    proposals_with_counts = []
    summary: dict[str, int] = defaultdict(int)

    for proposal in proposals:
        state_counts: dict[str, int] = {}
        vote_count = len([v for v in proposal.votes if v.state == "voted"])

        if "min_votes" not in summary or summary["min_votes"] > vote_count:
            summary["min_votes"] = vote_count

        if summary["max_votes"] < vote_count:
            summary["max_votes"] = vote_count

        for v in proposal.votes:
            # Update proposal values
            state_counts.setdefault(v.state, 0)
            state_counts[v.state] += 1

            # Update note stats
            if v.note is not None:
                summary["notes_total"] += 1

            if v.note is not None and not v.has_been_read:
                summary["notes_unread"] += 1

            # State stats
            if v.state in ("voted", "blocked", "recused"):
                summary[v.state + "_total"] += 1

        proposals_with_counts.append((proposal, state_counts))

    # sort_key = lambda p: (p[0].get_unread_vote_note_count() > 0, p[0].created)
    sort_for_vote_summary(proposals_with_counts)

    return render_template(
        "cfp_review/vote_summary.html",
        summary=summary,
        proposals_with_counts=proposals_with_counts,
    )


@cfp_review.route("/close-round/<proposal_type>", methods=["GET", "POST"])
@admin_required
def close_round(proposal_type: ProposalType) -> ResponseReturnValue:
    if proposal_type not in get_args(ProposalType):
        # FIXME: this should check .review_type
        flash("Can only close rounds for talks or workshops")
        return redirect(url_for(".proposals"))
    form = CloseRoundForm()
    min_votes = 0

    vote_subquery = (
        db.session.query(ProposalVote)
        .with_entities(ProposalVote.proposal_id, func.count("*").label("count"))
        .filter(ProposalVote.state == "voted")
        .group_by("proposal_id")
        .subquery()
    )

    proposals = (
        db.session.query(Proposal)
        .with_entities(Proposal, vote_subquery.c.count)
        .join(vote_subquery, Proposal.id == vote_subquery.c.proposal_id)
        .filter(Proposal.state == "anonymised", Proposal.type == proposal_type)
        .order_by(vote_subquery.c.count.desc())
        .all()
    )

    preview = False
    if form.validate_on_submit():
        if form.confirm.data:
            min_votes = session["min_votes"]
            round = Round(proposal_type=proposal_type, minimum_votes=int(min_votes), minimum_score=-1.0)
            db.session.add(round)

            for prop, vote_count in proposals:
                proposal_round = ProposalRound(
                    round=round,
                    proposal=prop,
                    vote_count=vote_count,
                    score=-1.0,
                )
                if vote_count >= min_votes:
                    proposal_round.outcome = "in-progress"
                else:
                    proposal_round.outcome = "not-enough-votes"
                db.session.add(proposal_round)

            db.session.commit()
            del session["min_votes"]
            app.logger.info(f"CFP Round closed. Set {len(proposals)} proposals to 'reviewed'")

            return redirect(url_for(".rank", round_id=round.id))

        if form.close_round.data:
            preview = True
            session["min_votes"] = form.min_votes.data
            flash(f'Proposals with more than {session["min_votes"]} (blue) will be marked as "reviewed"')

        elif form.cancel.data:
            form.min_votes.data = form.min_votes.default  # type: ignore [assignment]
            if "min_votes" in session:
                del session["min_votes"]

    # Find proposals where the submitter has already had an accepted proposal
    # or another proposal in this list
    duplicates = {}
    for prop, _ in proposals:
        if len(prop.user.proposals) > 1:
            duplicates[prop.user] = prop.user.proposals

    return render_template(
        "cfp_review/close-round.html",
        form=form,
        proposals=proposals,
        duplicates=duplicates,
        preview=preview,
        min_votes=session.get("min_votes"),
    )


@cfp_review.route("/rank/<int:round_id>", methods=["GET", "POST"])
@admin_required
def rank(round_id: int) -> ResponseReturnValue:
    round = get_or_404(db, Round, round_id)

    most_recent_round = (
        db.session.query(Round)
        .where(Round.proposal_type == round.proposal_type)
        .order_by(desc(Round.created))
        .first()
    )

    if round != most_recent_round and most_recent_round:
        flash(
            f"WARNING: this is not the most recent {round.proposal_type} round. Did you want {url_for('.rank', round_id=most_recent_round.id)}?"
        )

    form = AcceptanceForm()
    scored_proposals = []

    for round_prop in round.proposal_rounds:
        if round_prop.outcome == "not-enough-votes":
            continue
        score_list = [v.vote for v in round_prop.proposal.votes if v.state == "voted"]
        score = calculate_max_normalised_score(score_list)
        scored_proposals.append((round_prop.proposal, score))

    scored_proposals = sorted(scored_proposals, key=lambda p: p[1], reverse=True)

    preview = False
    if form.validate_on_submit():
        if form.confirm.data:
            min_score = session["min_score"]
            count = 0
            round.minimum_score = min_score
            for proposal, score in scored_proposals:
                # If the proposal is no longer in anonymised state we shouldn't
                # touch it, because we've probably rejected, pulled, or
                # accepted it during round close review. If we don't do this
                # then we can set accepted talks back to anonymised.
                if proposal.state != "anonymised":
                    continue

                proposal_round = (
                    db.session.query(ProposalRound)
                    .where(
                        ProposalRound.round == round,
                        ProposalRound.proposal == proposal,
                    )
                    .one()
                )
                proposal_round.score = score
                app.logger.info(f"score is {score}, type is {type(score)}")

                if score >= min_score:
                    count += 1
                    proposal.accept()
                    proposal_round.outcome = "accepted"

                    # NB there is also the 'nobody' email option
                    if form.confirm_type.data in (
                        "accepted_unaccepted",
                        "accepted",
                        "accepted_reject",
                    ):
                        send_email_for_proposal(proposal, reason="accepted")

                else:
                    proposal_round.outcome = "still-considering"
                    if (
                        form.confirm_type.data == "accepted_unaccepted"
                        and not proposal.still_considering_email_sent
                    ):
                        proposal.still_considering_email_sent = True
                        send_email_for_proposal(proposal, reason="still-considered")

                    elif form.confirm_type.data == "accepted_reject":
                        proposal.state = "rejected"
                        proposal_round.outcome = "rejected"
                        proposal.rejected_email_sent = True
                        send_email_for_proposal(proposal, reason="rejected")

            for round_prop in round.proposal_rounds:
                if (
                    round_prop.outcome == "not-enough-votes"
                    and not round_prop.proposal.still_considering_email_sent
                ):
                    round_prop.proposal.still_considering_email_sent = True
                    send_email_for_proposal(round_prop.proposal, reason="still-considered")

            db.session.commit()

            del session["min_score"]
            msg = f"Accepted {count} proposals; min score: {min_score}"
            app.logger.info(msg)
            flash(msg, "info")
            return redirect(url_for(".proposals", state="accepted"))

        if form.set_score.data:
            preview = True
            session["min_score"] = form.min_score.data
            flash("Blue proposals will be accepted", "info")

        elif form.cancel.data and "min_score" in session:
            del session["min_score"]

    schedule_item_types: list[ScheduleItemType] = ["talk", "workshop"]
    estimates = {
        schedule_item_type: get_cfp_estimate(schedule_item_type) for schedule_item_type in schedule_item_types
    }

    # Find proposals where the submitter has already had an accepted proposal
    # or another proposal in this list
    duplicates = {}
    for prop, _ in scored_proposals:
        if len(prop.user.proposals) > 1:
            duplicates[prop.user] = prop.user.proposals

    return render_template(
        "cfp_review/rank.html",
        form=form,
        preview=preview,
        proposals=scored_proposals,
        duplicates=duplicates,
        estimates=estimates,
        min_score=session.get("min_score"),
        proposal_types=schedule_item_types,
    )


# FIXME: orphans from lightning talk class
def get_remaining_lightning_slots():
    return {}


def get_total_lightning_talk_slots():
    return {}


@cfp_review.route("/lightning-talks")
@schedule_required
def lightning_talks():
    filter_query = {"type": "lightning"}
    if "day" in request.args:
        filter_query["session"] = request.args["day"]

    proposals = ScheduleItem.query.filter_by(**filter_query).filter(ScheduleItem.state != "withdrawn").all()

    remaining_lightning_slots = get_remaining_lightning_slots()

    return render_template(
        "cfp_review/lightning_talks_list.html",
        proposals=proposals,
        remaining_lightning_slots=remaining_lightning_slots,
        total_slots=get_total_lightning_talk_slots(),
    )


@cfp_review.route("/confidentiality", methods=["GET", "POST"])
def confidentiality_warning():
    if request.method == "POST" and request.form.get("agree"):
        session["cfp_confidentiality"] = True
        return redirect(get_next_url(default=url_for(".proposals")))

    return render_template("cfp_review/confidentiality_warning.html")


@cfp_review.route("/invite-speaker", methods=["GET", "POST"])
@admin_required
def invite_speaker():
    form = InviteSpeakerForm()

    if form.validate_on_submit():
        email, name, reason = form.email.data, form.name.data, form.invite_reason.data
        user = User(email, name)
        user.cfp_invite_reason = reason

        db.session.add(user)
        db.session.commit()

        app.logger.info(f"{current_user.id} created a new user {user} ({email}) to invite to the cfp")

        code = user.login_code(app.config["SECRET_KEY"])

        return render_template(
            "cfp_review/invite-speaker-complete.html",
            user=user,
            login_code=code,
            proposal_type=form.proposal_type.data,
        )

    return render_template("cfp_review/invite-speaker.html", form=form)


def get_diversity_counts(user_list):
    res = {
        "age": Counter(),
        "gender": Counter(),
        "ethnicity": Counter(),
        "reviewer_tags": Counter(),
        "other": {
            "total": len(user_list),
        },
    }

    for user in user_list:
        if not user.diversity:
            res["age"][""] += 1
            res["gender"][""] += 1
            res["ethnicity"][""] += 1
            continue

        if user.diversity.age:
            res["age"][user.diversity.age] += 1
        else:
            res["age"][""] += 1
        if user.diversity.gender:
            res["gender"][user.diversity.gender] += 1
        else:
            res["gender"][""] += 1
        if user.diversity.ethnicity:
            res["ethnicity"][user.diversity.ethnicity] += 1
        else:
            res["ethnicity"][""] += 1
        for tag in user.cfp_reviewer_tags:
            res["reviewer_tags"][tag] += 1

    res["age"]["not given"] = res["age"][""]
    del res["age"][""]
    res["gender"]["not given"] = res["gender"][""]
    del res["gender"][""]
    res["ethnicity"]["not given"] = res["ethnicity"][""]
    del res["ethnicity"][""]

    return res


@cfp_review.route("/speaker-diversity")
@admin_required
def speaker_diversity():
    speakers = (
        db.session.query(User)
        .join(User.proposals)
        .filter(
            User.proposals.any(
                Proposal.state.in_(
                    [
                        "manual-review",
                        "accepted",
                        "finalised",
                    ]
                )
            )
        )
        .all()
    )
    total_counts = get_diversity_counts(speakers)
    # remove tags from the counts as these are reviewer tags and irrelevant here
    total_counts.pop("reviewer_tags")
    total_counts["other"]["missing proposal"] = ""

    invited_speakers = [u for u in speakers if u.is_invited_speaker]
    invited_counts = get_diversity_counts(invited_speakers)
    invited_counts.pop("reviewer_tags")

    invited_counts["other"]["missing proposal"] = len(
        [
            u
            for u in db.session.query(User).where(User.cfp_invite_reason.is_not(None)).all()
            if len(u.proposals) == 0
        ]
    )

    return render_template(
        "cfp_review/speaker_diversity.html",
        total_counts=total_counts,
        invited_counts=invited_counts,
    )


@cfp_review.route("/reviewer-diversity")
@admin_required
def reviewer_diversity():
    reviewers = (
        User.query.join(User.permissions)
        .filter(User.permissions.any(Permission.name.in_(["cfp_reviewer"])))
        .all()
    )
    counts = get_diversity_counts(reviewers)
    return render_template("cfp_review/reviewer_diversity.html", counts=counts)


@cfp_review.route("/users/<int:user_id>", methods=["GET"])
@admin_required
def cfp_user(user_id: int) -> ResponseReturnValue:
    user = db.get_or_404(User, user_id)
    if not user.proposals and not user.schedule_items:
        abort(404)
    return render_template(
        "cfp_review/cfp_user.html",
        user=user,
    )


@cfp_review.route("/users/<int:user_id>/issue_cfp_voucher", methods=["POST"])
@admin_required
def issue_cfp_voucher(user_id: int) -> ResponseReturnValue:
    user = db.get_or_404(User, user_id)

    if request.form.get("issue_voucher") == "True":
        had_voucher = user.cfp_voucher is not None
        user.issue_cfp_voucher()

        if not had_voucher:
            flash("Issued CfP voucher")
            app.logger.info("Sending manual CfP voucher email for user %s", user.id)
            msg = EmailMessage(
                "Your Electromagnetic Field Voucher",
                from_email=config.from_email("CONTENT_EMAIL"),
                to=[user.email],
            )
            msg.body = render_template(
                "cfp_review/email/voucher_issued.txt",
                user=user,
                reserve_ticket_link=app.config["RESERVE_LIST_TICKET_LINK"],
            )
            msg.send()
        else:
            flash("Refreshed CfP voucher. The user has not been emailed.")

            app.logger.info("Refreshed CfP voucher for %s", user.id)

        db.session.commit()

    return redirect(url_for(".cfp_user", user_id=user_id))


@cfp_review.route("/lottery")
@admin_required
def lottery():
    ticketed_occurrences = list(db.session.scalars(select(Occurrence).filter_by(uses_lottery=True)))
    return render_template("cfp_review/lottery.html", ticketed_proposals=ticketed_occurrences)


from . import venues  # noqa
