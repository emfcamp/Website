from datetime import timedelta

import dateutil
from flask import (
    redirect, url_for, request, abort, render_template,
    flash, session, jsonify, current_app as app
)
from flask_login import current_user
from flask_mail import Message
from sqlalchemy import func, exists
from sqlalchemy.orm import joinedload

from main import db, mail, external_url
from .majority_judgement import calculate_max_normalised_score
from models.cfp import (
    Proposal, CFPMessage, CFPVote, Venue,
    InvalidVenueException, MANUAL_REVIEW_TYPES
)
from models.user import User
from models.purchase import Ticket
from .forms import (
    UpdateTalkForm, UpdatePerformanceForm, UpdateWorkshopForm,
    UpdateYouthWorkshopForm, UpdateInstallationForm, UpdateVotesForm, SendMessageForm,
    CloseRoundForm, AcceptanceForm, ConvertProposalForm,
)
from . import (
    cfp_review, admin_required, schedule_required, ordered_states,
    get_proposal_sort_dict, get_next_proposal_to
)


@cfp_review.route('')
def main():
    if current_user.is_anonymous:
        return redirect(url_for('users.login', next=url_for('.main')))

    if current_user.has_permission('cfp_admin'):
        return redirect(url_for('.proposals'))

    if current_user.has_permission('cfp_anonymiser'):
        return redirect(url_for('.anonymisation'))

    if current_user.has_permission('cfp_reviewer'):
        return redirect(url_for('.review_list'))

    abort(404)


def bool_qs(val):
    # Explicit true/false values are better than the implicit notset=&set=anything that bool does
    if val in ['True', '1']:
        return True
    elif val in ['False', '0']:
        return False
    raise ValueError('Invalid querystring boolean')

@cfp_review.route('/proposals')
@admin_required
def proposals():

    bool_names = ['one_day', 'needs_help', 'needs_money']
    bool_vals = [request.args.get(n, type=bool_qs) for n in bool_names]
    bool_dict = {n: v for n, v in zip(bool_names, bool_vals) if v is not None}

    proposals = Proposal.query.filter_by(**bool_dict)

    filtered = False

    types = request.args.getlist('type')
    if types:
        filtered = True
        proposals = proposals.filter(Proposal.type.in_(types))

    states = request.args.getlist('state')
    if states:
        filtered = True
        proposals = proposals.filter(Proposal.state.in_(states))

    needs_ticket = request.args.get('needs_ticket', type=bool_qs)
    if needs_ticket is True:
        filtered = True
        proposals = proposals.join(Proposal.user).filter_by(will_have_ticket=False).filter(
            ~exists().where((Ticket.state == 'paid') & (Ticket.type == 'admission_ticket') &
                            (Ticket.owner_id == User.id)))

    sort_dict = get_proposal_sort_dict(request.args)
    proposals = proposals.options(joinedload(Proposal.user)).options(joinedload('user.owned_tickets'))
    proposals = proposals.all()
    proposals.sort(**sort_dict)

    non_sort_query_string = dict(request.args)
    if 'sort_by' in non_sort_query_string:
        del non_sort_query_string['sort_by']

    if 'reverse' in non_sort_query_string:
        del non_sort_query_string['reverse']

    return render_template('cfp_review/proposals.html', proposals=proposals,
                           new_qs=non_sort_query_string, states=ordered_states,
                           filtered=filtered, total_proposals=Proposal.query.count())


