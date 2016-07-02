# encoding=utf-8

from flask import (
    redirect, url_for, request, abort, render_template,
    flash, Blueprint, session, current_app as app
)
from flask.ext.login import current_user

from sqlalchemy import func, or_
from sqlalchemy.orm import aliased

from wtforms import (
    SubmitField, StringField, FieldList, FormField, SelectField, TextAreaField,
    BooleanField, IntegerField, FloatField
)
from wtforms.validators import Required, NumberRange, ValidationError

import random
from datetime import datetime, timedelta
from main import db, external_url
from .common import require_permission, send_template_email
from .majority_judgement import calculate_max_normalised_score

from models.ticket import Ticket, TicketType
from models.user import User
from models.cfp import (
    Proposal, CFPMessage, CFPVote, CFP_STATES
)
from .common.forms import Form, HiddenIntegerField

cfp_review = Blueprint('cfp_review', __name__)
admin_required = require_permission('admin')  # Decorator to require admin permissions
anon_required = require_permission('cfp_anonymiser')
review_required = require_permission('cfp_reviewer')
ordered_states = [
    'edit', 'new', 'locked', 'checked', 'rejected', 'cancelled', 'anonymised',
    'anon-blocked', 'manual-review', 'reviewed', 'accepted', 'finished'
]


@cfp_review.context_processor
def cfp_review_variables():
    unread_count = CFPMessage.query.filter(
        # is_to_admin AND (has_been_read IS null OR has_been_read IS false)
        or_(CFPMessage.has_been_read.is_(False),
            CFPMessage.has_been_read.is_(None)),
        CFPMessage.is_to_admin.is_(True)
    ).count()

    count_dict = dict(Proposal.query.with_entities(
        Proposal.state,
        func.count(Proposal.state),
    ).group_by(Proposal.state).all())
    proposal_counts = {state: count_dict.get(state, 0) for state in CFP_STATES}

    unread_reviewer_notes = CFPVote.query.join(Proposal).filter(
        Proposal.id == CFPVote.proposal_id,
        Proposal.state == 'anonymised',
        or_(CFPVote.has_been_read.is_(False),
            CFPVote.has_been_read.is_(None))
    ).count()

    return {
        'ordered_states': ordered_states,
        'unread_count': unread_count,
        'proposal_counts': proposal_counts,
        'unread_reviewer_notes': unread_reviewer_notes,
        'view_name': request.url_rule.endpoint.replace('cfp_review.', '.')
    }

@cfp_review.route('')
def main():
    if current_user.is_anonymous():
        return redirect(url_for('users.login', next=url_for('.main')))

    if current_user.has_permission('admin'):
        return redirect(url_for('.proposals'))

    if current_user.has_permission('cfp_anonymiser'):
        return redirect(url_for('.anonymisation'))

    if current_user.has_permission('cfp_reviewer'):
        return redirect(url_for('.review_list'))

    abort(404)


def build_proposal_query_dict(parameters):
    res = {}
    fields = [('type', str), ('state', str), ('needs_help', bool), ('needs_money', bool)]

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

def sort_by_notice(notice):
    return {
        '1 week': 0,
        '1 month': 1,
        '> 1 month': 2,
    }.get(notice, -1)

def get_proposal_sort_dict(parameters):
    sort_keys = {
        'state': lambda p: (p.state, p.modified, p.title),
        'date': lambda p: (p.modified, p.title),
        'type': lambda p: (p.type, p.title),
        'user': lambda p: (p.user.name, p.title),
        'title': lambda p: p.title,
        'ticket': lambda p: (p.user.tickets.count() > 0, p.title),
        'notice': lambda p: (sort_by_notice(p.notice_required), p.title),
    }

    sort_by_key = parameters.get('sort_by')
    return {
        'key': sort_keys.get(sort_by_key, sort_keys['state']),
        'reverse': bool(parameters.get('reverse'))
    }


