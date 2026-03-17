from typing import Any, TypedDict

from flask import url_for
from flask_restful import Resource
from geoalchemy2.shape import to_shape
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from main import db
from models import event_year
from models.cfp import ScheduleItem

from . import api


class InstallationResponse(TypedDict):
    id: int
    name: str
    url: str
    description: str | None
    short_description: str | None
    location: dict[str, Any] | None


def render_installation(schedule_item: ScheduleItem) -> InstallationResponse:
    data: InstallationResponse = {
        "id": schedule_item.id,
        "name": schedule_item.title,
        "url": url_for(
            "schedule.item",
            year=event_year(),
            schedule_item_id=schedule_item.id,
            _external=True,
        ),
        "description": schedule_item.description,
        "short_description": schedule_item.short_description,
        "location": None,
    }
    if schedule_item.occurrences:
        occurrence = schedule_item.occurrences[0]
        if occurrence.scheduled_venue and occurrence.scheduled_venue.location:
            data["location"] = to_shape(occurrence.scheduled_venue.location).__geo_interface__
    return data


class Installations(Resource):
    def get(self):
        result = []
        schedule_items = db.session.execute(
            select(ScheduleItem)
            .where(ScheduleItem.type == "installation")
            .where(ScheduleItem.is_published)
            .options(selectinload(ScheduleItem.occurrences))
        )
        for schedule_item in schedule_items:
            result.append(render_installation(schedule_item))
        return result


api.add_resource(Installations, "/installations")