def send_email_for_proposal(proposal, reason="still-considered"):
    proposal_title = proposal.title

    while True:
        if reason == "accepted":
            app.logger.info('Sending accepted email for proposal %s', proposal.id)
            subject = 'Your EMF proposal "%s" has been accepted!' % proposal_title
            template = 'cfp_review/email/accepted_msg.txt'

        elif reason == "still-considered":
            app.logger.info('Sending still-considered email for proposal %s', proposal.id)
            subject = 'We\'re still considering your EMF proposal "%s"' % proposal_title
            template = 'cfp_review/email/not_accepted_msg.txt'

        elif reason == "rejected":
            app.logger.info('Sending rejected email for proposal %s', proposal.id)
            proposal.has_rejected_email = True
            subject = 'Your EMF proposal "%s" was not accepted.' % proposal_title
            template = 'emails/cfp-rejected.txt'

        else:
            raise Exception("Unknown cfp proposal email type %s" % reason)

        msg = Message(subject, sender=app.config['CONTENT_EMAIL'],
                    recipients=[proposal.user.email])
        msg.body = render_template(template, user=proposal.user, proposal=proposal)

        # Due to https://bugs.python.org/issue27240 heaader re-wrapping may
        # occasionally fail on arbitrary strings. We try and avoid this by
        # removing the talk title in the subject when the error occurrs.
        # FIXME: This is disgusting and we should remove it when we're on a
        # fixed version of python.
        try:
            mail.send(msg)
            return True
        except AttributeError as e:
            if proposal_title:
                app.logger.error('Failed to email proposal %s, with title, retrying: %s', proposal.id, e)
                proposal_title = ""
            else:
                app.logger.error('Failed to email proposal %s without title, ABORTING: %s', proposal.id, e)
                return False


@cfp_review.route('/proposals/<int:proposal_id>/convert', methods=['GET', 'POST'])
@admin_required
def convert_proposal(proposal_id):
    proposal = Proposal.query.get_or_404(proposal_id)

    form = ConvertProposalForm()
    types = {'talk', 'workshop', 'youthworkshop', 'performance', 'installation'}
    form.new_type.choices = [(t, t.title()) for t in types if t != proposal.type]

    if form.validate_on_submit():
        proposal.type = form.new_type.data
        db.session.commit()

        proposal = Proposal.query.get_or_404(proposal_id)

        return redirect(url_for('.update_proposal', proposal_id=proposal.id))

    return render_template('cfp_review/convert_proposal.html', proposal=proposal, form=form)