@cfp_review.route('/proposals')
@admin_required
def proposals():
    query_dict = build_proposal_query_dict(request.args)
    proposals = Proposal.query.filter_by(**query_dict)

    if request.args.get('needs_ticket') == 'True':
        paid_tickets = Ticket.query.join(TicketType).filter(
            TicketType.admits == 'full',
            or_(Ticket.paid == True,  # noqa
                Ticket.expired == False),
        )
        proposals = proposals.join(Proposal.user).filter(
            User.will_have_ticket == False,  # noqa
            ~paid_tickets.filter(User.tickets.expression).exists()
        )

    sort_dict = get_proposal_sort_dict(request.args)
    proposals = proposals.all()
    proposals.sort(**sort_dict)

    non_sort_query_string = dict(request.args)
    if 'sort_by' in non_sort_query_string:
        del non_sort_query_string['sort_by']

    if 'reverse' in non_sort_query_string:
        del non_sort_query_string['reverse']

    return render_template('cfp_review/proposals.html', proposals=proposals,
                           new_qs=non_sort_query_string)


class UpdateProposalForm(Form):
    # Admin can change anything
    state = SelectField('State', choices=[(s, s) for s in ordered_states])
    title = StringField('Title', [Required()])
    description = TextAreaField('Description', [Required()])
    requirements = TextAreaField('Requirements')
    length = StringField('Length')
    notice_required = SelectField("Required notice",
                                  choices=[('1 week', '1 week'),
                                           ('1 month', '1 month'),
                                           ('> 1 month', 'Longer than 1 month')])
    needs_help = BooleanField('Needs Help')
    needs_money = BooleanField('Needs Money')
    one_day = BooleanField('One day only')
    will_have_ticket = BooleanField('Will have a ticket')

    published_names = StringField('Published names')
    arrival_period = StringField('Arrival time')
    departure_period = StringField('Departure time')
    telephone_number = StringField('Telephone')
    may_record = BooleanField('May record')
    needs_laptop = BooleanField('Needs laptop')
    available_times = StringField('Available times')

    update = SubmitField('Force update')
    reject = SubmitField('Reject')
    checked = SubmitField('Send for Anonymisation')
    accept = SubmitField('Accept and send standard email')
    reject_with_message = SubmitField('Reject and send standard email')

    def update_proposal(self, proposal):
        proposal.title = self.title.data
        proposal.description = self.description.data
        proposal.requirements = self.requirements.data
        proposal.length = self.length.data
        proposal.notice_required = self.notice_required.data
        proposal.needs_help = self.needs_help.data
        proposal.needs_money = self.needs_money.data
        proposal.one_day = self.one_day.data
        proposal.user.will_have_ticket = self.will_have_ticket.data
        proposal.published_names = self.published_names.data
        proposal.arrival_period = self.arrival_period.data
        proposal.departure_period = self.departure_period.data
        proposal.telephone_number = self.telephone_number.data
        proposal.may_record = self.may_record.data
        proposal.needs_laptop = self.needs_laptop.data
        proposal.available_times = self.available_times.data


class UpdateWorkshopForm(UpdateProposalForm):
    cost = StringField('Cost per attendee')
    attendees = StringField('Attendees', [Required()])

    def update_proposal(self, proposal):
        proposal.cost = self.cost.data
        proposal.attendees = self.attendees.data
        super(UpdateWorkshopForm, self).update_proposal(proposal)


class UpdateInstallationForm(UpdateProposalForm):
    funds = StringField('Funds')
    size = StringField('Size', [Required()])

    def update_proposal(self, proposal):
        proposal.size = self.size.data
        proposal.funds = self.funds.data
        super(UpdateInstallationForm, self).update_proposal(proposal)


def get_next_proposal_to(prop, state):
    return Proposal.query.filter(
        Proposal.id != prop.id,
        Proposal.state == state,
        Proposal.modified >= prop.modified # ie find something after this one
    ).order_by('modified', 'id').first()

