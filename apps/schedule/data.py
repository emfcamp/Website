from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import NotRequired, TypedDict

import pendulum
from flask import request
from flask_login import current_user
from slugify import slugify
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from apps.common import tidy_workshop_cost
from main import db, external_url
from models import event_year
from models.content import Occurrence, ScheduleItem
from models.content.attributes import (
    TalkAttributes,
    WorkshopAttributes,
    YouthWorkshopAttributes,
)
from models.user import User

from . import event_tz


class OccurrenceDict(TypedDict):
    occurrence_num: int
    start_date: datetime
    end_date: datetime
    venue: str
    latlon: str | None
    map_link: str | None
    uses_lottery: bool

    video_privacy: str
    ccc_url: NotRequired[str]
    youtube_url: NotRequired[str]
    preview_image_url: NotRequired[str]
    recording_lost: bool


class ScheduleItemDict(TypedDict):
    id: int
    type: str

    names: str
    pronouns: str | None
    title: str
    description: str
    short_description: str

    default_video_privacy: str
    is_fave: bool
    official_content: bool

    slug: str
    link: str

    # Attributes

    content_note: NotRequired[str | None]

    family_friendly: NotRequired[bool]

    cost: NotRequired[str]
    equipment: NotRequired[str]
    age_range: NotRequired[str]
    attendees: NotRequired[str | None]

    occurrences: list[OccurrenceDict]


@dataclass
class ScheduleFilter:
    venues: Sequence[str] = field(default_factory=list)
    is_favourite: bool = False
    user: User | None = None

    @classmethod
    def from_request(cls):
        return ScheduleFilter(
            venues=request.args.getlist("venue"),
            is_favourite=request.args.get("is_favourite"),
            user=(current_user.is_authenticated and current_user) or None,
        )


def _get_schedule_item_dict(filter: ScheduleFilter, schedule_item: ScheduleItem) -> ScheduleItemDict:
    if filter.user:
        favourites_ids = [f.id for f in filter.user.favourites]
    else:
        favourites_ids = []

    sid = ScheduleItemDict(
        id=schedule_item.id,
        type=schedule_item.type,
        names=schedule_item.names or "",
        pronouns=schedule_item.pronouns,
        title=schedule_item.title,
        description=schedule_item.description or "",
        short_description=schedule_item.short_description or "",
        default_video_privacy=schedule_item.default_video_privacy,
        is_fave=schedule_item.id in favourites_ids,
        official_content=schedule_item.official_content,
        slug=schedule_item.slug,
        link=external_url(
            ".item",
            year=event_year(),
            schedule_item_id=schedule_item.id,
            slug=schedule_item.slug,
        ),
        occurrences=[],
    )
    if isinstance(schedule_item.attributes, WorkshopAttributes | YouthWorkshopAttributes):
        # FIXME: should these be renamed? Should we just dump the attributes dict?
        sid["cost"] = tidy_workshop_cost(schedule_item.attributes.participant_cost or "")
        sid["equipment"] = (schedule_item.attributes.participant_equipment or "").strip()
        sid["age_range"] = (schedule_item.attributes.age_range or "").strip()
        # participant_count is only on proposals

    if isinstance(schedule_item.attributes, TalkAttributes | WorkshopAttributes):
        sid["family_friendly"] = schedule_item.attributes.family_friendly

    if isinstance(schedule_item.attributes, TalkAttributes | WorkshopAttributes | YouthWorkshopAttributes):
        sid["content_note"] = schedule_item.attributes.content_note

    # Occurrences will be added by either get_schedule_item_dicts_flat or get_schedule_item_dict_full
    return sid


def _get_occurrence_dict(filter: ScheduleFilter, occurrence: Occurrence) -> OccurrenceDict:
    assert occurrence.state == "scheduled"

    # We can make these assertions because state == "scheduled"
    assert occurrence.scheduled_venue is not None
    assert occurrence.scheduled_time is not None
    assert occurrence.scheduled_end_time is not None

    od = OccurrenceDict(
        occurrence_num=occurrence.occurrence_num,
        start_date=event_tz.localize(occurrence.scheduled_time),
        end_date=event_tz.localize(occurrence.scheduled_end_time),
        venue=occurrence.scheduled_venue.name,
        latlon=occurrence.scheduled_venue.latlon,
        map_link=occurrence.scheduled_venue.map_link,
        uses_lottery=bool(occurrence.lottery),
        video_privacy=occurrence.video_privacy,
        recording_lost=occurrence.video_recording_lost,
    )

    if occurrence.c3voc_url:
        od["ccc_url"] = occurrence.c3voc_url
    if occurrence.youtube_url:
        od["youtube_url"] = occurrence.youtube_url
    if occurrence.thumbnail_url:
        od["preview_image_url"] = occurrence.thumbnail_url

    return od