@cfp_review.route('/proposals/<int:proposal_id>', methods=['GET', 'POST'])
@admin_required
def update_proposal(proposal_id):
    def log_and_close(msg, next_page, proposal_id=None):
        flash(msg)
        app.logger.info(msg)
        db.session.commit()

        return redirect(url_for(next_page, proposal_id=proposal_id))

    prop = Proposal.query.get_or_404(proposal_id)
    next_prop = get_next_proposal_to(prop, prop.state)

    next_id = next_prop.id if next_prop else None

    form = UpdateTalkForm() if prop.type == 'talk' else \
           UpdateWorkshopForm() if prop.type == 'workshop' else \
           UpdateYouthWorkshopForm() if prop.type == 'youthworkshop' else \
           UpdatePerformanceForm() if prop.type == 'performance' else \
           UpdateInstallationForm()

    # Process the POST
    if form.validate_on_submit():
        try:
            form.update_proposal(prop)
        except InvalidVenueException:
            # FIXME: this should just be standard field validator,
            # e.g. validate_allowed_venues. That way it'll show up
            # in the form where the error is.
            flash('Invalid venue')
            return render_template('cfp_review/update_proposal.html',
                                   proposal=prop, form=form, next_id=next_id)

        if form.update.data:
            msg = 'Updating proposal %s' % proposal_id
            prop.state = form.state.data

        elif form.reject.data or form.reject_with_message.data:
            msg = 'Rejecting proposal %s' % proposal_id
            prop.set_state('rejected')

            if form.reject_with_message.data:
                send_email_for_proposal(prop, reason="rejected")

        elif form.accept.data:
            msg = 'Manually accepting proposal %s' % proposal_id
            prop.set_state('accepted')
            send_email_for_proposal(prop, reason="accepted")

        elif form.checked.data:
            if prop.type in MANUAL_REVIEW_TYPES:
                msg = 'Sending proposal %s for manual review' % proposal_id
                prop.set_state('manual-review')
            else:
                msg = 'Sending proposal %s for anonymisation' % proposal_id
                prop.set_state('checked')

            if not next_id:
                return log_and_close(msg, '.proposals')
            return log_and_close(msg, '.update_proposal', proposal_id=next_id)
        return log_and_close(msg, '.update_proposal', proposal_id=proposal_id)

    form.state.data = prop.state
    form.title.data = prop.title
    form.description.data = prop.description
    form.requirements.data = prop.requirements
    form.length.data = prop.length
    form.notice_required.data = prop.notice_required
    form.needs_help.data = prop.needs_help
    form.needs_money.data = prop.needs_money
    form.one_day.data = prop.one_day
    form.will_have_ticket.data = prop.user.will_have_ticket
    form.published_names.data = prop.published_names
    form.arrival_period.data = prop.arrival_period
    form.departure_period.data = prop.departure_period
    form.telephone_number.data = prop.telephone_number
    form.may_record.data = prop.may_record
    form.needs_laptop.data = prop.needs_laptop
    form.available_times.data = prop.available_times

    form.allowed_venues.data = prop.get_allowed_venues_serialised()
    form.allowed_times.data = prop.get_allowed_time_periods_serialised()
    form.scheduled_time.data = prop.scheduled_time
    form.scheduled_duration.data = prop.scheduled_duration
    form.potential_time.data = prop.potential_time

    if prop.scheduled_venue:
        form.scheduled_venue.data = prop.scheduled_venue.name

    if prop.potential_venue:
        form.potential_venue.data = prop.potential_venue.name

    if prop.type == 'workshop':
        form.attendees.data = prop.attendees
        form.cost.data = prop.cost
        form.participant_equipment.data = prop.participant_equipment
        form.age_range.data = prop.age_range

    elif prop.type == 'youthworkshop':
        form.attendees.data = prop.attendees
        form.cost.data = prop.cost
        form.participant_equipment.data = prop.participant_equipment
        form.age_range.data = prop.age_range
        form.valid_dbs.data = prop.valid_dbs

    elif prop.type == 'installation':
        form.size.data = prop.size
        form.funds.data = prop.funds

    return render_template('cfp_review/update_proposal.html',
                            proposal=prop, form=form, next_id=next_id)

def get_all_messages_sort_dict(parameters, user):
    sort_keys = {
        'unread': lambda p: (p.get_unread_count(user) > 0, p.messages[-1].created),
        'date': lambda p: p.messages[-1].created,
        'from': lambda p: p.user.name,
        'title': lambda p: p.title,
        'count': lambda p: len(p.messages),
    }

    sort_by_key = parameters.get('sort_by')
    reverse = parameters.get('reverse')
    # If unread sort order we have to have unread on top which means reverse sort
    if sort_by_key is None or sort_by_key == 'unread':
        reverse = True
    return {
        'key': sort_keys.get(sort_by_key, sort_keys['unread']),
        'reverse': bool(reverse)
    }

@cfp_review.route('/messages')
@admin_required
def all_messages():
    filter_type = request.args.get('type')

    # Query from the proposal because that's actually what we display
    proposal_with_message = Proposal.query\
        .join(CFPMessage)\
        .filter(Proposal.id == CFPMessage.proposal_id)\
        .order_by(CFPMessage.has_been_read, CFPMessage.created.desc())

    if filter_type:
        proposal_with_message = proposal_with_message.filter(Proposal.type == filter_type)
    else:
        filter_type = 'all'

    proposal_with_message = proposal_with_message.all()

    sort_dict = get_all_messages_sort_dict(request.args, current_user)
    proposal_with_message.sort(**sort_dict)

    return render_template('cfp_review/all_messages.html',
                           proposal_with_message=proposal_with_message, type=filter_type)