@cfp_review.route('/proposals/<int:proposal_id>', methods=['GET', 'POST'])
@admin_required
def update_proposal(proposal_id):
    prop = Proposal.query.get_or_404(proposal_id)
    next_prop = get_next_proposal_to(prop, prop.state)

    next_id = next_prop.id if next_prop else None

    form = UpdateProposalForm() if prop.type == 'talk' else \
           UpdateWorkshopForm() if prop.type == 'workshop' else \
           UpdateInstallationForm()

    # Process the POST
    if form.validate_on_submit():
        form.update_proposal(prop)
        if form.update.data:
            msg = 'Updating proposal %s' % proposal_id
            prop.state = form.state.data

        elif form.reject.data or form.reject_with_message.data:
            msg = 'Rejecting proposal %s' % proposal_id
            prop.set_state('rejected')

            if form.reject_with_message.data:
                send_email_for_proposal(prop, accepted=False)

        elif form.accept.data:
            msg = 'Manually accepting proposal %s' % proposal_id
            prop.set_state('accepted')
            send_email_for_proposal(prop, accepted=True)

        elif form.checked.data:
            msg = 'Sending proposal %s for anonymisation' % proposal_id
            prop.set_state('checked')

            flash(msg)
            app.logger.info(msg)
            db.session.commit()
            if not next_id:
                return redirect(url_for('.proposals'))
            return redirect(url_for('.update_proposal', proposal_id=next_id))

        flash(msg)
        app.logger.info(msg)
        db.session.commit()
        return redirect(url_for('.update_proposal', proposal_id=proposal_id))

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

    if prop.type == 'workshop':
        form.attendees.data = prop.attendees
        form.cost.data = prop.cost

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
def all_messages(types=None):
    # TODO add search
    # Query from the proposal because that's actually what we display
    proposal_with_message = Proposal.query\
        .join(CFPMessage)\
        .filter(Proposal.id == CFPMessage.proposal_id)\
        .order_by(CFPMessage.has_been_read, CFPMessage.created.desc())

    # if 'all' not in request.args:
    if not request.args.get('all'):
        proposal_with_message = proposal_with_message.filter(Proposal.type != 'installation')

    proposal_with_message = proposal_with_message.all()

    sort_dict = get_all_messages_sort_dict(request.args, current_user)
    proposal_with_message.sort(**sort_dict)

    return render_template('cfp_review/all_messages.html',
                           proposal_with_message=proposal_with_message, types=types)


class SendMessageForm(Form):
    message = TextAreaField('New Message')
    send = SubmitField('Send Message')
    mark_read = SubmitField('Mark all as read')


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
            send_template_email('New message about your EMF proposal',
                                proposal.user.email, app.config['CONTENT_EMAIL'],
                                'cfp_review/email/new_message.txt', url=msg_url,
                                to_user=proposal.user, from_user=current_user,
                                proposal=proposal)

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

        if summary['min_votes'] > vote_count or summary['min_votes'] is None:
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


class ResolveVoteForm(Form):
    id = HiddenIntegerField('Vote Id')
    resolve = BooleanField("Set to 'resolved'")


class UpdateVotesForm(Form):
    votes_to_resolve = FieldList(FormField(ResolveVoteForm))
    include_recused = BooleanField("Also set 'recused' votes to 'stale'")
    set_all_stale = SubmitField("Set all votes to 'stale'")
    resolve_all = SubmitField("Set all 'blocked' votes to 'resolved'")
    update = SubmitField("Set selected votes to 'resolved'")
    set_all_read = SubmitField("Set all notes to read")


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


@cfp_review.route('/anonymisation')
@anon_required
def anonymisation():
    proposals = Proposal.query.filter_by(state='checked').all()

    sort_dict = get_proposal_sort_dict(request.args)
    proposals.sort(**sort_dict)

    non_sort_query_string = dict(request.args)
    if 'sort_by' in non_sort_query_string:
        del non_sort_query_string['sort_by']

    if 'reverse' in non_sort_query_string:
        del non_sort_query_string['reverse']

    return render_template('cfp_review/anonymise_list.html', proposals=proposals,
                           new_qs=non_sort_query_string)


class AnonymiseProposalForm(Form):
    title = StringField('Title', [Required()])
    description = TextAreaField('Description', [Required()])
    anonymise = SubmitField('Send to review and go to next')
    reject = SubmitField('I cannot anonymise this proposal')


