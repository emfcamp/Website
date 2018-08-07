from flask_restful import Resource
from models.map import MapObject
from geoalchemy2.shape import to_shape
import shapely.geometry

from . import api
from .user import UserInfo


class Map(Resource):
    def get(self):
        features = []
        for obj in MapObject.query.all():
            features.append({
                "type": "Feature",
                "geometry": shapely.geometry.mapping(to_shape(obj.geom)),
                "properties": {
                    "name": obj.name,
                    "wiki_page": obj.wiki_page,
                    "owner": api.url_for(UserInfo, user_id=obj.owner.id)
                }
            })
        return {"type": "FeatureCollection",
                "features": features
                }


class MapObjectResource(Resource):
    def get(self, obj_id):
        return {'obj': obj_id}

api.add_resource(Map, '/map')
api.add_resource(MapObjectResource, '/map/<int:obj_id>')