@cfp_review.route('/proposals/<int:proposal_id>/message', methods=['GET', 'POST'])
@admin_required
def message_proposer(proposal_id):
    form = SendMessageForm()
    proposal = Proposal.query.get_or_404(proposal_id)

    if request.method == 'POST':
        if form.send.data and form.message.data:
            msg = CFPMessage()
            msg.is_to_admin = False
            msg.from_user_id = current_user.id
            msg.proposal_id = proposal_id
            msg.message = form.message.data

            db.session.add(msg)
            db.session.commit()

            app.logger.info('Sending message from %s to %s', current_user.id, proposal.user_id)

            msg_url = external_url('cfp.proposal_messages', proposal_id=proposal_id)
            msg = Message('New message about your EMF proposal',
                          sender=app.config['CONTENT_EMAIL'],
                          recipients=[proposal.user.email])
            msg.body = render_template('cfp_review/email/new_message.txt', url=msg_url,
                                       to_user=proposal.user, from_user=current_user,
                                       proposal=proposal)
            mail.send(msg)

        if form.mark_read.data or form.send.data:
            count = proposal.mark_messages_read(current_user)
            app.logger.info('Marked %s messages to admin on proposal %s as read' % (count, proposal.id))

        return redirect(url_for('.message_proposer', proposal_id=proposal_id))

    # Admin can see all messages sent in relation to a proposal
    messages = CFPMessage.query.filter_by(
        proposal_id=proposal_id
    ).order_by('created').all()

    return render_template('cfp_review/message_proposer.html',
                           form=form, messages=messages, proposal=proposal)

def get_vote_summary_sort_args(parameters):
    sort_keys = {
        # Notes == unread first then by date
        'notes': lambda p: (p[0].get_unread_vote_note_count() > 0,
                            p[0].get_total_note_count()),
        'date': lambda p: p[0].created,
        'title': lambda p: p[0].title.lower(),
        'votes': lambda p: p[1].get('voted', 0),
        'blocked': lambda p: p[1].get('blocked', 0),
        'recused': lambda p: p[1].get('recused', 0),
    }

    sort_by_key = parameters.get('sort_by')
    return {
        'key': sort_keys.get(sort_by_key, sort_keys['notes']),
        'reverse': bool(parameters.get('reverse'))
    }

@cfp_review.route('/votes')
@admin_required
def vote_summary():
    proposal_query = Proposal.query if request.args.get('all', None) else Proposal.query.filter_by(state='anonymised')

    proposals = proposal_query.order_by('modified').all()

    proposals_with_counts = []
    summary = {
        'notes_total': 0,
        'notes_unread': 0,
        'blocked_total': 0,
        'recused_total': 0,
        'voted_total': 0,
        'min_votes': None,
        'max_votes': 0,
    }

    for prop in proposals:
        state_counts = {}
        vote_count = len([v for v in prop.votes if v.state == 'voted'])

        if summary['min_votes'] is None or summary['min_votes'] > vote_count:
            summary['min_votes'] = vote_count

        if summary['max_votes'] < vote_count:
            summary['max_votes'] = vote_count

        for v in prop.votes:
            # Update proposal values
            state_counts.setdefault(v.state, 0)
            state_counts[v.state] += 1

            # Update note stats
            if v.note is not None:
                summary['notes_total'] += 1

            if v.note is not None and not v.has_been_read:
                summary['notes_unread'] += 1

            # State stats
            if v.state in ('voted', 'blocked', 'recused'):
                summary[v.state + '_total'] += 1

        proposals_with_counts.append((prop, state_counts))

    # sort_key = lambda p: (p[0].get_unread_vote_note_count() > 0, p[0].created)
    sort_args = get_vote_summary_sort_args(request.args)
    proposals_with_counts.sort(**sort_args)

    return render_template('cfp_review/vote_summary.html', summary=summary,
                            proposals_with_counts=proposals_with_counts)


