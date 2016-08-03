from uuid import uuid5, NAMESPACE_URL
from datetime import time, datetime, timedelta
import pytz

from lxml import etree
from slugify import slugify_unicode

from main import external_url

event_tz = pytz.timezone('Europe/London')


def get_duration(start_time, end_time):
    # str(timedelta) creates e.g. hrs:min:sec...
    duration = (end_time - start_time).total_seconds() / 60
    hours = int(duration // 60)
    minutes = int(duration % 60)
    return '{0:01d}:{1:02d}'.format(hours, minutes)

def get_day_start_end(dt, start_time=time(4, 0)):
    # A day changeover of 4am allows us to have late events.
    # All in local time because that's what people deal in.
    start_date = dt.date()
    if dt.time() < start_time:
        start_date -= timedelta(days=1)

    end_date = start_date + timedelta(days=1)

    start_dt = datetime.combine(start_date, start_time)
    end_dt = datetime.combine(end_date, start_time)

    start_dt = event_tz.localize(start_dt)
    end_dt = event_tz.localize(end_dt)

    return start_dt, end_dt

def _add_sub_with_text(parent, element, text):
    node = etree.SubElement(parent, element)
    node.text = text
    return node

def make_root():
    root = etree.Element('schedule')

    _add_sub_with_text(root, 'version', '1.0-public')

    conference = etree.SubElement(root, 'conference')

    _add_sub_with_text(conference, 'title', 'Electromagnetic Field 2016')
    _add_sub_with_text(conference, 'acronym', 'emf16')
    _add_sub_with_text(conference, 'start', '2016-08-05')
    _add_sub_with_text(conference, 'end', '2016-08-07')
    _add_sub_with_text(conference, 'days', '3')
    _add_sub_with_text(conference, 'timeslot_duration', '00:10')

    return root

def add_day(root, index, start, end):
    # Don't include start because it's not needed
    return etree.SubElement(root, 'day', index=str(index),
                                         date=start.strftime('%Y-%m-%d'),
                                         end=end.isoformat())

def add_room(day, name):
    return etree.SubElement(day, 'room', name=name)

def add_event(room, event):
    url = external_url('schedule.line_up_proposal', proposal_id=event['id'], slug=None)

    event_node = etree.SubElement(room, 'event', id=str(event['id']),
                                                 guid=str(uuid5(NAMESPACE_URL, url)))

    _add_sub_with_text(event_node, 'room', room.attrib['name'])
    _add_sub_with_text(event_node, 'title', event['title'])
    _add_sub_with_text(event_node, 'type', event.get('type', 'talk'))
    _add_sub_with_text(event_node, 'date', event['start_date'].isoformat())

    # Start time
    _add_sub_with_text(event_node, 'start', event['start_date'].strftime('%H:%M'))

    duration = get_duration(event['start_date'], event['end_date'])
    _add_sub_with_text(event_node, 'duration', duration)

    _add_sub_with_text(event_node, 'abstract', event['description'])
    _add_sub_with_text(event_node, 'description', event['description'])

    _add_sub_with_text(event_node, 'slug', 'emf2016-%s-%s' % (event['id'], slugify_unicode(event['title']).lower()))

    _add_sub_with_text(event_node, 'subtitle', '')
    _add_sub_with_text(event_node, 'track', '')

    add_recording(event_node, event)

def add_recording(event_node, event):

    recording_node = etree.SubElement(event_node, 'recording')

    _add_sub_with_text(recording_node, 'license', 'CC BY-SA 3.0')
    _add_sub_with_text(recording_node, 'optout', 'false' if event.get('may_record') else 'true')


def export_frab(schedule):
    root = make_root()
    days_dict = {}
    index = 0

    for event in schedule:
        day_start, day_end = get_day_start_end(event['start_date'])
        day_key = day_start.strftime('%Y-%m-%d')
        venue_key = event['venue']

        if day_key not in days_dict:
            index += 1
            node = add_day(root, index, day_start, day_end)
            days_dict[day_key] = {
                'node': node,
                'rooms': {}
            }

        day = days_dict[day_key]

        if venue_key not in day['rooms']:
            day['rooms'][venue_key] = add_room(day['node'], venue_key)

        add_event(day['rooms'][venue_key], event)

    return etree.tostring(root)


