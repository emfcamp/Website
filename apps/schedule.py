# encoding=utf-8
import json
import cgi
import pytz
import random

from flask import (
    Blueprint, render_template, redirect, url_for, flash,
    request, Response, abort,
)
from flask_login import current_user
from flask import current_app as app
from jinja2.utils import urlize
from icalendar import Calendar, Event
from slugify import slugify_unicode as slugify

from main import db, external_url

from .common import feature_flag, json_response
from models.cfp import Proposal, Venue
from models.ical import CalendarSource, CalendarEvent
from models.user import User, generate_api_token
from models.site_state import event_start
from .schedule_xml import export_frab

schedule = Blueprint('schedule', __name__)

event_tz = pytz.timezone('Europe/London')


def _get_proposal_dict(proposal, favourites_ids):
    res = {
        'id': proposal.id,
        'slug': proposal.slug,
        'start_date': event_tz.localize(proposal.scheduled_time),
        'end_date': event_tz.localize(proposal.end_date),
        'venue': proposal.scheduled_venue.name,
        'latlon': proposal.latlon,
        'map_link': proposal.map_link,
        'title': proposal.display_title,
        'speaker': proposal.published_names or proposal.user.name,
        'user_id': proposal.user.id,
        'description': proposal.published_description or proposal.description,
        'type': proposal.type,
        'may_record': proposal.may_record,
        'is_fave': proposal.id in favourites_ids,
        'source': 'database',
        'link': external_url('.line_up_proposal', proposal_id=proposal.id),
    }
    if proposal.type == 'workshop':
        res['cost'] = proposal.cost
    return res

def _get_ical_dict(event, favourites_ids):
    return {
        'id': -event.id,
        'start_date': event_tz.localize(event.start_dt),
        'end_date': event_tz.localize(event.end_dt),
        'venue': event.location or '(Unknown)',
        'latlon': event.latlon,
        'map_link': event.map_link,
        'title': event.summary,
        'speaker': '',
        'user_id': None,
        'description': event.description,
        'type': 'talk',
        'may_record': False,
        'is_fave': event.id in favourites_ids,
        'source': 'external',
        'link': external_url('.line_up_external', event_id=event.id),
    }

def _get_scheduled_proposals(filter_obj={}, override_user=None):
    if override_user:
        user = override_user
    else:
        user = current_user

    if user.is_anonymous:
        proposal_favourites = external_favourites = []
    else:
        proposal_favourites = [f.id for f in user.favourites]
        external_favourites = [f.id for f in user.calendar_favourites]

    schedule = Proposal.query.filter(Proposal.state.in_(['accepted', 'finished']),
                                      Proposal.scheduled_time.isnot(None),
                                      Proposal.scheduled_venue_id.isnot(None),
                                      Proposal.scheduled_duration.isnot(None)
                                    ).all()

    schedule = [_get_proposal_dict(p, proposal_favourites) for p in schedule]

    ical_sources = CalendarSource.query.filter_by(enabled=True)

    for source in ical_sources:
        for e in source.events:
            d = _get_ical_dict(e, external_favourites)
            # Override venue if we have a venue set on the source
            if source.main_venue:
                d['venue'] = source.main_venue
            else:
                d['venue'] = e.location
            schedule.append(d)

    if 'is_favourite' in filter_obj and filter_obj['is_favourite']:
        schedule = [s for s in schedule if s.get('is_fave', False)]

    if 'venue' in filter_obj:
        schedule = [s for s in schedule if s['venue'] in filter_obj.getlist('venue')]

    return schedule

def _get_priority_sorted_venues(venues_to_allow):
    main_venues = Venue.query.filter().all()
    main_venue_names = [(v.name, 'main', v.priority) for v in main_venues]

    ical_sources = CalendarSource.query.filter_by(enabled=True)
    ical_source_names = [(v.main_venue, 'ical', v.priority) for v in ical_sources]

    # List event venues that are not overridden with zero priority
    for source in ical_sources:
        for e in source.events:
            if not source.main_venue:
                ical_source_names.append((e['location'], 'ical', source.priority))

    res = []
    seen_names = []
    for venue in main_venue_names + ical_source_names:
        name = venue[0]
        if name not in seen_names and name in venues_to_allow:
            seen_names.append(name)
            res.append({
                'key': slugify(name),
                'label': name,
                'source': 'main'if name == 'Workshop 3' else venue[1],
                'order': venue[2]
            })

    res = sorted(res, key=lambda v: (v['source'] != 'ical', v['order']), reverse=True)
    return res