@cfp_review.route('/proposals/<int:proposal_id>/votes', methods=['GET', 'POST'])
@admin_required
def proposal_votes(proposal_id):
    form = UpdateVotesForm()
    proposal = Proposal.query.get_or_404(proposal_id)
    all_votes = {v.id: v for v in proposal.votes}

    if form.validate_on_submit():
        msg = ''
        if form.set_all_stale.data:
            stale_count = 0
            states_to_set = ['voted', 'blocked', 'recused'] if form.include_recused.data\
                                                            else ['voted', 'blocked']
            for vote in all_votes.values():
                if vote.state in states_to_set:
                    vote.set_state('stale')
                    stale_count += 1

            if stale_count:
                msg = 'Set %s votes to stale' % stale_count

        elif form.update.data:
            update_count = 0
            for form_vote in form.votes_to_resolve:
                vote = all_votes[form_vote['id'].data]
                if form_vote.resolve.data and vote.state in ['blocked']:
                    vote.set_state('resolved')
                    update_count += 1

            if update_count:
                msg = 'Set %s votes to resolved' % update_count

        elif form.resolve_all.data:
            resolved_count = 0
            for vote in all_votes.values():
                if vote.state == 'blocked':
                    vote.set_state('resolved')
                    resolved_count += 1

        if msg:
            flash(msg)
            app.logger.info(msg)

        # Regardless, set everything to read
        for v in all_votes.values():
            v.has_been_read = True

        db.session.commit()
        return redirect(url_for('.proposal_votes', proposal_id=proposal_id))

    for v_id in all_votes:
        form.votes_to_resolve.append_entry()
        form.votes_to_resolve[-1]['id'].data = v_id

    return render_template('cfp_review/proposal_votes.html',
                           proposal=proposal, form=form, votes=all_votes)


@cfp_review.route('/close-round', methods=['GET', 'POST'])
@admin_required
def close_round():
    form = CloseRoundForm()
    min_votes = 0

    vote_subquery = CFPVote.query\
        .with_entities(
            CFPVote.proposal_id,
            func.count('*').label('count')
        )\
        .filter(CFPVote.state == 'voted')\
        .group_by('proposal_id')\
        .subquery()

    proposals = Proposal.query\
        .with_entities(Proposal, vote_subquery.c.count)\
        .join(
            vote_subquery,
            Proposal.id == vote_subquery.c.proposal_id
        )\
        .filter(
            Proposal.state.in_(['anonymised', 'reviewed'])
        ).order_by(vote_subquery.c.count.desc()).all()

    preview = False
    if form.validate_on_submit():
        if form.confirm.data:
            min_votes = session['min_votes']
            for (prop, vote_count) in proposals:
                if vote_count >= min_votes and prop.state != 'reviewed':
                    prop.set_state('reviewed')

            db.session.commit()
            del session['min_votes']
            app.logger.info("CFP Round closed. Set %s proposals to 'reviewed'" % len(proposals))

            return redirect(url_for('.rank'))

        elif form.close_round.data:
            preview = True
            session['min_votes'] = form.min_votes.data
            flash('Blue proposals will be marked as "reviewed"')

        elif form.cancel.data:
            form.min_votes.data = form.min_votes.default
            if 'min_votes' in session:
                del session['min_votes']

    return render_template('cfp_review/close-round.html', form=form,
                           proposals=proposals, preview=preview,
                           min_votes=session.get('min_votes'))


