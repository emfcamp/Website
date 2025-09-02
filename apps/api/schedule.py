from functools import wraps
from hmac import compare_digest
from typing import ClassVar

from flask import current_app as app
from flask import request
from flask_login import current_user
from flask_restful import Resource, abort

from main import db, get_or_404
from models import event_year
from models.admin_message import AdminMessage
from models.cfp import Proposal
from models.event_tickets import EventTicket

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


class ProposalResource(Resource):
    method_decorators: ClassVar = {"patch": [_require_video_api_key]}

    def patch(self, proposal_id):
        if not request.is_json:
            abort(415)
        proposal = get_or_404(db, Proposal, proposal_id)

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
                setattr(proposal, attribute, payload[attribute])

        db.session.commit()

        return {
            "id": proposal.id,
            "slug": proposal.slug,
            "youtube_url": proposal.youtube_url,
            "thumbnail_url": proposal.thumbnail_url,
            "c3voc_url": proposal.c3voc_url,
            "video_recording_lost": proposal.video_recording_lost,
        }


class FavouriteProposal(Resource):
    def get(self, proposal_id):
        if not current_user.is_authenticated:
            abort(401)

        proposal = get_or_404(db, Proposal, proposal_id)
        current_state = proposal in current_user.favourites

        return {"is_favourite": current_state}

    def put(self, proposal_id):
        """Put with no data to toggle"""
        if not current_user.is_authenticated:
            abort(401)

        proposal = get_or_404(db, Proposal, proposal_id)
        current_state = proposal in current_user.favourites

        data = request.get_json()
        if data.get("state") is not None:
            new_state = bool(data["state"])
        else:
            new_state = not current_state

        if new_state and not current_state:
            current_user.favourites.append(proposal)
        elif current_state and not new_state:
            current_user.favourites.remove(proposal)

        db.session.commit()

        return {"is_favourite": new_state}


class UpdateLotteryPreferences(Resource):
    def post(self, proposal_type):
        if proposal_type not in ["workshop", "youthworkshop"]:
            abort(400)

        if not current_user.is_authenticated:
            abort(401)

        new_order = [int(i) for i in request.get_json()]

        current_tickets = {
            t.id: t
            for t in EventTicket.query.filter_by(state="entered-lottery", user_id=current_user.id).all()
            if t.proposal.type == proposal_type
        }

        if len(current_tickets) != len(new_order):
            # the ticket lists don't match
            abort(400)

        for new_rank, t_id in enumerate(new_order):
            ticket = current_tickets[t_id]
            ticket.rank = new_rank

        db.session.commit()

        res = sorted(current_tickets.values(), key=lambda t: t.rank)

        # return the curret version of the preference list
        return [t.id for t in res]


class ProposalC3VOCPublishingWebhook(Resource):
    method_decorators: ClassVar = {"post": [_require_video_api_key]}

    def post(self):
        if not request.is_json:
            abort(415)

        payload = request.get_json()

        try:
            conference = payload["fahrplan"]["conference"]
            proposal_id = payload["fahrplan"]["id"]

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

            proposal = get_or_404(db, Proposal, proposal_id)

            if payload["voctoweb"]["enabled"]:
                if payload["voctoweb"]["frontend_url"]:
                    c3voc_url = payload["voctoweb"]["frontend_url"]
                    if not c3voc_url.startswith("https://media.ccc.de/"):
                        abort(406, message="voctoweb frontend_url must start with https://media.ccc.de/")
                    app.logger.info(f"C3VOC webhook set c3voc_url for {proposal.id=} to {c3voc_url}")
                    proposal.c3voc_url = c3voc_url
                    proposal.video_recording_lost = False
                else:
                    # This allows c3voc to notify us if videos got depublished
                    # as well. We do not explicitely set 'video_recording_lost'
                    # here because the video might only need fixing audio or
                    # such.
                    app.logger.warning(
                        f"C3VOC webhook cleared c3voc_url for {proposal.id=}, was {proposal.c3voc_url}"
                    )
                    proposal.c3voc_url = None

                if payload["voctoweb"]["thumb_path"]:
                    path = payload["voctoweb"]["thumb_path"]
                    if path.startswith("/static.media.ccc.de"):
                        path = "https://static.media.ccc.de/media" + path[len("/static.media.ccc.de") :]
                    if not path.startswith("https://"):
                        abort(
                            406,
                            message="voctoweb thumb_path must start with https:// or /static.media.ccc.de",
                        )
                    app.logger.info(f"C3VOC webhook set thumbnail_url for {proposal.id=} to {path}")
                    proposal.thumbnail_url = path
                else:
                    app.logger.warning(
                        f"C3VOC webhook cleared thumbnail_url for {proposal.id=}, was {proposal.thumbnail_url}"
                    )
                    proposal.thumbnail_url = None

            if payload["youtube"]["enabled"]:
                if payload["youtube"]["urls"]:
                    # Please do not overwrite existing youtube urls
                    youtube_url = payload["youtube"]["urls"][0]
                    if not youtube_url.startswith("https://www.youtube.com/watch"):
                        abort(406, message="youtube url must start with https://www.youtube.com/watch")
                    if not proposal.youtube_url:
                        # c3voc will send us a list, even though we only have one
                        # video.
                        app.logger.info(f"C3VOC webhook set youtube_url for {proposal.id=} to {youtube_url}")
                        proposal.youtube_url = youtube_url
                        proposal.video_recording_lost = False
                    elif proposal.youtube_url not in payload["youtube"]["urls"]:
                        # c3voc sent us some urls, but none of them are matching
                        # the url we have in our database.
                        app.logger.warning(
                            "C3VOC webhook sent youtube urls update without referencing the previously stored value. Ignoring."
                        )
                        app.logger.debug(
                            f"{proposal.id=} {payload['youtube']['urls']=} {proposal.youtube_url=}"
                        )
                else:
                    # see comment at c3voc_url above
                    app.logger.warning(
                        f"C3VOC webhook cleared youtube_url for {proposal.id=}, was {proposal.youtube_url}"
                    )
                    proposal.youtube_url = None

            db.session.commit()
        except KeyError as e:
            abort(400, message=f"Missing required field: {e}")

        return "OK", 204


def renderScheduleMessage(message):
    return {"id": message.id, "body": message.message}


class ScheduleMessage(Resource):
    def get(self):
        records = AdminMessage.get_visible_messages()
        messages = list(map(renderScheduleMessage, records))

        return messages


api.add_resource(ProposalResource, "/proposal/<int:proposal_id>")
api.add_resource(FavouriteProposal, "/proposal/<int:proposal_id>/favourite")
api.add_resource(ScheduleMessage, "/schedule_messages")
api.add_resource(UpdateLotteryPreferences, "/schedule/tickets/<proposal_type>/preferences")
api.add_resource(ProposalC3VOCPublishingWebhook, "/proposal/c3voc-publishing-webhook")
