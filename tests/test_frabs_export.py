from __future__ import absolute_import
import unittest
from StringIO import StringIO
from datetime import datetime
from lxml import etree

from apps.schedule_xml import (
    make_root, add_day, add_room, add_event, get_duration, export_frab
)

_schema = None
def get_frabs_schema():
    global _schema
    if _schema is not None:
        return _schema

    xml_file = open('tests/frabs_schema.xml')
    schema_doc = etree.parse(xml_file)
    _schema = etree.XMLSchema(schema_doc)
    return _schema

class XMLTestCase(unittest.TestCase):
    def test_empty_schema_fails(self):
        empty_root = etree.Element('root')
        schema = get_frabs_schema()

        is_invalid = schema.validate(empty_root)
        assert is_invalid is False

    def test_min_version_is_valid(self):
        root = make_root()
        add_day(root, index=1, date=datetime(2016, 8, 5))

        schema = get_frabs_schema()
        is_valid = schema.validate(root)
        assert is_valid

    def test_simple_room(self):
        root = make_root()
        day = add_day(root, index=1, date=datetime(2016, 8, 5))
        add_room(day, 'the hinterlands')

        schema = get_frabs_schema()
        is_valid = schema.validate(root)
        assert is_valid

    def test_simple_event(self):
        root = make_root()
        day = add_day(root, index=1, date=datetime(2016, 8, 5))
        room = add_room(day, 'the hinterlands')

        event = {
            'id': 1,
            'title': 'The foo bar',
            'description': 'The foo bar',
            'end_date': datetime(2016, 8, 5, 11, 00),
            'start_date': datetime(2016, 8, 5, 10, 30),
        }

        add_event(room, event)

        schema = get_frabs_schema()
        is_valid = schema.validate(root)
        assert is_valid

    def test_export_frab(self):
        events = [{
            'id': 1,
            'title': 'The foo bar',
            'venue': 'here',
            'description': 'The foo bar',
            'end_date': datetime(2016, 8, 5, 11, 00),
            'start_date': datetime(2016, 8, 5, 10, 30),
        }, {
            'id': 2,
            'title': 'The foo bartt',
            'venue': 'There',
            'description': 'The foo bar',
            'end_date': datetime(2016, 8, 5, 11, 00),
            'start_date': datetime(2016, 8, 5, 10, 30),
        }, {
            'id': 3,
            'title': 'The foo bartt2',
            'venue': 'here',
            'type': 'workshop',
            'description': 'The foo bar',
            'end_date': datetime(2016, 8, 6, 11, 00),
            'start_date': datetime(2016, 8, 6, 10, 30),
        }, ]

        frab = export_frab(events)
        frab_doc = etree.parse(StringIO(frab))
        schema = get_frabs_schema()
        is_valid = schema.validate(frab_doc)

        assert is_valid

    def test_get_duration(self):
        start = datetime(2016, 8, 15, 11, 00)
        stop = datetime(2016, 8, 15, 11, 30)
        assert get_duration(start, stop) == '0:30'
        stop = datetime(2016, 8, 15, 11, 05)
        assert get_duration(start, stop) == '0:05'
        stop = datetime(2016, 8, 15, 12, 00)
        assert get_duration(start, stop) == '1:00'

