from flask import abort, request
from flask_login import current_user
from flask_restful import Resource
from geoalchemy2.shape import from_shape, to_shape
from shapely.geometry import Point

from main import db
from models.cfp import Venue
from models.user import User
from models.village import Village, VillageMember

from . import api


def render_village(village: Village):
    return {
        "id": village.id,
        "name": village.name,
        "url": village.url,
        "description": village.description,
        "location": (to_shape(village.location).__geo_interface__ if village.location else None),
    }


class VillagesMap(Resource):
    def get(self):
        features = []
        for obj in Village.query.filter(Village.location.isnot(None)):
            data = obj.__geo_interface__
            if data["properties"].get("description") is not None:
                desc = data["properties"]["description"]
                data["properties"]["description"] = (desc[:230] + "...") if len(desc) > 230 else desc
            features.append(data)
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

        my_villages = Village.query.join(VillageMember)
        if (not current_user.has_permission("villages")) or request.args.get("all") != "true":
            my_villages = my_villages.filter(
                (VillageMember.user == current_user) & (VillageMember.admin.is_(True))
            )

        if request.args.get("placed") == "false":
            my_villages = my_villages.filter(Village.location.is_(None))

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
        # Used to update village location from the map.
        # This only updates location for the moment.
        obj = Village.query.get(id)
        if not obj:
            return abort(404)

        village_admins = (
            User.query.join(VillageMember)
            .filter(VillageMember.village_id == obj.id, VillageMember.admin.is_(True))
            .all()
        )

        if (current_user not in village_admins) and not current_user.has_permission("villages"):
            return abort(403)

        data = request.get_json()

        if "location" not in data:
            return None

        obj.location = from_shape(Point(data["location"]), srid=4326)
        db.session.commit()
        return None


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

api.add_resource(VenuesMap, "/venues.geojson")