def get_schedule_item_dicts_flat(
    filter: ScheduleFilter, schedule_item: ScheduleItem
) -> list[ScheduleItemDict]:
    """
    Returns a list of ScheduleItemDicts, each with one .occurrence that matches the filter
    """
    flat_sids = []

    sid = _get_schedule_item_dict(filter, schedule_item)

    occurrence: Occurrence
    for occurrence in schedule_item.occurrences:
        if occurrence.state != "scheduled":
            continue

        # Safe assertion due to check that state == "scheduled"
        assert occurrence.scheduled_venue is not None

        if filter.venues and occurrence.scheduled_venue.name not in filter.venues:
            continue

        od = _get_occurrence_dict(filter, occurrence)
        # TODO: maybe we should type these differently
        flat_sid = sid.copy()
        flat_sid["occurrences"] = [od]
        flat_sids.append(flat_sid)

    return flat_sids


def get_schedule_item_dict_full(filter: ScheduleFilter, schedule_item: ScheduleItem) -> ScheduleItemDict:
    """
    Returns a ScheduleItemDict with a list of .occurrences that match the filter
    """
    sid = _get_schedule_item_dict(filter, schedule_item)

    occurrence: Occurrence
    for occurrence in schedule_item.occurrences:
        if occurrence.state != "scheduled":
            continue

        # Safe assertion due to check that state == "scheduled"
        assert occurrence.scheduled_venue is not None

        if filter.venues and occurrence.scheduled_venue.name not in filter.venues:
            continue

        od = _get_occurrence_dict(filter, occurrence)
        sid["occurrences"].append(od)

    return sid


def get_schedule_items(filter: ScheduleFilter) -> list[ScheduleItem]:
    query = (
        select(ScheduleItem)
        .where(
            ScheduleItem.state == "published",
            ScheduleItem.occurrences.any(
                Occurrence.state == "scheduled",
            ),
        )
        .options(selectinload(ScheduleItem.occurrences))
    )

    if filter.user and filter.is_favourite:
        query = query.where(ScheduleItem.favourited_by.any(User.id == filter.user.id))

    if filter.venues:
        # Although this excludes schedule items with no matching occurrences,
        # you still need to filter out individual occurrences that don't match.
        # get_schedule_item_dicts_flat and get_schedule_item_dicts_full do this.
        query = query.where(ScheduleItem.occurrences.any(Occurrence.scheduled_venue.in_(filter.venues)))

    schedule_items = list(db.session.scalars(query))
    return schedule_items


def get_upcoming(filter: ScheduleFilter, per_venue_limit: int = 2) -> dict[str, list[ScheduleItemDict]]:
    schedule_items = get_schedule_items(filter)
    flat_sids = [flat_sid for si in schedule_items for flat_sid in get_schedule_item_dicts_flat(filter, si)]

    # TODO: surely now/next could come straight from the DB? I can't believe we need wrangle this structure
    now = pendulum.now(event_tz)  # type: ignore[arg-type]
    flat_sids = [flat_sid for flat_sid in flat_sids if flat_sid["occurrences"][0]["start_date"] > now]
    flat_sids = sorted(flat_sids, key=lambda flat_sid: flat_sid["occurrences"][0]["start_date"])

    _fix_up_times_horribly(flat_sids)
    # We now can't use start_date because it's a str

    venue_sids: dict[str, list[ScheduleItemDict]] = defaultdict(list)
    for flat_sid in flat_sids:
        venue_name = flat_sid["occurrences"][0]["venue"]
        if len(venue_sids[venue_name]) < per_venue_limit:
            venue_sids[venue_name].append(flat_sid)

    # FIXME: do we know no venue names collide when slugified?
    venue_slug_sids = {slugify(k.lower()): v for k, v in venue_sids.items()}
    return venue_slug_sids


def _fix_up_times_horribly(schedule_item_dicts: Sequence[ScheduleItemDict]) -> None:
    # FIXME: WTF is this?

    for sid in schedule_item_dicts:
        for od in sid["occurrences"]:
            # FIXME these fields aren't in the TypedDict definition
            od["start_time"] = od["start_date"].strftime("%H:%M")  # type: ignore
            od["end_time"] = od["end_date"].strftime("%H:%M")  # type: ignore

            # FIXME: and these aren't strings
            od["start_date"] = od["start_date"].strftime("%Y-%m-%d %H:%M:00")  # type: ignore
            od["end_date"] = od["end_date"].strftime("%Y-%m-%d %H:%M:00")  # type: ignore
