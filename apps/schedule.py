# encoding=utf-8
from dateutil import parser
import datetime
import json

from flask import (
    Blueprint, render_template, redirect, url_for, flash,
    request, Response
)
from flask.ext.login import current_user
from icalendar import Calendar, Event

from main import db

from .common import feature_flag
from .common.forms import Form
from models.cfp import Proposal

schedule = Blueprint('schedule', __name__)

@schedule.route('/schedule')
@feature_flag('SCHEDULE')
def main():
    if request.headers.get('Content-Type') == 'application/json':
        return schedule_json()

    if request.headers.get('Content-Type') == 'text/calendar':
        return schedule_ical()

    def convert_to_schedulerjs(event):
        start_str = event['slot_datetime']
        start = parser.parse(start_str)
        end = start + datetime.timedelta(minutes=int(event['duration']))
        return {
            'id': event['id'],
            'start_date': start.strftime('%Y-%m-%d %H:%M:00'),
            'end_date': end.strftime('%Y-%m-%d %H:%M:00'),
            'text': event['title'],
        }

    # {id:1, text:"Meeting",   start_date:"04/11/2013 14:00",end_date:"04/11/2013 17:00"}
    schedule_data = _get_schedule()
    schedule_data = map(convert_to_schedulerjs, schedule_data)
    return render_template('schedule/user_schedule.html', schedule_data=schedule_data)


@schedule.route('/schedule.json')
@feature_flag('SCHEDULE')
def schedule_json():
    return Response(json.dumps(_get_schedule()), mimetype='application/json')

@schedule.route('/schedule.ical')
@feature_flag('SCHEDULE')
def schedule_ical():
    schedule = _get_schedule()
    title = 'EMF 2014'

    cal = Calendar()
    cal.add('summary', title)
    cal.add('X-WR-CALNAME', title)
    cal.add('X-WR-CALDESC', title)
    cal.add('version', '2.0')

    for event in schedule:
        start = parser.parse(event['slot_datetime'])
        end = start + datetime.timedelta(minutes=int(event['duration']))
        cal_event = Event()
        cal_event.add('uid', event['id'])
        cal_event.add('summary', event['title'])
        cal_event.add('location', event['venue'])
        cal_event.add('dtstart', start)
        cal_event.add('dtend', end)
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

class FavouriteProposalForm(Form):
    pass

@schedule.route('/line-up/<int:proposal_id>', methods=['GET', 'POST'])
@feature_flag('SCHEDULE')
def line_up_proposal(proposal_id):
    proposal = Proposal.query.get_or_404(proposal_id)
    form = FavouriteProposalForm()

    if not current_user.is_anonymous():
        is_fave = proposal in current_user.favourites
    else:
        is_fave = False

    # Use the form for CSRF token but explicitly check for post requests as
    # an empty form is always valid
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

    return render_template('schedule/line-up-proposal.html', form=form,
                           proposal=proposal, is_fave=is_fave)

