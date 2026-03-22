from functools import wraps
from hmac import compare_digest
from typing import ClassVar, cast

from flask import current_app as app
from flask import request
from flask.typing import ResponseReturnValue
from flask_login import current_user
from flask_restful import Resource, abort
from sqlalchemy import select

from main import db, get_or_404
from models import event_year
from models.admin_message import AdminMessage
from models.cfp import SCHEDULE_ITEM_INFOS, Occurrence, ScheduleItem, ScheduleItemType
from models.lottery import LotteryEntry

from . import api


def _require_video_api_key(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if not app.config.get("VIDEO_API_KEY"):
            abort(401)

        auth_header = request.headers.get("authorization", None)
        if not auth_header or not auth_header.startswith("Bearer "):
            abort(401)

        bearer_token = auth_header.removeprefix("Bearer ")
        if not compare_digest(bearer_token, app.config["VIDEO_API_KEY"]):
            abort(401)

        return func(*args, **kwargs)

    return wrapper


class OccurrenceResource(Resource):
    method_decorators: ClassVar = {"patch": [_require_video_api_key]}

    def patch(self, occurrence_id: int) -> ResponseReturnValue:
        if not request.is_json:
            abort(415)
        occurrence: Occurrence = get_or_404(db, Occurrence, occurrence_id)

        payload = request.get_json()
        if not payload:
            abort(400)

        ALLOWED_ATTRIBUTES = {
            "youtube_url",
            "thumbnail_url",
            "c3voc_url",
            "video_recording_lost",
        }
        if set(payload.keys()) - ALLOWED_ATTRIBUTES:
            abort(400)

        for attribute in ALLOWED_ATTRIBUTES:
            if attribute in payload:
                setattr(occurrence, attribute, payload[attribute])

        db.session.commit()

        return {
            "id": occurrence.id,
            "slug": f"{occurrence.schedule_item.id}-{occurrence.occurrence_num}-{occurrence.schedule_item.slug}",
            "youtube_url": occurrence.youtube_url,
            "thumbnail_url": occurrence.thumbnail_url,
            "c3voc_url": occurrence.c3voc_url,
            "video_recording_lost": occurrence.video_recording_lost,
        }


class FavouriteScheduleItem(Resource):
    def get(self, schedule_item_id: int) -> ResponseReturnValue:
        if not current_user.is_authenticated:
            abort(401)

        schedule_item = get_or_404(db, ScheduleItem, schedule_item_id)
        current_state = schedule_item in current_user.favourites

        return {"is_favourite": current_state}

    def put(self, schedule_item_id: int) -> ResponseReturnValue:
        """Put with no data to toggle"""
        if not current_user.is_authenticated:
            abort(401)

        schedule_item = get_or_404(db, ScheduleItem, schedule_item_id)
        current_state = schedule_item in current_user.favourites

        data = request.get_json()
        if data.get("state") is not None:
            new_state = bool(data["state"])
        else:
            new_state = not current_state

        if new_state and not current_state:
            current_user.favourites.append(schedule_item)
        elif current_state and not new_state:
            current_user.favourites.remove(schedule_item)

        db.session.commit()

        return {"is_favourite": new_state}


class UpdateLotteryPreferences(Resource):
    def post(self, schedule_item_type: str) -> ResponseReturnValue:
        if schedule_item_type not in SCHEDULE_ITEM_INFOS:
            abort(400)
        schedule_item_type = cast(ScheduleItemType, schedule_item_type)
        if not SCHEDULE_ITEM_INFOS[schedule_item_type].supports_lottery:
            abort(400)

        if not current_user.is_authenticated:
            abort(401)

        new_order = [int(i) for i in request.get_json()]

        current_entries: dict[int, LotteryEntry] = {
            e.id: e
            for e in db.session.scalars(
                select(LotteryEntry)
                .where(LotteryEntry.state == "entered")
                .where(LotteryEntry.user == current_user)
                .where(
                    LotteryEntry.occurrence.has(
                        Occurrence.schedule_item.has(ScheduleItem.type == schedule_item_type)
                    )
                )
            )
        }

        if len(current_entries) != len(new_order):
            # the entry list has changed
            abort(400)

        for new_rank, e_id in enumerate(new_order):
            entry = current_entries[e_id]
            entry.rank = new_rank

        db.session.commit()

        # return the current version of the preference list
        # FIXME: is defaulting to 0 correct?
        sorted_entries = sorted(current_entries.values(), key=lambda e: e.rank or 0)
        return [e.id for e in sorted_entries]


class OccurrenceC3VOCPublishingWebhook(Resource):
    method_decorators: ClassVar = {"post": [_require_video_api_key]}

    def post(self) -> ResponseReturnValue:
        if not request.is_json:
            abort(415)

        payload = request.get_json()

        try:
            conference = payload["fahrplan"]["conference"]
            occurrence_id = payload["fahrplan"]["id"]

            if not payload["is_master"]:
                # c3voc *should* only send us information about the master
                # encoding getting published. Aborting early ensures we don't
                # accidentially delete video information from the database.
                abort(403, message="The request referenced a non-master video edit, and has been denied.")

            if conference != f"emf{event_year()}":
                abort(
                    422,
                    message="The request did not reference the current event year, and has not been processed.",
                )

            occurrence: Occurrence = get_or_404(db, Occurrence, occurrence_id)

            if payload["voctoweb"]["enabled"]:
                if payload["voctoweb"]["frontend_url"]:
                    c3voc_url = payload["voctoweb"]["frontend_url"]
                    if not c3voc_url.startswith("https://media.ccc.de/"):
                        abort(406, message="voctoweb frontend_url must start with https://media.ccc.de/")
                    app.logger.info(f"C3VOC webhook set c3voc_url for {occurrence.id=} to {c3voc_url}")
                    occurrence.c3voc_url = c3voc_url
                    occurrence.video_recording_lost = False
                else:
                    # This allows c3voc to notify us if videos got depublished
                    # as well. We do not explicitely set 'video_recording_lost'
                    # here because the video might only need fixing audio or
                    # such.
                    app.logger.warning(
                        f"C3VOC webhook cleared c3voc_url for {occurrence.id=}, was {occurrence.c3voc_url}"
                    )
                    occurrence.c3voc_url = None

                if payload["voctoweb"]["thumb_path"]:
                    path = payload["voctoweb"]["thumb_path"]
                    if path.startswith("/static.media.ccc.de"):
                        path = "https://static.media.ccc.de/media" + path[len("/static.media.ccc.de") :]
                    if not path.startswith("https://"):
                        abort(
                            406,
                            message="voctoweb thumb_path must start with https:// or /static.media.ccc.de",
                        )
                    app.logger.info(f"C3VOC webhook set thumbnail_url for {occurrence.id=} to {path}")
                    occurrence.thumbnail_url = path
                else:
                    app.logger.warning(
                        f"C3VOC webhook cleared thumbnail_url for {occurrence.id=}, was {occurrence.thumbnail_url}"
                    )
                    occurrence.thumbnail_url = None

            if payload["youtube"]["enabled"]:
                if payload["youtube"]["urls"]:
                    # Please do not overwrite existing youtube urls
                    youtube_url = payload["youtube"]["urls"][0]
                    if not youtube_url.startswith("https://www.youtube.com/watch"):
                        abort(406, message="youtube url must start with https://www.youtube.com/watch")
                    if not occurrence.youtube_url:
                        # c3voc will send us a list, even though we only have one
                        # video.
                        app.logger.info(
                            f"C3VOC webhook set youtube_url for {occurrence.id=} to {youtube_url}"
                        )
                        occurrence.youtube_url = youtube_url
                        occurrence.video_recording_lost = False
                    elif occurrence.youtube_url not in payload["youtube"]["urls"]:
                        # c3voc sent us some urls, but none of them are matching
                        # the url we have in our database.
                        app.logger.warning(
                            "C3VOC webhook sent youtube urls update without referencing the previously stored value. Ignoring."
                        )
                        app.logger.debug(
                            f"{occurrence.id=} {payload['youtube']['urls']=} {occurrence.youtube_url=}"
                        )
                else:
                    # see comment at c3voc_url above
                    app.logger.warning(
                        f"C3VOC webhook cleared youtube_url for {occurrence.id=}, was {occurrence.youtube_url}"
                    )
                    occurrence.youtube_url = None

            db.session.commit()
        except KeyError as e:
            abort(400, message=f"Missing required field: {e}")

        return "OK", 204


def renderScheduleMessage(message):
    return {"id": message.id, "body": message.message}


class ScheduleMessage(Resource):
    def get(self) -> ResponseReturnValue:
        records = AdminMessage.get_visible_messages()
        messages = list(map(renderScheduleMessage, records))

        return messages


api.add_resource(OccurrenceResource, "/occurrence/<int:occurrence_id>")
api.add_resource(FavouriteScheduleItem, "/schedule-item/<int:schedule_item_id>/favourite")
api.add_resource(ScheduleMessage, "/schedule-messages")
api.add_resource(UpdateLotteryPreferences, "/schedule/lottery/<schedule_item_type>/preferences")
api.add_resource(OccurrenceC3VOCPublishingWebhook, "/occurrence/c3voc-publishing-webhook")
