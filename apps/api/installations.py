from flask import url_for
from flask_restful import Resource
from models import event_year
from models.cfp import InstallationProposal
from geoalchemy2.shape import to_shape

from . import api


def render_installation(installation: InstallationProposal):
    return {
        "id": installation.id,
        "name": installation.display_title,
        "url": url_for(
            "schedule.item",
            year=event_year(),
            proposal_id=installation.id,
            _external=True,
        ),
        "description": installation.published_description,
        "location": to_shape(installation.scheduled_venue.location).__geo_interface__
        if installation.scheduled_venue and installation.scheduled_venue.location
        else None,
    }


class Installations(Resource):
    def get(self):
        result = []
        proposals = InstallationProposal.query.filter(
            InstallationProposal.state.in_(["accepted", "finished"])
        ).all()
        for proposal in proposals:
            result.append(render_installation(proposal))
        return result


api.add_resource(Installations, "/installations")
