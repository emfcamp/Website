from apps.schedule.data import ScheduleFilter, _get_schedule_item_dict
from models.content import ScheduleItem


def make_schedule_item(type, attributes_json):
    return ScheduleItem(
        id=1,
        type=type,
        title="Test item",
        names="Test Person",
        pronouns=None,
        description="Test description",
        short_description="Test short description",
        video_privacy="public",
        official_content=True,
        attributes_json=attributes_json,
    )


def test_youth_workshops_are_always_family_friendly(request_context):
    schedule_item = make_schedule_item("familyworkshop", {})

    sid = _get_schedule_item_dict(ScheduleFilter(), schedule_item)

    assert sid["family_friendly"] is True


def test_workshops_use_family_friendly_attribute(request_context):
    schedule_item = make_schedule_item("workshop", {"family_friendly": False})

    sid = _get_schedule_item_dict(ScheduleFilter(), schedule_item)

    assert sid["family_friendly"] is False
