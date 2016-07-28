# encoding=utf-8
import json

from flask import (
    Blueprint, render_template, redirect, url_for, flash,
    request, Response, abort,
)
from flask.ext.login import current_user
from jinja2.utils import urlize
from icalendar import Calendar, Event

from main import db

from .common import feature_flag
from models.cfp import Proposal, Venue
from models.ical import ICalSource
from .schedule_xml import export_frab

schedule = Blueprint('schedule', __name__)


def _get_scheduled_proposals():
    schedule = Proposal.query.filter(Proposal.state.in_(['accepted', 'finished']),
                                      Proposal.scheduled_time.isnot(None),
                                      Proposal.scheduled_venue.isnot(None),
                                      Proposal.scheduled_duration.isnot(None)
                                    ).all()

    schedule = [p.get_schedule_dict() for p in schedule]

    ical_sources = ICalSource.query.filter_by(enabled=True).all()

    for source in ical_sources:
        schedule = schedule + source.get_ical_feed()

    return schedule

@schedule.route('/schedule')
@feature_flag('SCHEDULE')
def main():
    if current_user.is_anonymous():
        favourites = []
    else:
        favourites = [f.id for f in current_user.favourites]

    def add_event(event):
        event['text'] = event['title']
        event['description'] = urlize(event['description'])
        event['start_date'] = event['start_date'].strftime('%Y-%m-%d %H:%M:00')
        event['end_date'] = event['end_date'].strftime('%Y-%m-%d %H:%M:00')
        event['is_fave'] = event['id'] in favourites
        event['venue'] = event['venue'].id
        return event

    # {id:1, text:"Meeting",   start_date:"04/11/2013 14:00",end_date:"04/11/2013 17:00"}
    schedule_data = _get_scheduled_proposals()
    venues = set([(e['venue'].id, e['venue'].name) for e in schedule_data])
    venues = [{'key': v[0], 'label': v[1]} for v in venues]
    venues = sorted(venues, key=lambda x: x['label'])

    schedule_data = [add_event(e) for e in schedule_data]

    # venues = [{'key': v.id, 'label': v.name} for v in Venue.query.filter_by().all()] +\
    #          [{'key': v.id, 'label': v.name} for v in ICalSource.query.filter_by(enabled=True).all()]


    return render_template('schedule/user_schedule.html', venues=venues,
                            schedule_data=schedule_data)


@schedule.route('/schedule.json')
@feature_flag('SCHEDULE')
def schedule_json():
    def convert_time_to_str(event):
        event['start_date'] = event['start_date'].strftime('%Y-%m-%d %H:%M:00')
        event['end_date'] = event['end_date'].strftime('%Y-%m-%d %H:%M:00')
        event['venue'] = event['venue'].name
        return event

    schedule = [convert_time_to_str(p) for p in _get_scheduled_proposals()]

    # NB this is JSON in a top-level array (security issue for low-end browsers)
    return Response(json.dumps(schedule), mimetype='application/json')

@schedule.route('/schedule.frab')
@feature_flag('SCHEDULE')
def schedule_frab():
    schedule = export_frab(_get_scheduled_proposals())

    return Response(schedule, mimetype='application/xml')

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
        cal_event.add('location', event['venue'].name)
        cal_event.add('dtstart', event['start_date'])
        cal_event.add('dtend', event['end_date'])
        cal.add_component(cal_event)

    return Response(cal.to_ical(), mimetype='text/calendar')

@schedule.route('/line-up')
@feature_flag('SCHEDULE')
def line_up_redirect():
    return redirect(url_for('.line_up'))

@schedule.route('/line-up/2016')
@feature_flag('SCHEDULE')
def line_up():
    proposals = Proposal.query.filter(Proposal.scheduled_duration.isnot(None)).\
        filter(Proposal.state.in_(['accepted', 'finished'])).\
        filter(Proposal.type.in_(['talk', 'workshop'])).all()

    return render_template('schedule/line-up.html', proposals=proposals)


@schedule.route('/favourites')
@feature_flag('SCHEDULE')
def favourites():
    if current_user.is_anonymous():
        return redirect(url_for('users.login', next=url_for('.favourites')))

    proposals = current_user.favourites

    return render_template('schedule/favourites.html', proposals=proposals)

@schedule.route('/line-up/2016/<int:proposal_id>', methods=['GET', 'POST'])
@feature_flag('SCHEDULE')
def line_up_proposal(proposal_id):
    proposal = Proposal.query.get_or_404(proposal_id)
    if proposal.state not in ('accepted', 'finished'):
        abort(404)

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

    venue_name = None
    if proposal.scheduled_venue:
        venue_name = Venue.query.filter_by(id=proposal.scheduled_venue).one().name

    return render_template('schedule/line-up-proposal.html',
                           proposal=proposal, is_fave=is_fave, venue_name=venue_name)
