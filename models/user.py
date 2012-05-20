from main import db
import random
import bcrypt
import flaskext
import os
import base64
from datetime import datetime, timedelta

safechars = '2346789BCDFGHJKMPQRTVWXY'

class User(db.Model, flaskext.login.UserMixin):
    __tablename__ = 'user'
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String, unique=True)
    name = db.Column(db.String, nullable=False)
    password = db.Column(db.String, nullable=False)
    bankref = db.Column(db.String, nullable=False, unique=True)
    tickets = db.relationship('Ticket', lazy='dynamic', backref='user', cascade='all, delete, delete-orphan')

    def __init__(self, email, name):
        self.email = email
        self.name = name
        # not cryptographic
        bankref = ''.join(random.sample(safechars, 8))
        self.bankref = '%s-%s' % (bankref[:4], bankref[4:])

    def set_password(self, password):
        self.password = bcrypt.hashpw(password, bcrypt.gensalt())

    def check_password(self, password):
        return bcrypt.hashpw(password, self.password) == self.password

class PasswordReset(db.Model):
    __tablename__ = 'password_reset'
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String, nullable=False)
    expires = db.Column(db.DateTime, nullable=False)
    token = db.Column(db.String, nullable=False)

    def __init__(self, email):
        self.email = email
        self.expires = datetime.utcnow() + timedelta(days=1)

    def new_token(self):
        self.token = base64.urlsafe_b64encode(os.urandom(5*3))

    def expired(self):
        return self.expires < datetime.utcnow()

