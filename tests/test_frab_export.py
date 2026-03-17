from datetime import datetime

import pytest
from lxml import etree

from apps.schedule import event_tz
from apps.schedule.data import OccurrenceDict, ScheduleItemDict
from apps.schedule.schedule_xml import (
    add_day,
    add_event,
    add_room,
    export_frab,
    get_duration,
    make_root,
)


def _local_datetime(*args):
    dt = datetime(*args)
    return event_tz.localize(dt)


@pytest.fixture(scope="session")
def frab_schema():
    with open("tests/frabs_schema.xml") as xml_file:
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
    room_name = "the hinterlands"
    room = add_room(day, room_name)

    flat_sid = ScheduleItemDict(
        id=1,
        type="talk",
        names="Someone",
        pronouns="they/them",
        title="The foo bar",
        description="The foo bar",
        short_description="The foo bar",
        default_video_privacy="public",
        is_fave=False,
        official_content=True,
        slug="the-foo-bar",
        link="https://example.invalid/the-foo-bar",
        occurrences=[
            OccurrenceDict(
                occurrence_num=1,
                start_date=_local_datetime(2016, 8, 5, 10, 30),
                end_date=_local_datetime(2016, 8, 5, 11, 00),
                venue="here",
                latlon=None,
                map_link=None,
                uses_lottery=False,
                video_privacy="public",
                recording_lost=False,
            )
        ],
    )

    add_event(room, room_name, flat_sid)

    frab_schema.assert_(root)


def test_export_frab(frab_schema, request_context):
    flat_sids: list[ScheduleItemDict] = [
        ScheduleItemDict(
            id=1,
            type="talk",
            names="Someone",
            pronouns="they/them",
            title="The foo bar",
            description="The foo bar",
            short_description="The foo bar",
            default_video_privacy="public",
            is_fave=False,
            official_content=True,
            slug="the-foo-bar",
            link="https://example.invalid/the-foo-bar",
            occurrences=[
                OccurrenceDict(
                    occurrence_num=1,
                    start_date=_local_datetime(2016, 8, 5, 10, 30),
                    end_date=_local_datetime(2016, 8, 5, 11, 00),
                    venue="here",
                    latlon=None,
                    map_link=None,
                    uses_lottery=False,
                    video_privacy="public",
                    ccc_url="http://example.com/media.ccc.de",
                    recording_lost=False,
                )
            ],
        ),
        ScheduleItemDict(
            id=2,
            type="talk",
            names="Someone",
            pronouns="they/them",
            title="The foo bartt",
            description="The foo bar",
            short_description="The foo bar",
            default_video_privacy="public",
            is_fave=False,
            official_content=True,
            slug="the-foo-bartt",
            link="https://example.invalid/the-foo-bartt",
            occurrences=[
                OccurrenceDict(
                    occurrence_num=1,
                    start_date=_local_datetime(2016, 8, 5, 10, 30),
                    end_date=_local_datetime(2016, 8, 5, 11, 00),
                    venue="There",
                    latlon=None,
                    map_link=None,
                    uses_lottery=False,
                    video_privacy="public",
                    youtube_url="http://example.com/youtube.com",
                    recording_lost=False,
                )
            ],
        ),
        ScheduleItemDict(
            id=3,
            type="workshop",
            names="Someone",
            pronouns="they/them",
            title="The foo bartt2",
            description="The foo bar",
            short_description="The foo bar",
            default_video_privacy="public",
            is_fave=False,
            official_content=True,
            slug="the-foo-bartt2",
            link="https://example.invalid/the-foo-bartt",
            occurrences=[
                OccurrenceDict(
                    occurrence_num=1,
                    start_date=_local_datetime(2016, 8, 6, 10, 30),
                    end_date=_local_datetime(2016, 8, 6, 11, 00),
                    venue="here",
                    latlon=None,
                    map_link=None,
                    uses_lottery=False,
                    video_privacy="public",
                    ccc_url="http://example.com/media.ccc.de",
                    youtube_url="http://example.com/youtube.com",
                    recording_lost=False,
                )
            ],
        ),
    ]

    frab = export_frab(flat_sids)
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