@schedule.route('/schedule')
@feature_flag('SCHEDULE')
def main():
    def add_event(event):
        event['text'] = cgi.escape(event['title'])
        event['description'] = urlize(event['description'])
        event['start_date'] = event['start_date'].strftime('%Y-%m-%d %H:%M:00')
        event['end_date'] = event['end_date'].strftime('%Y-%m-%d %H:%M:00')
        event['venue'] = slugify(event['venue'])
        return event

    # {id:1, text:"Meeting",   start_date:"04/11/2013 14:00",end_date:"04/11/2013 17:00"}
    schedule_data = _get_scheduled_proposals()

    venues_with_events = set([e['venue'] for e in schedule_data])
    venues = _get_priority_sorted_venues(venues_with_events)

    schedule_data = [add_event(e) for e in schedule_data]

    return render_template('schedule/user_schedule.html', venues=venues,
                            schedule_data=schedule_data)


@schedule.route('/schedule.json')
@feature_flag('SCHEDULE')
def schedule_json():
    def convert_time_to_str(event):
        event['start_date'] = event['start_date'].strftime('%Y-%m-%d %H:%M:00')
        event['end_date'] = event['end_date'].strftime('%Y-%m-%d %H:%M:00')
        return event

    schedule = [convert_time_to_str(p) for p in _get_scheduled_proposals(request.args)]

    # NB this is JSON in a top-level array (security issue for low-end browsers)
    return Response(json.dumps(schedule), mimetype='application/json')

@schedule.route('/schedule.frab')
@feature_flag('SCHEDULE')
def schedule_frab():
    schedule = Proposal.query.filter(Proposal.state.in_(['accepted', 'finished']),
                                      Proposal.scheduled_time.isnot(None),
                                      Proposal.scheduled_venue_id.isnot(None),
                                      Proposal.scheduled_duration.isnot(None)
                                    ).order_by(Proposal.scheduled_time).all()

    schedule = [_get_proposal_dict(p, []) for p in schedule]

    frab = export_frab(schedule)

    return Response(frab, mimetype='application/xml')

@schedule.route('/schedule.ical')
@schedule.route('/schedule.ics')
@feature_flag('SCHEDULE')
def schedule_ical():
    schedule = _get_scheduled_proposals(request.args)
    title = 'EMF {}'.format(event_start().year)

    cal = Calendar()
    cal.add('summary', title)
    cal.add('X-WR-CALNAME', title)
    cal.add('X-WR-CALDESC', title)
    cal.add('version', '2.0')

    for event in schedule:
        cal_event = Event()
        cal_event.add('uid', event['id'])
        cal_event.add('summary', event['title'])
        cal_event.add('description', event['description'])
        cal_event.add('location', event['venue'])
        cal_event.add('dtstart', event['start_date'])
        cal_event.add('dtend', event['end_date'])
        cal.add_component(cal_event)

    return Response(cal.to_ical(), mimetype='text/calendar')

@schedule.route('/favourites.json')
@feature_flag('LINEUP')
def favourites_json():
    code = request.args.get('token', None)
    user = None
    if code:
        user = User.get_by_api_token(app.config.get('SECRET_KEY'), str(code))
    if not current_user.is_anonymous:
        user = current_user
    if not user:
        abort(404)

    def convert_time_to_str(event):
        event['start_date'] = event['start_date'].strftime('%Y-%m-%d %H:%M:00')
        event['end_date'] = event['end_date'].strftime('%Y-%m-%d %H:%M:00')
        return event

    schedule = [convert_time_to_str(p) for p in _get_scheduled_proposals(request.args, override_user=user) if p['is_fave']]

    # NB this is JSON in a top-level array (security issue for low-end browsers)
    return Response(json.dumps(schedule), mimetype='application/json')

@schedule.route('/favourites.ical')
@schedule.route('/favourites.ics')
@feature_flag('LINEUP')
def favourites_ical():
    code = request.args.get('token', None)
    user = None
    if code:
        user = User.get_by_api_token(app.config.get('SECRET_KEY'), str(code))
    if not current_user.is_anonymous:
        user = current_user
    if not user:
        abort(404)

    schedule = _get_scheduled_proposals(request.args, override_user=user)
    title = 'EMF {} Favourites for {}'.format(event_start().year, user.name)

    cal = Calendar()
    cal.add('summary', title)
    cal.add('X-WR-CALNAME', title)
    cal.add('X-WR-CALDESC', title)
    cal.add('version', '2.0')

    for event in schedule:
        if not event['is_fave']:
            continue
        cal_event = Event()
        cal_event.add('uid', event['id'])
        cal_event.add('summary', event['title'])
        cal_event.add('description', event['description'])
        cal_event.add('location', event['venue'])
        cal_event.add('dtstart', event['start_date'])
        cal_event.add('dtend', event['end_date'])
        cal.add_component(cal_event)

    return Response(cal.to_ical(), mimetype='text/calendar')

