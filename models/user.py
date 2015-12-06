from main import db
from models import exists

from flask.ext.login import UserMixin

import bcrypt
import os
import base64
import hmac
import hashlib
from datetime import datetime, timedelta
from random import choice
import time


def generate_login_code(key, timestamp, uid):
    msg = "%s-%s" % (int(timestamp), uid)
    mac = hmac.new(key, msg, digestmod=hashlib.sha256)
    # Truncate the digest to 20 base64 bytes
    return msg + "-" + base64.urlsafe_b64encode(mac.digest())[:20]


def verify_login_code(key, current_timestamp, code):
    try:
        timestamp, uid, _ = code.split("-", 2)
    except ValueError:
        return None
    if hmac.compare_digest(generate_login_code(key, timestamp, uid), code):
        age = datetime.fromtimestamp(current_timestamp) - datetime.fromtimestamp(int(timestamp))
        if age > timedelta(hours=6):
            return None
        else:
            return int(uid)
    return None


class User(db.Model, UserMixin):
    __tablename__ = 'user'
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String, unique=True, index=True)
    name = db.Column(db.String, nullable=False, index=True)
    password = db.Column(db.String, nullable=False)
    admin = db.Column(db.Boolean, default=False, nullable=False)
    arrivals = db.Column(db.Boolean, default=False, nullable=False)
    phone = db.Column(db.String, nullable=True)
    tickets = db.relationship('Ticket', lazy='dynamic', backref='user', cascade='all, delete, delete-orphan')
    payments = db.relationship('Payment', lazy='dynamic', backref='user', cascade='all')

    transfers_to = db.relationship('TicketTransfer',
                                   primaryjoin='TicketTransfer.to_user_id == User.id',
                                   backref='to_user', lazy='dynamic')
    transfers_from = db.relationship('TicketTransfer',
                                   primaryjoin='TicketTransfer.from_user_id == User.id',
                                   backref='from_user', lazy='dynamic')

    def __init__(self, email, name):
        self.email = email
        self.name = name

    def login_code(self, key):
        return generate_login_code(key, int(time.time()), self.id)

    def set_password(self, password):
        self.password = bcrypt.hashpw(password.encode('utf8'), bcrypt.gensalt())

    def check_password(self, password):
        return bcrypt.hashpw(password.encode('utf8'), self.password) == self.password

    def generate_random_password(self):
        chars = "ABCDEFGHKLMNPRSTUVWXYZ23456789"
        password = ''.join(choice(chars) for _ in range(10))
        self.set_password(password)
        return password

    def __repr__(self):
        return '<User %s>' % self.email

    @classmethod
    def does_user_exist(cls, email):
        return exists(User.query.filter_by(email=email))

    @classmethod
    def get_by_code(cls, key, code):
        uid = verify_login_code(key, time.time(), code)
        if uid is None:
            return None

        return User.query.filter_by(id=uid).one()


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
        self.token = base64.urlsafe_b64encode(os.urandom(5 * 3))

    def expired(self):
        return self.expires < datetime.utcnow()
