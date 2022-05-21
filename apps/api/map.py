from flask_restful import Resource
from models.village import Village
from models.cfp import Venue

from . import api


class VillagesMap(Resource):
    def get(self):
        features = []
        for obj in Village.query.filter(Village.location.isnot(None)):
            features.append(obj.__geo_interface__)
        return {"type": "FeatureCollection", "features": features}


class VenuesMap(Resource):
    def get(self):
        features = []
        for obj in Venue.query.filter(Venue.location.isnot(None)):
            features.append(obj.__geo_interface__)
        return {"type": "FeatureCollection", "features": features}


""" class MapObjectResource(Resource):
    def get(self, obj_id):
        obj = MapObject.query.get(obj_id)
        if not obj:
            return abort(404)
        return render_feature(obj)

    def post(self, obj_id):
        obj = MapObject.query.get(obj_id)
        if not obj:
            return abort(404)

        if obj.owner != current_user:
            return abort(403)

        data = request.get_json()
        validate_map_obj(data)

        if (
            data["name"] != obj.name
            and MapObject.query.filter_by(name=data["name"]).one_or_none()
        ):
            raise BadRequest("Duplicate Name: {}".format(data["name"]))

        obj.name = data.get("name")
        obj.wiki_page = data.get("wiki_page").replace(
            "https://wiki.emfcamp.org/wiki/", ""
        )
        obj.geom = "SRID=4326;POINT({} {})".format(*data["location"])
        db.session.commit()

    def delete(self, obj_id):
        obj = MapObject.query.get(obj_id)
        if not obj:
            return abort(404)

        if obj.owner != current_user:
            return abort(403)

        db.session.delete(obj)
        db.session.commit()
 """

api.add_resource(VillagesMap, "/map/villages")
api.add_resource(VenuesMap, "/map/venues")
# api.add_resource(MapObjectResource, "/map/<int:obj_id>")
