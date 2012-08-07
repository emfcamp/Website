from main import db
import bcrypt
import flaskext
import os
import base64
from datetime import datetime, timedelta

# this links each volunteer to the shifts they've volunteered for
volunteer = db.Table('volunteer', 
                  db.Column('user_id',  db.Integer, db.ForeignKey('user.id')),
                  db.Column('shift_id', db.Integer, db.ForeignKey('shift.id')))

class Role(db.Model):
    __tablename__ = 'role'
    id         = db.Column(db.Integer, primary_key=True)
    code       = db.Column(db.Integer, nullable=False, index=True, unique=True)
    name       = db.Column(db.String,  nullable=False)
    wiki_link  = db.Column(db.String,  nullable=False)
    
    def __init__(self, code, name, wiki_link=''):
        self.code = code
        self.name = name
        self.wiki_link = wiki_link
    

class Shift(db.Model):
    __tablename__ = 'shift'
    id         = db.Column(db.Integer, primary_key=True)
    start_time = db.Column(db.DateTime, nullable=False)
    end_time   = db.Column(db.DateTime, nullable=False)
    count      = db.Column(db.Integer,  nullable=False)
    minimum    = db.Column(db.Integer,  nullable=False)
    maximum    = db.Column(db.Integer)
    log        = db.Column(db.String)
    role_id    = db.Column(db.Integer, db.ForeignKey('role.id'), nullable=False)
    # have a dynamic backref 'users' from User via the 'volunteer' table
    
    def __init__(self, start_time, end_time, minimum, maximum, role_id, log=''):
        self.start_time = start_time
        self.end_time = end_time
        self.count = 0
        self.minimum = minimum
        self.maximum = maximum
        self.log = log
        self.role_id = role_id
    
    @classmethod
    def byrole(cls, role):
        return Shift.query.filter_by(role=role).one()
