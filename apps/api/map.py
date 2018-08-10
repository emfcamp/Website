from werkzeug.exceptions import BadRequest
from flask import request, abort, redirect
from flask_login import current_user
from flask_restful import Resource
from models.map import MapObject
from geoalchemy2.shape import to_shape
import shapely.geometry

from main import db

from . import api


def render_feature(obj):
    return {
        "id": api.url_for(MapObjectResource, obj_id=obj.id),
        "type": "Feature",
        "geometry": shapely.geometry.mapping(to_shape(obj.geom)),
        "properties": {
            "id": api.url_for(MapObjectResource, obj_id=obj.id),
            "name": obj.name,
            "wiki_page": obj.wiki_page,
            "owner_name": obj.owner.name,
            "owner": "/api/user/{}".format(obj.owner.id)
        },
    }


def validate_map_obj(data):
    for field in ("name", "location"):
        if field not in data:
            raise BadRequest("{} must be provided".format(field))

    if data['name'].strip() == '':
        raise BadRequest("Name must not be blank")


class Map(Resource):
    def get(self):
        features = []
        for obj in MapObject.query.all():
            features.append(render_feature(obj))
        return {"type": "FeatureCollection", "features": features}


class MapObjectResource(Resource):
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

        obj.name = data.get('name')
        obj.wiki_page = data.get('wiki_page').replace('https://wiki.emfcamp.org/wiki/', '')
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


class MapCreateResource(Resource):
    def put(self):
        if not current_user.is_authenticated:
            abort(401)

        data = request.get_json()
        validate_map_obj(data)

        if MapObject.query.filter_by(name=data['name']).one_or_none():
            raise BadRequest("Duplicate Name: {}".format(data['name']))

        obj = MapObject(
            name=data["name"],
            wiki_page=data.get("wiki_page").replace('https://wiki.emfcamp.org/wiki/', ''),
            geom="SRID=4326;POINT({} {})".format(*data["location"]),
            owner=current_user,
        )
        db.session.add(obj)
        db.session.commit()

        return redirect(api.url_for(MapObjectResource, obj_id=obj.id), 303)


api.add_resource(Map, "/map")
api.add_resource(MapObjectResource, "/map/<int:obj_id>")
api.add_resource(MapCreateResource, "/map/create")