@cfp_review.route('/anonymisation/<int:proposal_id>', methods=['GET', 'POST'])
@anon_required
def anonymise_proposal(proposal_id):
    prop = Proposal.query.get_or_404(proposal_id)
    if prop.state in ['new', 'edit', 'locked']:
        # Make sure people only see proposals that are ready
        return abort(404)

    next_prop = get_next_proposal_to(prop, 'checked')
    form = AnonymiseProposalForm()

    if prop.state == 'checked' and form.validate_on_submit():
        if form.reject.data:
            prop.set_state('anon-blocked')
            prop.anonymiser_id = current_user.id
            db.session.commit()
            app.logger.info('Proposal %s cannot be anonymised', proposal_id)

        if form.anonymise.data:
            prop.title = form.title.data
            prop.description = form.description.data
            prop.set_state('anonymised')
            prop.anonymiser_id = current_user.id
            db.session.commit()
            app.logger.info('Sending proposal %s for review', proposal_id)

        if not next_prop:
            return redirect(url_for('.anonymisation'))
        return redirect(url_for('.anonymise_proposal', proposal_id=next_prop.id))


    form.title.data = prop.title
    form.description.data = prop.description

    return render_template('cfp_review/anonymise_proposal.html',
                           proposal=prop, form=form, next_proposal=next_prop)


class ReviewListForm(Form):
    show_proposals = SubmitField("Show me some more proposals")
    reload_proposals = SubmitField("Show some different proposals")

@cfp_review.route('/review', methods=['GET', 'POST'])
@review_required
def review_list():
    form = ReviewListForm()

    if form.validate_on_submit():
        app.logger.info('Clearing review order')
        session['review_order'] = None
        session['review_order_dt'] = datetime.utcnow()
        return redirect(url_for('.review_list'))

    review_order_dt = session.get('review_order_dt')

    last_visit = session.get('review_visit_dt')
    if not last_visit:
        last_vote_cast = CFPVote.query.filter_by(user_id=current_user.id) \
            .order_by(CFPVote.modified.desc()).first()

        if last_vote_cast:
            last_visit = last_vote_cast.modified
            review_order_dt = last_vote_cast.modified

    proposal_query = Proposal.query.filter(Proposal.state == 'anonymised')

    if not current_user.has_permission('admin'):
        # reviewers shouldn't see their own proposals, and don't review installations
        proposal_query = proposal_query.filter(
            Proposal.user_id != current_user.id,
            Proposal.type.in_(['talk', 'workshop']))

    to_review_again = []
    to_review_new = []
    to_review_old = []
    reviewed = []

    user_votes = aliased(CFPVote, CFPVote.query.filter_by(user_id=current_user.id).subquery())

    for proposal, vote in proposal_query.outerjoin(user_votes).with_entities(Proposal, user_votes).all():
        proposal.user_vote = vote
        if vote:
            if vote.state in ['new', 'resolved', 'stale']:
                proposal.is_new = True
                to_review_again.append(proposal)
            else:
                reviewed.append(((vote.state, vote.vote, vote.modified), proposal))
        else:
            # modified doesn't really describe when proposals are "new", but it's near enough
            if last_visit is None or review_order_dt is None or proposal.modified < review_order_dt:
                to_review_old.append(proposal)
            else:
                proposal.is_new = True
                to_review_new.append(proposal)

    reviewed = [p for o, p in sorted(reviewed, reverse=True)]

    review_order = session.get('review_order')
    if review_order is None \
           or not set([p.id for p in to_review_again]).issubset(review_order) \
           or (to_review_new and (last_visit is None or datetime.utcnow() - last_visit > timedelta(hours=1))):

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

        session['review_order'] = [p.id for p in to_review]
        session['review_order_dt'] = last_visit
        session['review_visit_dt'] = datetime.utcnow()

    else:
        # Sort proposals based on the previous review order
        to_review_dict = dict((p.id, p) for p in to_review_again + to_review_new + to_review_old)
        to_review = [to_review_dict[i] for i in session['review_order'] if i in to_review_dict]

        session['review_visit_dt'] = datetime.utcnow()

    return render_template('cfp_review/review_list.html',
                           to_review=to_review, reviewed=reviewed, form=form)

class VoteForm(Form):
    vote_bad = SubmitField('Bad')
    vote_ok = SubmitField('OK')
    vote_excellent = SubmitField('Excellent')

    note = TextAreaField('Message')

    change = SubmitField("I'd like to change my response")
    recuse = SubmitField('I can identify the submitter (do not vote)')
    question = SubmitField('I need more information')

    def validate_note(form, field):
        if not field.data and form.recuse.data:
            raise ValidationError("Please tell us why you're not voting. If you can identify the submitter, please tell us who it is.")
        if not field.data and form.question.data:
            raise ValidationError("Please let us know what's unclear")