@cfp_review.route('/rank', methods=['GET', 'POST'])
@admin_required
def rank():
    proposals = Proposal.query\
        .filter_by(state='reviewed').all()

    form = AcceptanceForm()
    scored_proposals = []

    for prop in proposals:
        score_list = [v.vote for v in prop.votes if v.state == 'voted']
        score = calculate_max_normalised_score(score_list)
        scored_proposals.append((prop, score))

    scored_proposals = sorted(scored_proposals, key=lambda p: p[1], reverse=True)

    preview = False
    if form.validate_on_submit():
        if form.confirm.data:
            min_score = session['min_score']
            count = 0
            for (prop, score) in scored_proposals:

                if score >= min_score:
                    count += 1
                    prop.set_state('accepted')
                    send_email_for_proposal(prop, reason="accepted")

                else:
                    send_email_for_proposal(prop, reason="still-considered")

                db.session.commit()

            del session['min_score']
            msg = "Accepted %s proposals; min score: %s" % (count, min_score)
            app.logger.info(msg)
            flash(msg, 'info')
            return redirect(url_for('.proposals', state='accepted'))

        elif form.set_score.data:
            preview = True
            session['min_score'] = form.min_score.data
            flash('Blue proposals will be accepted', 'info')

        elif form.cancel.data and 'min_score' in session:
            del session['min_score']

    accepted_count = Proposal.query\
        .filter(
            Proposal.state.in_(['accepted', 'finished'])
        ).count()

    return render_template('cfp_review/rank.html', form=form, preview=preview,
                           proposals=scored_proposals, accepted_count=accepted_count,
                           min_score=session.get('min_score'))

@cfp_review.route('/potential_schedule_changes', methods=['GET', 'POST'])
@schedule_required
def potential_schedule_changes():
    proposals = Proposal.query.filter(
        (Proposal.potential_venue != None) | (Proposal.potential_time != None)  # noqa
    ).filter(Proposal.scheduled_duration.isnot(None)).all()

    for proposal in proposals:
        if proposal.scheduled_venue:
            proposal.scheduled_venue_name = proposal.scheduled_venue.name
        if proposal.potential_venue:
            proposal.potential_venue_name = proposal.potential_venue.name

    return render_template('cfp_review/potential_schedule_changes.html', proposals=proposals)

@cfp_review.route('/scheduler')
@schedule_required
def scheduler():
    proposals = Proposal.query.filter(Proposal.scheduled_duration.isnot(None)).\
        filter(Proposal.state.in_(['finished', 'accepted'])).all()

    schedule_data = []
    for proposal in proposals:
        export = {
            'id': proposal.id,
            'duration': proposal.scheduled_duration,
            'is_potential': False,
            'speakers': [ proposal.user.id ],
            'text': proposal.title,
            'valid_venues': [ v.id for v in proposal.get_allowed_venues() ],
            'valid_time_ranges': [
                {"start": str(p.start), "end": str(p.end)} for p in proposal.get_allowed_time_periods_with_default()
            ],
        }

        if proposal.scheduled_venue:
            export['venue'] = proposal.scheduled_venue_id
        if proposal.potential_venue:
            export['venue'] = proposal.potential_venue_id
            export['is_potential'] = True

        if proposal.scheduled_time:
            export['start_date'] = proposal.scheduled_time
        if proposal.potential_time:
            export['start_date'] = proposal.potential_time
            export['is_potential'] = True

        if 'start_date' in export:
            export['end_date'] = export['start_date'] + timedelta(minutes=proposal.scheduled_duration)
            export['start_date'] = str(export['start_date'])
            export['end_date'] = str(export['end_date'])

        # We can't show things that are not yet in a slot!
        # FIXME: Show them somewhere
        if 'venue' not in export or 'start_date' not in export:
            continue

        schedule_data.append(export)

    venues = [{'key': v.id, 'label': v.name} for v in Venue.query.all()]

    return render_template('cfp_review/scheduler.html', venues=venues, schedule_data=schedule_data)

@cfp_review.route('/scheduler_update', methods=['GET', 'POST'])
@admin_required
def scheduler_update():
    proposal = Proposal.query.filter_by(id=request.form['id']).one()
    proposal.potential_time = dateutil.parser.parse(request.form['time']).replace(tzinfo=None)
    proposal.potential_venue = request.form['venue']

    changed = True
    if proposal.potential_time == proposal.scheduled_time and str(proposal.potential_venue_id) == str(proposal.scheduled_venue_id):
        proposal.potential_time = None
        proposal.potential_venue = None
        changed = False

    db.session.commit()
    return jsonify({'changed': changed})
