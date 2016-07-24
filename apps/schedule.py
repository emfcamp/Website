# encoding=utf-8
import json

from flask import (
    Blueprint, render_template, redirect, url_for, flash,
    request, Response
)
from flask.ext.login import current_user
from icalendar import Calendar, Event

from main import db

from .common import feature_flag
from models.cfp import Proposal, Venue

schedule = Blueprint('schedule', __name__)


def _get_scheduled_proposals():
    proposals = Proposal.query.filter_by(state='finished')\
                              .filter(Proposal.scheduled_time.isnot(None),
                                      Proposal.scheduled_venue.isnot(None))
    return [p.get_schedule_dict() for p in proposals]

@schedule.route('/schedule')
@feature_flag('SCHEDULE')
def main():
    if request.headers.get('Content-Type') == 'application/json':
        return schedule_json()

    if request.headers.get('Content-Type') == 'text/calendar':
        return schedule_ical()

    favourites = [f.id for f in current_user.favourites] if not current_user.is_anonymous()\
                                                         else []

    def add_event(event):
        event['text'] = event['title']
        event['start_date'] = event['start_date'].strftime('%Y-%m-%d %H:%M:00')
        event['end_date'] = event['end_date'].strftime('%Y-%m-%d %H:%M:00')
        event['is_fave'] = event['id'] in favourites
        return event


    # {id:1, text:"Meeting",   start_date:"04/11/2013 14:00",end_date:"04/11/2013 17:00"}
    schedule_data = _get_scheduled_proposals()
    schedule_data = [add_event(e) for e in schedule_data]

    venues = [{'key': v.id, 'label': v.name} for v in Venue.query.all()]

    return render_template('schedule/user_schedule.html', venues=venues,
                            schedule_data=schedule_data)


@schedule.route('/schedule.json')
@feature_flag('SCHEDULE')
def schedule_json():
    def convert_time_to_str(event):
        event['start_date'] = event['start_date'].strftime('%Y-%m-%d %H:%M:00')
        event['end_date'] = event['end_date'].strftime('%Y-%m-%d %H:%M:00')
        return event

    schedule = [convert_time_to_str(p) for p in _get_scheduled_proposals()]

    return Response(json.dumps(schedule), mimetype='application/json')

@schedule.route('/schedule.ical')
@feature_flag('SCHEDULE')
def schedule_ical():
    schedule = _get_scheduled_proposals()
    title = 'EMF 2016'

    cal = Calendar()
    cal.add('summary', title)
    cal.add('X-WR-CALNAME', title)
    cal.add('X-WR-CALDESC', title)
    cal.add('version', '2.0')

    for event in schedule:
        cal_event = Event()
        cal_event.add('uid', event['id'])
        cal_event.add('summary', event['title'])
        cal_event.add('location', event['venue'])
        cal_event.add('dtstart', event['start_date'])
        cal_event.add('dtend', event['end_date'])
        cal.add_component(cal_event)

    return Response(cal.to_ical(), mimetype='text/calendar')

@schedule.route('/line-up')
@feature_flag('SCHEDULE')
def line_up():
    proposals = Proposal.query.filter_by(state='finished').all()

    return render_template('schedule/line-up.html', proposals=proposals)


@schedule.route('/favourites')
@feature_flag('SCHEDULE')
def favourites():
    if current_user.is_anonymous():
        return redirect(url_for('users.login', next=url_for('.favourites')))

    proposals = current_user.favourites

    return render_template('schedule/favourites.html', proposals=proposals)

@schedule.route('/line-up/<int:proposal_id>', methods=['GET', 'POST'])
@feature_flag('SCHEDULE')
def line_up_proposal(proposal_id):
    proposal = Proposal.query.get_or_404(proposal_id)

    if not current_user.is_anonymous():
        is_fave = proposal in current_user.favourites
    else:
        is_fave = False

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

    return render_template('schedule/line-up-proposal.html',
                           proposal=proposal, is_fave=is_fave)
