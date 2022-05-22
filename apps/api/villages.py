from flask import abort, request
from flask_login import current_user
from flask_restful import Resource
from models.village import Village, VillageMember
from models.cfp import Venue
from shapely.geometry import shape
from geoalchemy2.shape import to_shape, from_shape

from main import db
from . import api


def render_village(village: Village):
    return {
        "id": village.id,
        "name": village.name,
        "url": village.url,
        "description": village.description,
        "location": to_shape(village.location).__geo_interface__
        if village.location
        else None,
    }


class VillagesMap(Resource):
    def get(self):
        features = []
        for obj in Village.query.filter(Village.location.isnot(None)):
            features.append(obj.__geo_interface__)
        return {"type": "FeatureCollection", "features": features}


class Villages(Resource):
    def get(self):
        result = []
        for village in Village.query.all():
            result.append(render_village(village))
        return result


class MyVillages(Resource):
    def get(self):
        if not current_user.is_authenticated:
            return abort(404)
        my_villages = (
            Village.query.join(VillageMember)
            .filter((VillageMember.user == current_user))
            .all()
        )
        result = []
        for village in my_villages:
            result.append(render_village(village))
        return result


class VillageResource(Resource):
    def get(self, id):
        village = Village.query.get(id)
        if not village:
            return {"error": "Not found"}, 404
        return render_village(village)

    def post(self, id):
        obj = Village.query.get(id)
        if not obj:
            return abort(404)

        if obj.owner != current_user and not current_user.has_permission("villages"):
            return abort(403)

        data = request.get_json()

        if "location" not in data:
            return

        loc = shape(data["location"])
        obj.location = from_shape(loc)
        db.session.commit()


class VenuesMap(Resource):
    def get(self):
        features = []
        for obj in Venue.query.filter(Venue.location.isnot(None)):
            features.append(obj.__geo_interface__)
        return {"type": "FeatureCollection", "features": features}


api.add_resource(VillagesMap, "/villages.geojson")
api.add_resource(Villages, "/villages")
api.add_resource(MyVillages, "/villages/mine")
api.add_resource(VillageResource, "/villages/<int:id>")
api.add_resource(VenuesMap, "/venues")
