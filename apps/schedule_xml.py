from lxml import etree
from slugify import slugify_unicode


def get_duration(start_time, end_time):
    # str(timedelta) creates e.g. hrs:min:sec...
    duration = (end_time - start_time).total_seconds() / 60
    hours = int(duration // 60)
    minutes = int(duration % 60)
    return '{0:01d}:{1:02d}'.format(hours, minutes)

def _add_sub_with_text(parent, element, text):
    node = etree.SubElement(parent, element)
    node.text = text
    return node

def make_root():
    root = etree.Element('schedule')

    _add_sub_with_text(root, 'version', '1.0-public')

    conference = etree.SubElement(root, 'conference')

    _add_sub_with_text(conference, 'title', 'Electromagnetic Field 2016')
    _add_sub_with_text(conference, 'acronym', 'EMF2016')
    _add_sub_with_text(conference, 'start', '2016-08-05')
    _add_sub_with_text(conference, 'end', '2016-08-07')
    _add_sub_with_text(conference, 'days', '3')
    _add_sub_with_text(conference, 'timeslot_duration', '00:10')

    return root

def add_day(root, index=0, date=None):
    # Skip the start/end attributes as we'll assume stuff may run all day
    return etree.SubElement(root, 'day', index=str(index), date=date.strftime('%Y-%m-%d'))

def add_room(day, name):
    return etree.SubElement(day, 'room', name=name)

def add_event(room, event):
    event_node = etree.SubElement(room, 'event', id=str(event['id']))
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
    _add_sub_with_text(recording_node, 'optout', 'false' if event['may_record'] else 'true')

def export_frab(schedule):
    root = make_root()
    days_dict = {}
    index = 0

    for event in schedule:
        day_key = event['start_date'].strftime('%Y-%m-%d')
        venue_key = event['venue']

        if day_key not in days_dict:
            index += 1
            node = add_day(root, index=index, date=event['start_date'])
            days_dict[day_key] = {
                'node': node,
                'rooms': {}
            }

        day = days_dict[day_key]

        if venue_key not in day['rooms']:
            day['rooms'][venue_key] = add_room(day['node'], venue_key)

        add_event(day['rooms'][venue_key], event)

    return etree.tostring(root)


