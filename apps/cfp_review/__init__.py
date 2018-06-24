from flask import Blueprint, request, current_app as app
from sqlalchemy import func, or_

from main import mail
from models.cfp import Proposal, CFPMessage, CFPVote, CFP_STATES
from ..common import require_permission

cfp_review = Blueprint('cfp_review', __name__)
admin_required = require_permission('cfp_admin')  # Decorator to require admin permissions
anon_required = require_permission('cfp_anonymiser')
review_required = require_permission('cfp_reviewer')
schedule_required = require_permission('cfp_schedule')

ordered_states = [
    'edit', 'new', 'locked', 'checked', 'rejected', 'cancelled', 'anonymised',
    'anon-blocked', 'manual-review', 'reviewed', 'accepted', 'finished'
]


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
        'duration': lambda p: (p.scheduled_duration or 0)
    }

    sort_by_key = parameters.get('sort_by')
    return {
        'key': sort_keys.get(sort_by_key, sort_keys['state']),
        'reverse': bool(parameters.get('reverse'))
    }


def get_next_proposal_to(prop, state):
    return Proposal.query.filter(
        Proposal.id != prop.id,
        Proposal.state == state,
        Proposal.modified >= prop.modified # ie find something after this one
    ).order_by('modified', 'id').first()


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


from . import base  # noqa: F401
from . import review  # noqa: F401
from . import anonymise  # noqa: F401
