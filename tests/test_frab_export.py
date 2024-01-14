import pytest
from datetime import datetime
from lxml import etree

from apps.schedule import event_tz
from apps.schedule.schedule_xml import (
    make_root,
    add_day,
    add_room,
    add_event,
    get_duration,
    export_frab,
)


def _local_datetime(*args):
    dt = datetime(*args)
    return event_tz.localize(dt)


@pytest.fixture(scope="session")
def frab_schema():
    xml_file = open("tests/frabs_schema.xml")
    schema_doc = etree.parse(xml_file)
    _schema = etree.XMLSchema(schema_doc)
    yield _schema


def test_empty_frab_schema_fails(frab_schema):
    empty_root = etree.Element("root")
    is_invalid = frab_schema.validate(empty_root)
    assert is_invalid is False


def test_min_version_is_valid(frab_schema, request_context):
    root = make_root()
    add_day(
        root,
        index=1,
        start=_local_datetime(2016, 8, 5, 4, 0),
        end=_local_datetime(2016, 8, 6, 4, 0),
    )

    frab_schema.assert_(root)


def test_simple_room(frab_schema, request_context):
    root = make_root()
    day = add_day(
        root,
        index=1,
        start=_local_datetime(2016, 8, 5, 4, 0),
        end=_local_datetime(2016, 8, 6, 4, 0),
    )
    add_room(day, "the hinterlands")

    frab_schema.assert_(root)


def test_simple_event(frab_schema, request_context):
    root = make_root()
    day = add_day(
        root,
        index=1,
        start=_local_datetime(2016, 8, 5, 4, 0),
        end=_local_datetime(2016, 8, 6, 4, 0),
    )
    room = add_room(day, "the hinterlands")

    event = {
        "id": 1,
        "slug": "the-foo-bar",
        "title": "The foo bar",
        "description": "The foo bar",
        "speaker": "Someone",
        "user_id": 123,
        "end_date": _local_datetime(2016, 8, 5, 11, 00),
        "start_date": _local_datetime(2016, 8, 5, 10, 30),
    }

    add_event(room, event)

    frab_schema.assert_(root)


def test_export_frab(frab_schema, request_context):
    events = [
        {
            "id": 1,
            "slug": "the-foo-bar",
            "title": "The foo bar",
            "venue": "here",
            "description": "The foo bar",
            "speaker": "Someone",
            "user_id": 123,
            "end_date": _local_datetime(2016, 8, 5, 11, 00),
            "start_date": _local_datetime(2016, 8, 5, 10, 30),
        },
        {
            "id": 2,
            "slug": "the-foo-bartt",
            "title": "The foo bartt",
            "venue": "There",
            "description": "The foo bar",
            "speaker": "Someone",
            "user_id": 123,
            "end_date": _local_datetime(2016, 8, 5, 11, 00),
            "start_date": _local_datetime(2016, 8, 5, 10, 30),
        },
        {
            "id": 3,
            "slug": "the-foo-bartt2",
            "title": "The foo bartt2",
            "venue": "here",
            "type": "workshop",
            "description": "The foo bar",
            "speaker": "Someone",
            "user_id": 123,
            "end_date": _local_datetime(2016, 8, 6, 11, 00),
            "start_date": _local_datetime(2016, 8, 6, 10, 30),
        },
    ]

    frab = export_frab(events)
    frab_doc = etree.fromstring(frab)

    frab_schema.assert_(frab_doc)


def test_get_duration():
    start = datetime(2016, 8, 15, 11, 0)
    stop = datetime(2016, 8, 15, 11, 30)
    assert get_duration(start, stop) == "0:30"
    stop = datetime(2016, 8, 15, 11, 5)
    assert get_duration(start, stop) == "0:05"
    stop = datetime(2016, 8, 15, 12, 0)
    assert get_duration(start, stop) == "1:00"
