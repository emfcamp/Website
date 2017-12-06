import base64
import hmac
import hashlib
from datetime import datetime, timedelta
import time
import struct

from sqlalchemy import func
from sqlalchemy.orm.exc import NoResultFound
from flask import current_app as app
from flask_login import UserMixin

from main import db
from .permission import UserPermission, Permission

CHECKIN_CODE_LEN = 16
checkin_code_re = r'[0-9a-zA-Z_-]{%s}' % CHECKIN_CODE_LEN


def generate_hmac_msg(prefix, key, timestamp, uid):
    """ Note: this outputs bytes because you need to check it with hmac.compare_digest """
    if isinstance(uid, bytes):
        uid = uid.decode('utf-8')

    if isinstance(key, str):
        key = key.encode('utf-8')

    if isinstance(prefix, str):
        prefix = prefix.encode('utf-8')

    msg = ("%s-%s" % (int(timestamp), uid)).encode('utf-8')
    mac = hmac.new(key, prefix + msg, digestmod=hashlib.sha256)
    # Truncate the digest to 20 base64 bytes
    return msg + b"-" + base64.urlsafe_b64encode(mac.digest())[:20]


def generate_login_code(key, timestamp, uid):
    """ Note: this outputs bytes because you need to check it with hmac.compare_digest"""
    return generate_hmac_msg('login-', key, timestamp, uid)


def generate_sso_code(key, timestamp, uid):
    return generate_hmac_msg('sso-', key, timestamp, uid)


def verify_login_code(key, current_timestamp, code):
    if isinstance(code, str):
        code = code.encode('utf-8')

    try:
        timestamp, uid, _ = code.split(b"-", 2)
    except ValueError:
        return None

    login_code = generate_login_code(key, timestamp, uid)
    if hmac.compare_digest(login_code, code):
        age = datetime.fromtimestamp(current_timestamp) - datetime.fromtimestamp(int(timestamp))
        if age > timedelta(hours=6):
            return None
        else:
            return int(uid)
    return None


def generate_checkin_code(key, user_id, version=1):
    if isinstance(key, str):
        key = key.encode('utf-8')
    # H = short (< 65536), B = byte (< 256)
    msg = struct.pack('HB', user_id, version)
    mac = hmac.new(key, b'checkin-' + msg, digestmod=hashlib.sha256)
    # An input length that's a multiple of 3 ensures no wasted output
    # 9 bytes (72 bits) won't resist offline attacks, so be careful
    code = base64.urlsafe_b64encode(msg + mac.digest()[:9])
    # The output length should be (len(msg) + 9) / 3 * 4
    assert len(code) == CHECKIN_CODE_LEN
    return code


def verify_checkin_code(key, code):
    msg = base64.urlsafe_b64decode(code.encode('utf-8')[:4])
    user_id, version = struct.unpack('HB', msg)
    if version != 1:
        return None

    expected_code = generate_checkin_code(key, user_id, version=version)
    if isinstance(code, str):
        code = code.encode('utf-8')

    if hmac.compare_digest(expected_code, code):
        return user_id
    return None


class User(db.Model, UserMixin):
    __tablename__ = 'user'
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String, unique=True, index=True)
    name = db.Column(db.String, nullable=False, index=True)
    phone = db.Column(db.String, nullable=True)
    will_have_ticket = db.Column(db.Boolean, nullable=False, default=False)  # for CfP filtering
    checkin_note = db.Column(db.String, nullable=True)

    diversity = db.relationship('UserDiversity', uselist=False, backref='user', cascade='all, delete, delete-orphan')
    payments = db.relationship('Payment', lazy='dynamic', backref='user', cascade='all')
    permissions = db.relationship('Permission', backref='user', cascade='all', secondary=UserPermission)
    votes = db.relationship('CFPVote', backref='user', lazy='dynamic')

    proposals = db.relationship('Proposal',
                                primaryjoin='Proposal.user_id == User.id',
                                backref='user', lazy='dynamic',
                                cascade='all, delete, delete-orphan')
    anonymised_proposals = db.relationship('Proposal',
                                           primaryjoin='Proposal.anonymiser_id == User.id',
                                           backref='anonymiser', lazy='dynamic',
                                           cascade='all, delete, delete-orphan')

    messages_from = db.relationship('CFPMessage',
                                    primaryjoin='CFPMessage.from_user_id == User.id',
                                    backref='from_user', lazy='dynamic')

    owned_products = db.relationship('Purchase',
                                     backref='owner', lazy='dynamic',
                                     primaryjoin='Purchase.owner_id == User.id',
                                     cascade='all, delete, delete-orphan')
    purchased_products = db.relationship('Purchase',
                                         backref='purchaser', lazy='dynamic',
                                         primaryjoin='Purchase.purchaser_id == User.id',
                                         cascade='all, delete, delete-orphan')

    transfers_to = db.relationship('PurchaseTransfer',
                                   backref='to_user', lazy='dynamic',
                                   primaryjoin='PurchaseTransfer.to_user_id == User.id',
                                   cascade='all, delete, delete-orphan')
    transfers_from = db.relationship('PurchaseTransfer',
                                     backref='from_user', lazy='dynamic',
                                     primaryjoin='PurchaseTransfer.from_user_id == User.id',
                                     cascade='all, delete, delete-orphan')

    def __init__(self, email, name):
        self.email = email
        self.name = name

    def login_code(self, key):
        return generate_login_code(key, int(time.time()), self.id)

    def sso_code(self, key):
        return generate_sso_code(key, int(time.time()), self.id)

    @property
    def purchased_tickets(self):
        """ This returns all tickets (in all states) bought by the user """
        # return [p for p in self.purchased_products if p.is_ticket]
        return self.purchased_products.filter_by(is_ticket=True)

    @property
    def owned_tickets(self):
        """ This returns all tickets (in all states) bought by the user """
        return [p for p in self.owned_products if p.is_ticket]

    def get_tickets(self):
        return [p for p in self.owned_products if p.is_ticket and p.is_paid_for]

    @property
    def checkin_code(self):
        return generate_checkin_code(app.config.get('SECRET_KEY'), self.id)

    def has_permission(self, name, cascade=True):
        if cascade and name != 'admin' and self.has_permission('admin'):
            return True
        for permission in self.permissions:
            if permission.name == name:
                return True
        return False

    def grant_permission(self, name):
        try:
            perm = Permission.query.filter_by(name=name).one()
        except NoResultFound:
            perm = Permission(name)
            db.session.add(perm)
        self.permissions.append(perm)
        db.session.commit()

    def revoke_permission(self, name):
        for user_perm in self.permissions:
            if user_perm.name == name:
                self.permissions.remove(user_perm)
        db.session.commit()

    def __repr__(self):
        return '<User %s>' % self.email

    @classmethod
    def get_by_email(cls, email):
        return User.query.filter(func.lower(User.email) == func.lower(email)).one_or_none()

    @classmethod
    def does_user_exist(cls, email):
        return bool(User.get_by_email(email))

    @classmethod
    def get_by_code(cls, key, code):
        uid = verify_login_code(key, time.time(), code)
        if uid is None:
            return None

        return User.query.filter_by(id=uid).one()

    @classmethod
    def get_by_checkin_code(cls, key, code):
        uid = verify_checkin_code(key, code)
        if uid is None:
            return None

        return User.query.filter_by(id=uid).one()


class UserDiversity(db.Model):
    __tablename__ = 'diversity'
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, primary_key=True)
    age = db.Column(db.String)
    gender = db.Column(db.String)
    ethnicity = db.Column(db.String)


