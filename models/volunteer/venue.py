# coding=utf-8
from main import db

class VolunteerVenue(db.Model):
    __tablename__ = 'volunteer_venue'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String, unique=True, index=True)
    mapref = db.Column(db.String)

    def __repr__(self):
        return '<VolunteerVenue {0}>'.format(self.name)

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "mapref": self.mapref,
        }

    @classmethod
    def get_all(cls):
        return cls.query.order_by(VolunteerVenue.id).all()

    @classmethod
    def get_by_id(cls, id):
        return cls.query.get(id)

    @classmethod
    def get_by_name(cls, name):
        return cls.query.filter_by(name=name).one_or_none()