@schedule.route('/line-up')
@feature_flag('LINEUP')
def line_up_redirect():
    return redirect(url_for('.line_up'))

@schedule.route('/line-up/2018')
@feature_flag('LINEUP')
def line_up():
    proposals = Proposal.query.filter(Proposal.scheduled_duration.isnot(None)).\
        filter(Proposal.state.in_(['accepted', 'finished'])).\
        filter(Proposal.type.in_(['talk', 'workshop', 'youthworkshop'])).all()

    # Shuffle the order, but keep it fixed per-user
    # (Because we don't want a bias in starring)
    random.Random(current_user.get_id()).shuffle(proposals)

    externals = CalendarSource.get_enabled_events()

    return render_template('schedule/line-up.html', proposals=proposals, externals=externals)


@schedule.route('/favourites')
@feature_flag('LINEUP')
def favourites():
    if current_user.is_anonymous:
        return redirect(url_for('users.login', next=url_for('.favourites')))

    proposals = current_user.favourites
    externals = current_user.calendar_favourites

    token = generate_api_token(app.config['SECRET_KEY'], current_user.id)

    return render_template('schedule/favourites.html', proposals=proposals, externals=externals, token=token)

@schedule.route('/line-up/2018/<int:proposal_id>', methods=['GET', 'POST'])
@schedule.route('/line-up/2018/<int:proposal_id>-<slug>', methods=['GET', 'POST'])
@feature_flag('LINEUP')
def line_up_proposal(proposal_id, slug=None):
    proposal = Proposal.query.get_or_404(proposal_id)
    if proposal.state not in ('accepted', 'finished'):
        abort(404)

    if not current_user.is_anonymous:
        is_fave = proposal in current_user.favourites
    else:
        is_fave = False

    if (request.method == "POST") and not current_user.is_anonymous:
        if is_fave:
            current_user.favourites.remove(proposal)
            msg = 'Removed "%s" from favourites' % proposal.display_title
        else:
            current_user.favourites.append(proposal)
            msg = 'Added "%s" to favourites' % proposal.display_title
        db.session.commit()
        flash(msg)
        return redirect(url_for('.line_up_proposal', proposal_id=proposal.id, slug=proposal.slug))

    if slug != proposal.slug:
        return redirect(url_for('.line_up_proposal', proposal_id=proposal.id, slug=proposal.slug))

    venue_name = None
    if proposal.scheduled_venue:
        venue_name = proposal.scheduled_venue.name

    return render_template('schedule/line-up-proposal.html',
                           proposal=proposal, is_fave=is_fave, venue_name=venue_name)

@schedule.route('/line-up/2018/<int:proposal_id>.json')
@schedule.route('/line-up/2018/<int:proposal_id>-<slug>.json')
@json_response
@feature_flag('LINEUP')
def line_up_proposal_json(proposal_id, slug=None):
    proposal = Proposal.query.get_or_404(proposal_id)
    if proposal.state not in ('accepted', 'finished'):
        abort(404)

    if not current_user.is_anonymous:
        favourites_ids = [f.id for f in current_user.favourites]
    else:
        favourites_ids = []

    data = _get_proposal_dict(proposal, favourites_ids)

    data['start_date'] = data['start_date'].strftime('%Y-%m-%d %H:%M:%S')
    data['end_date'] = data['end_date'].strftime('%Y-%m-%d %H:%M:%S')
    # Remove unnecessary data for now
    del data['link']
    del data['source']
    del data['id']

    return data


@schedule.route('/line-up/2018/external/<int:event_id>', methods=['GET', 'POST'])
@schedule.route('/line-up/2018/external/<int:event_id>-<slug>', methods=['GET', 'POST'])
@feature_flag('LINEUP')
def line_up_external(event_id, slug=None):
    event = CalendarEvent.query.get_or_404(event_id)

    if not current_user.is_anonymous:
        is_fave = event in current_user.calendar_favourites
    else:
        is_fave = False

    if (request.method == "POST") and not current_user.is_anonymous:
        if is_fave:
            current_user.calendar_favourites.remove(event)
            msg = 'Removed "%s" from favourites' % event.display_title
        else:
            current_user.calendar_favourites.append(event)
            msg = 'Added "%s" to favourites' % event.display_title
        db.session.commit()
        flash(msg)
        return redirect(url_for('.line_up_external', event_id=event.id, slug=event.slug))

    if slug != event.slug:
        return redirect(url_for('.line_up_external', event_id=event.id, slug=event.slug))

    return render_template('schedule/line-up-external.html',
                           event=event, is_fave=is_fave, venue_name=event.venue)