def _get_schedule():
    return [{
            "duration": 15,
            "id": 14,
            "slot": 178,
            "slot_datetime": "2014-08-30 17:40:00+00:00",
            "speakers": [ 112 ],
            "time_ranges": [
                {
                    "end": "2014-08-29T20:30:00Z",
                    "start": "2014-08-29T12:00:00Z"
                },
                {
                    "end": "2014-08-30T20:30:00Z",
                    "start": "2014-08-30T10:00:00Z"
                }
            ],
            "title": "The digital democracy dream",
            "valid_venues": [
                1
            ],
            "venue": 1
        },
        {
            "duration": 10,
            "id": 17,
            "slot": 333,
            "slot_datetime": "2014-08-31 19:30:00+00:00",
            "speakers": [ 106 ],
            "time_ranges": [
                {
                    "end": "2014-08-31T20:30:00Z",
                    "start": "2014-08-31T10:00:00Z"
                }
            ],
            "title": "Zo\u00eb Star; Neurotic IoT Machines from an Alternate Reality",
            "valid_venues": [
                1,
                2,
                3
            ],
            "venue": 1
        },
        {
            "duration": 30,
            "id": 18,
            "slot": 15,
            "slot_datetime": "2014-08-29 14:30:00+00:00",
            "speakers": [ 116 ],
            "time_ranges": [
                {
                    "end": "2014-08-29T20:30:00Z",
                    "start": "2014-08-29T12:00:00Z"
                },
                {
                    "end": "2014-08-30T20:30:00Z",
                    "start": "2014-08-30T10:00:00Z"
                },
                {
                    "end": "2014-08-31T20:30:00Z",
                    "start": "2014-08-31T10:00:00Z"
                }
            ],
            "title": "Materials and Makers",
            "valid_venues": [
                1,
                2,
                3
            ],
            "venue": 2
        },
        {
            "duration": 30,
            "id": 20,
            "slot": 187,
            "slot_datetime": "2014-08-30 19:10:00+00:00",
            "speakers": [ 37 ],
            "time_ranges": [
                {
                    "end": "2014-08-29T20:30:00Z",
                    "start": "2014-08-29T12:00:00Z"
                },
                {
                    "end": "2014-08-30T20:30:00Z",
                    "start": "2014-08-30T10:00:00Z"
                },
                {
                    "end": "2014-08-31T20:30:00Z",
                    "start": "2014-08-31T10:00:00Z"
                }
            ],
            "title": "Evading Anti-virus",
            "valid_venues": [
                1,
                2,
                3
            ],
            "venue": 3
        },
        {
            "duration": 45,
            "id": 21,
            "slot": 25,
            "slot_datetime": "2014-08-29 16:10:00+00:00",
            "speakers": [ 80 ],
            "time_ranges": [
                {
                    "end": "2014-08-29T20:30:00Z",
                    "start": "2014-08-29T12:00:00Z"
                },
                {
                    "end": "2014-08-30T20:30:00Z",
                    "start": "2014-08-30T10:00:00Z"
                },
                {
                    "end": "2014-08-31T20:30:00Z",
                    "start": "2014-08-31T10:00:00Z"
                }
            ],
            "title": "Surface Mount Soldering",
            "valid_venues": [
                4
            ],
            "venue": 4
        },
        {
            "duration": 45,
            "id": 22,
            "slot": 189,
            "slot_datetime": "2014-08-30 19:30:00+00:00",
            "speakers": [ 46, 116
            ],
            "time_ranges": [
                {
                    "end": "2014-08-29T20:30:00Z",
                    "start": "2014-08-29T12:00:00Z"
                },
                {
                    "end": "2014-08-30T20:30:00Z",
                    "start": "2014-08-30T10:00:00Z"
                },
                {
                    "end": "2014-08-31T20:30:00Z",
                    "start": "2014-08-31T10:00:00Z"
                }
            ],
            "title": "Futures of Sexual Healthcare and Digital Fabrication",
            "valid_venues": [
                4
            ],
            "venue": 4
        },
        {
            "duration": 75,
            "id": 26,
            "slot": 163,
            "slot_datetime": "2014-08-30 15:10:00+00:00",
            "speakers": [ 26 ],
            "time_ranges": [
                {
                    "end": "2014-08-29T20:30:00Z",
                    "start": "2014-08-29T12:00:00Z"
                },
                {
                    "end": "2014-08-30T20:30:00Z",
                    "start": "2014-08-30T10:00:00Z"
                },
                {
                    "end": "2014-08-31T20:30:00Z",
                    "start": "2014-08-31T10:00:00Z"
                }
            ],
            "title": "InfraRed Communications",
            "valid_venues": [
                4
            ],
            "venue": 4
        },
        {
            "duration": 30,
            "id": 27,
            "slot": 329,
            "slot_datetime": "2014-08-31 18:50:00+00:00",
            "speakers": [ 26 ],
            "time_ranges": [
                {
                    "end": "2014-08-29T20:30:00Z",
                    "start": "2014-08-29T12:00:00Z"
                },
                {
                    "end": "2014-08-30T20:30:00Z",
                    "start": "2014-08-30T10:00:00Z"
                },
                {
                    "end": "2014-08-31T20:30:00Z",
                    "start": "2014-08-31T10:00:00Z"
                }
            ],
            "title": "LaserTag - How Quasar works",
            "valid_venues": [
                1,
                2,
                3
            ],
            "venue": 1
        },
        {
            "duration": 45,
            "id": 30,
            "slot": 44,
            "slot_datetime": "2014-08-29 19:20:00+00:00",
            "speakers": [ 31 ],
            "time_ranges": [
                {
                    "end": "2014-08-29T20:30:00Z",
                    "start": "2014-08-29T12:00:00Z"
                },
                {
                    "end": "2014-08-30T20:30:00Z",
                    "start": "2014-08-30T10:00:00Z"
                },
                {
                    "end": "2014-08-31T20:30:00Z",
                    "start": "2014-08-31T10:00:00Z"
                }
            ],
            "title": "Introduction To Electronic Fashion Workshop",
            "valid_venues": [
                4
            ],
            "venue": 4
        },
        {
            "duration": 10,
            "id": 31,
            "slot": 335,
            "slot_datetime": "2014-08-31 19:50:00+00:00",
            "speakers": [ 94 ],
            "time_ranges": [
                {
                    "end": "2014-08-29T20:30:00Z",
                    "start": "2014-08-29T12:00:00Z"
                },
                {
                    "end": "2014-08-30T20:30:00Z",
                    "start": "2014-08-30T10:00:00Z"
                },
                {
                    "end": "2014-08-31T20:30:00Z",
                    "start": "2014-08-31T10:00:00Z"
                }
            ],
            "title": "DDD: Disney Driven Development",
            "valid_venues": [
                1,
                2,
                3
            ],
            "venue": 3
        },
        {
            "duration": 15,
            "id": 32,
            "slot": 323,
            "slot_datetime": "2014-08-31 17:50:00+00:00",
            "speakers": [ 68 ],
            "time_ranges": [
                {
                    "end": "2014-08-31T20:30:00Z",
                    "start": "2014-08-31T16:00:00Z"
                }
            ],
            "title": "Collaborative Science Fiction Film made at EMF",
            "valid_venues": [
                1,
                2
            ],
            "venue": 1
        },
        {
            "duration": 30,
            "id": 33,
            "slot": 17,
            "slot_datetime": "2014-08-29 14:50:00+00:00",
            "speakers": [ 35 ],
            "time_ranges": [
                {
                    "end": "2014-08-29T20:30:00Z",
                    "start": "2014-08-29T12:00:00Z"
                },
                {
                    "end": "2014-08-30T20:30:00Z",
                    "start": "2014-08-30T10:00:00Z"
                },
                {
                    "end": "2014-08-31T20:30:00Z",
                    "start": "2014-08-31T10:00:00Z"
                }
            ],
            "title": "Miracle cures, superpowers and the zombie apocalypse",
            "valid_venues": [
                1,
                2,
                3
            ],
            "venue": 1
        },
        {
            "duration": 15,
            "id": 34,
            "slot": 313,
            "slot_datetime": "2014-08-31 16:10:00+00:00",
            "speakers": [ 63 ],
            "time_ranges": [
                {
                    "end": "2014-08-29T20:30:00Z",
                    "start": "2014-08-29T12:00:00Z"
                },
                {
                    "end": "2014-08-30T20:30:00Z",
                    "start": "2014-08-30T10:00:00Z"
                },
                {
                    "end": "2014-08-31T20:30:00Z",
                    "start": "2014-08-31T10:00:00Z"
                }
            ],
            "title": "How we spent a year building a spaceship simulator in a caravan",
            "valid_venues": [
                1,
                2,
                3
            ],
            "venue": 3
        },
        {
            "duration": 105,
            "id": 35,
            "slot": 294,
            "slot_datetime": "2014-08-31 13:00:00+00:00",
            "speakers": [ 6 ],
            "time_ranges": [
                {
                    "end": "2014-08-31T18:00:00Z",
                    "start": "2014-08-31T12:00:00Z"
                }
            ],
            "title": "An Introduction to Glitch Art",
            "valid_venues": [
                4
            ],
            "venue": 4
        },
        {
            "duration": 15,
            "id": 40,
            "slot": 285,
            "slot_datetime": "2014-08-31 11:30:00+00:00",
            "speakers": [ 9 ],
            "time_ranges": [
                {
                    "end": "2014-08-29T20:30:00Z",
                    "start": "2014-08-29T12:00:00Z"
                },
                {
                    "end": "2014-08-30T20:30:00Z",
                    "start": "2014-08-30T10:00:00Z"
                },
                {
                    "end": "2014-08-31T20:30:00Z",
                    "start": "2014-08-31T10:00:00Z"
                }
            ],
            "title": "Mesh Your Brain",
            "valid_venues": [
                1,
                2,
                3
            ],
            "venue": 3
        },
        {
            "duration": 15,
            "id": 42,
            "slot": 302,
            "slot_datetime": "2014-08-31 14:20:00+00:00",
            "speakers": [ 87 ],
            "time_ranges": [
                {
                    "end": "2014-08-29T20:30:00Z",
                    "start": "2014-08-29T12:00:00Z"
                },
                {
                    "end": "2014-08-30T20:30:00Z",
                    "start": "2014-08-30T10:00:00Z"
                },
                {
                    "end": "2014-08-31T20:30:00Z",
                    "start": "2014-08-31T10:00:00Z"
                }
            ],
            "title": "Where Games Break",
            "valid_venues": [
                1,
                2,
                3
            ],
            "venue": 1
        },
        {
            "duration": 15,
            "id": 43,
            "slot": 138,
            "slot_datetime": "2014-08-30 11:00:00+00:00",
            "speakers": [ 117 ],
            "time_ranges": [
                {
                    "end": "2014-08-29T20:30:00Z",
                    "start": "2014-08-29T12:00:00Z"
                },
                {
                    "end": "2014-08-30T20:30:00Z",
                    "start": "2014-08-30T10:00:00Z"
                },
                {
                    "end": "2014-08-31T20:30:00Z",
                    "start": "2014-08-31T10:00:00Z"
                }
            ],
            "title": "Why are computers so @#!*, and what can we do about it?",
            "valid_venues": [
                1,
                2,
                3
            ],
            "venue": 1
        },
        {
            "duration": 15,
            "id": 44,
            "slot": 8,
            "slot_datetime": "2014-08-29 13:20:00+00:00",
            "speakers": [ 102 ],
            "time_ranges": [
                {
                    "end": "2014-08-29T20:30:00Z",
                    "start": "2014-08-29T12:00:00Z"
                }
            ],
            "title": "The three main parties railroaded the Data Retention Act through in a week. Where does the fightback begin?",
            "valid_venues": [
                1
            ],
            "venue": 1
        },
        {
            "duration": 30,
            "id": 47,
            "slot": 132,
            "slot_datetime": "2014-08-30 10:00:00+00:00",
            "speakers": [ 97 ],
            "time_ranges": [
                {
                    "end": "2014-08-29T20:30:00Z",
                    "start": "2014-08-29T12:00:00Z"
                },
                {
                    "end": "2014-08-30T20:30:00Z",
                    "start": "2014-08-30T10:00:00Z"
                },
                {
                    "end": "2014-08-31T20:30:00Z",
                    "start": "2014-08-31T10:00:00Z"
                }
            ],
            "title": "Showing keys in public",
            "valid_venues": [
                1,
                2,
                3
            ],
            "venue": 3
        },
        {
            "duration": 10,
            "id": 50,
            "slot": 9,
            "slot_datetime": "2014-08-29 13:30:00+00:00",
            "speakers": [ 40 ],
            "time_ranges": [
                {
                    "end": "2014-08-29T20:30:00Z",
                    "start": "2014-08-29T12:00:00Z"
                },
                {
                    "end": "2014-08-30T20:30:00Z",
                    "start": "2014-08-30T10:00:00Z"
                },
                {
                    "end": "2014-08-31T20:30:00Z",
                    "start": "2014-08-31T10:00:00Z"
                }
            ],
            "title": "Walt Disney World: This was supposed to be the future",
            "valid_venues": [
                1,
                2,
                3
            ],
            "venue": 3
        },
        {
            "duration": 30,
            "id": 51,
            "slot": 4,
            "slot_datetime": "2014-08-29 12:40:00+00:00",
            "speakers": [ 40 ],
            "time_ranges": [
                {
                    "end": "2014-08-29T20:30:00Z",
                    "start": "2014-08-29T12:00:00Z"
                },
                {
                    "end": "2014-08-30T20:30:00Z",
                    "start": "2014-08-30T10:00:00Z"
                },
                {
                    "end": "2014-08-31T20:30:00Z",
                    "start": "2014-08-31T10:00:00Z"
                }
            ],
            "title": "My Container Ship Holiday Slideshow",
            "valid_venues": [
                1,
                2,
                3
            ],
            "venue": 3
        },
        {
            "duration": 45,
            "id": 54,
            "slot": 18,
            "slot_datetime": "2014-08-29 15:00:00+00:00",
            "speakers": [ 29 ],
            "time_ranges": [
                {
                    "end": "2014-08-29T20:30:00Z",
                    "start": "2014-08-29T12:00:00Z"
                },
                {
                    "end": "2014-08-30T20:30:00Z",
                    "start": "2014-08-30T10:00:00Z"
                },
                {
                    "end": "2014-08-31T20:30:00Z",
                    "start": "2014-08-31T10:00:00Z"
                }
            ],
            "title": "Making rope from nettles",
            "valid_venues": [
                4
            ],
            "venue": 4
        },
        {
            "duration": 15,
            "id": 56,
            "slot": 299,
            "slot_datetime": "2014-08-31 13:50:00+00:00",
            "speakers": [ 59 ],
            "time_ranges": [
                {
                    "end": "2014-08-29T20:30:00Z",
                    "start": "2014-08-29T12:00:00Z"
                },
                {
                    "end": "2014-08-30T20:30:00Z",
                    "start": "2014-08-30T10:00:00Z"
                },
                {
                    "end": "2014-08-31T20:30:00Z",
                    "start": "2014-08-31T10:00:00Z"
                }
            ],
            "title": "Not Safe For Work: Industrial Control System Security",
            "valid_venues": [
                1,
                2,
                3
            ],
            "venue": 1
        }]

