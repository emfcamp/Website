from flask import request, jsonify
from flask_login import current_user
from flask_restful import Resource, abort

from . import api
from main import db
from models.cfp import Proposal
from models.ical import CalendarEvent
from models.admin_message import AdminMessage


class FavouriteProposal(Resource):
    def get(self, proposal_id):
        if not current_user.is_authenticated:
            abort(401)

        proposal = Proposal.query.get_or_404(proposal_id)
        current_state = proposal in current_user.favourites

        return {"is_favourite": current_state}

    def put(self, proposal_id):
        """Put with no data to toggle"""
        if not current_user.is_authenticated:
            abort(401)

        proposal = Proposal.query.get_or_404(proposal_id)
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


class FavouriteExternal(Resource):
    def get(self, event_id):
        if not current_user.is_authenticated:
            abort(401)

        event = CalendarEvent.query.get_or_404(event_id)
        current_state = event in current_user.calendar_favourites

        return {"is_favourite": current_state}

    def put(self, event_id):
        """Put with no data to toggle"""
        if not current_user.is_authenticated:
            abort(401)

        event = CalendarEvent.query.get_or_404(event_id)
        current_state = event in current_user.calendar_favourites

        data = request.get_json()
        if data.get("state") is not None:
            new_state = bool(data["state"])
        else:
            new_state = not current_state

        if new_state and not current_state:
            current_user.calendar_favourites.append(event)
        elif current_state and not new_state:
            current_user.calendar_favourites.remove(event)

        db.session.commit()

        return {"is_favourite": new_state}


def renderScheduleMessage(message):
    return {"id": message.id, "body": message.message}


class ScheduleMessage(Resource):
    def get(self):
        records = AdminMessage.get_visible_messages()
        messages = list(map(renderScheduleMessage, records))

        return messages


api.add_resource(FavouriteProposal, "/proposal/<int:proposal_id>/favourite")
api.add_resource(FavouriteExternal, "/external/<int:event_id>/favourite")
api.add_resource(ScheduleMessage, "/schedule_messages")
