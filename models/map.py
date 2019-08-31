from datetime import datetime

from geoalchemy2 import Geometry
from geoalchemy2.functions import ST_AsEWKT
from sqlalchemy import Index

from main import db


class MapObject(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    owner_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)

    created = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    modified = db.Column(
        db.DateTime, default=datetime.utcnow, nullable=False, onupdate=datetime.utcnow
    )

    name = db.Column(db.String, nullable=False)
    wiki_page = db.Column(db.String)
    geom = db.Column(Geometry("POINT", srid=4326, spatial_index=False))

    owner = db.relationship('User', backref='map_objects')

    @classmethod
    def get_export_data(cls):
        objects = cls.query.with_entities(
            cls.name, cls.wiki_page, ST_AsEWKT(cls.geom)
        )
        data = {
            'public': [
                {
                    'name': obj[0],
                    'wiki_page': obj[1],
                    'location': obj[2]
                }
                for obj in objects
            ]
        }
        return data

Index('ix_map_object_geom', MapObject.geom, postgresql_using='gist')