@cfp_review.route('/review/<int:proposal_id>', methods=['GET', 'POST'])
@review_required
def review_proposal(proposal_id):
    prop = Proposal.query.get_or_404(proposal_id)

    # Reviewers can only see anonymised proposals that aren't theirs
    # Also, only admin are reviewing installations
    if prop.state != 'anonymised'\
            or prop.user == current_user\
            or (prop.type == 'installation' and
                not current_user.has_permission('admin')):
        return abort(404)

    form = VoteForm()

    review_order = session.get('review_order')
    session['review_visit_dt'] = datetime.utcnow()

    # If the review order is missing redirect to the list to rebuild it
    if review_order is None:
        return redirect(url_for('.review_list'))

    if review_order and proposal_id in review_order:
        index = review_order.index(proposal_id) + 1
        next_id = review_order[index] if index < len(review_order) else None
        remaining = len(review_order)

    else:
        remaining = 0
        next_id = False

    vote = prop.get_user_vote(current_user)

    if form.validate_on_submit():
        # Make a new vote if need-be
        if not vote:
            vote = CFPVote(current_user, prop)
            db.session.add(vote)

        # If there's a note add it (will replace the old one but it's versioned)
        if form.note.data:
            vote.note = form.note.data
            vote.has_been_read = False
        else:
            vote.has_been_read = True

        vote_value = 2 if form.vote_excellent.data else\
                     1 if form.vote_ok.data else\
                     0 if form.vote_bad.data else None

        # Update vote state
        message = 'error'
        if vote_value is not None:
            vote.vote = vote_value
            vote.set_state('voted')
            review_order.remove(prop.id)
            message = 'You voted: ' + (['Bad', 'OK', 'Excellent'][vote_value])

        elif form.recuse.data:
            vote.set_state('recused')
            review_order.remove(prop.id)
            message = 'You declared a conflict of interest'

        elif form.question.data:
            vote.set_state('blocked')
            review_order.remove(prop.id)
            message = 'You requested more information'

        elif form.change.data:
            vote.set_state('resolved')
            message = 'Proposal re-opened for review'
            review_order.insert(0, proposal_id)
            next_id = proposal_id

        flash(message, 'info')
        session['review_order'] = review_order
        db.session.commit()
        if not next_id:
            return redirect(url_for('.review_list'))
        return redirect(url_for('.review_proposal', proposal_id=next_id))

    if vote and vote.note:
        form.note.data = vote.note
    return render_template('cfp_review/review_proposal.html',
                           form=form, proposal=prop, next_id=next_id,
                           previous_vote=vote, remaining=remaining)

class CloseRoundForm(Form):
    min_votes = IntegerField('Minimum number of votes', default=10, validators=[NumberRange(min=1)])
    close_round = SubmitField('Close this round...')
    confirm = SubmitField('Confirm')
    cancel = SubmitField('Cancel')


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

class AcceptanceForm(Form):
    min_score = FloatField('Minimum score for acceptance')
    set_score = SubmitField('Accept Proposals...')
    confirm = SubmitField('Confirm')
    cancel = SubmitField('Cancel')

def send_email_for_proposal(proposal, accepted):
    if accepted:
        app.logger.info('Sending accepted email for proposal %s', proposal.id)
        subject = 'Your EMF proposal "%s" has been accepted!' % proposal.title
        template = 'cfp_review/email/accepted_msg.txt'

    else:
        # If it's not accepted, it can still be accepted in the next round.
        # Send the proposer an email so they don't feel ignored, but only once.
        if proposal.has_rejected_email:
            return

        app.logger.info('Sending not-accepted email for proposal %s', proposal.id)
        proposal.has_rejected_email = True
        subject = 'An update on your EMF %s "%s"' % (proposal.type, proposal.title)
        template = 'cfp_review/email/not_accepted_msg.txt'

    user = proposal.user
    send_template_email(subject, user.email, app.config['CONTENT_EMAIL'],
                        template, user=user, proposal=proposal)


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
                    send_email_for_proposal(prop, accepted=True)

                else:
                    send_email_for_proposal(prop, accepted=False)

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
