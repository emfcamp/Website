from main import db
import bcrypt
import flaskext
import os
import base64
from datetime import datetime, timedelta

class Role(db.Model):
    __tablename__ = 'role'
    id         = db.Column(db.Integer, primary_key=True)
    name       = db.Column(db.String,  nullable=False)
    wiki_link  = db.Column(db.String,  nullable=False)
    

class Shift(db.Model):
    __tablename__ = 'shift'
    id = db.Column(db.Integer, primary_key=True)
    start_time = db.Column(db.DateTime, nullable=False)
    end_time   = db.Column(db.DateTime, nullable=False)
    role_id    = db.relationship("role", backref="ticket", cascade='all')

    def __init__(self, email, name):
        self.email = email
        self.name = name

    def set_password(self, password):
        self.password = bcrypt.hashpw(password.encode('utf8'), bcrypt.gensalt())

    def check_password(self, password):
        return bcrypt.hashpw(password.encode('utf8'), self.password) == self.password
