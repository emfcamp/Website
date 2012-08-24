from main import db
import bcrypt
import flaskext
import os
import base64
from datetime import datetime, timedelta

class Role(db.Model):
    __tablename__ = 'role'
    id          = db.Column(db.Integer, primary_key=True)
    code        = db.Column(db.String, nullable=False, index=True, unique=True)
    name        = db.Column(db.String,  nullable=False)
    wiki_link   = db.Column(db.String,  nullable=False)
    shift_slots = db.relationship('ShiftSlot', lazy='dynamic', backref='role')
    
    def __init__(self, code, name, wiki_link=''):
        self.code = code
        self.name = name
        self.wiki_link = wiki_link
    

class ShiftSlot(db.Model):
    __tablename__ = 'shift_slot'
    id         = db.Column(db.Integer, primary_key=True)
    start_time = db.Column(db.DateTime, nullable=False)
    end_time   = db.Column(db.DateTime, nullable=False)
    minimum    = db.Column(db.Integer,  nullable=False)
    maximum    = db.Column(db.Integer,  nullable=False)
    log        = db.Column(db.String)
    role_id    = db.Column(db.Integer, db.ForeignKey('role.id'), nullable=False)
    shifts     = db.relationship('Shift', lazy='dynamic', backref='shiftslot')
    
    def __init__(self, start_time, minimum, maximum, role_code, log=''):
        if minimum > maximum and maximum != None:
            raise ValueError("minimum %i should be less than maximum %i"%(minimum, maximum))
        self.start_time = start_time
        self.end_time   = start_time + timedelta(hours=3)
        self.minimum    = minimum
        self.maximum    = maximum
        self.log        = log
        # print role_code
        # print Role.query.filter_by(code=role_code).one().id
        self.role_id    =  Role.query.filter_by(code=role_code).one().id
    

class Shift(db.Model):
    __tablename__ = "shift"
    id = db.Column(db.Integer, primary_key=True)
    shift_slot_id = db.Column(db.Integer, db.ForeignKey('shift_slot.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    # states = pending, cancelled, show, no-show
    state = db.Column(db.String, nullable=False, default='pending')
    
    def __init__(self, shift_slot_id, user_id):
        self.shift_slot_id = shift_slot_id
        self.user_id = user_id
        
        
        
