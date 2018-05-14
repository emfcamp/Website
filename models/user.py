import base64
import hmac
import hashlib
import random
import string
from datetime import datetime, timedelta
import time
import struct
import re
from collections import defaultdict

from sqlalchemy import func
from sqlalchemy.orm.exc import NoResultFound
from flask import current_app as app, session
from flask_login import UserMixin, AnonymousUserMixin

from main import db
from loggingmanager import set_user_id
from . import bucketise
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


def verify_hmac_msg(prefix, key, current_timestamp, code, valid_hours):
    if isinstance(code, str):
        code = code.encode('utf-8')

    try:
        timestamp, uid, _ = code.split(b"-", 2)
    except ValueError:
        return None

    expected_code = generate_hmac_msg(prefix, key, timestamp, uid)
    if hmac.compare_digest(expected_code, code):
        age = datetime.fromtimestamp(current_timestamp) - datetime.fromtimestamp(int(timestamp))
        if age > timedelta(hours=valid_hours):
            return None
        else:
            return int(uid)
    return None


def generate_login_code(key, timestamp, uid):
    """ Note: this outputs bytes because you need to check it with hmac.compare_digest"""
    return generate_hmac_msg('login-', key, timestamp, uid)

def generate_sso_code(key, timestamp, uid):
    return generate_hmac_msg('sso-', key, timestamp, uid)

def generate_signup_code(key, timestamp, uid):
    return generate_hmac_msg('signup-', key, timestamp, uid)


def verify_login_code(key, current_timestamp, code):
    return verify_hmac_msg('login-', key, current_timestamp, code, valid_hours=6)

def verify_signup_code(key, current_timestamp, code):
    return verify_hmac_msg('signup-', key, current_timestamp, code, valid_hours=6)


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
    __versioned__ = {}

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String, unique=True, index=True)
    name = db.Column(db.String, nullable=False, index=True)
    phone = db.Column(db.String, nullable=True)
    will_have_ticket = db.Column(db.Boolean, nullable=False, default=False)  # for CfP filtering
    checkin_note = db.Column(db.String, nullable=True)
    # Whether the user has opted in to receive promo emails after this event:
    promo_opt_in = db.Column(db.Boolean, nullable=False, default=False)

    diversity = db.relationship('UserDiversity', uselist=False, backref='user', cascade='all, delete-orphan')
    payments = db.relationship('Payment', lazy='dynamic', backref='user', cascade='all')
    permissions = db.relationship('Permission', backref='user', cascade='all', secondary=UserPermission)
    votes = db.relationship('CFPVote', backref='user', lazy='dynamic')

    proposals = db.relationship('Proposal',
                                primaryjoin='Proposal.user_id == User.id',
                                backref='user', lazy='dynamic',
                                cascade='all, delete-orphan')
    anonymised_proposals = db.relationship('Proposal',
                                           primaryjoin='Proposal.anonymiser_id == User.id',
                                           backref='anonymiser', lazy='dynamic',
                                           cascade='all, delete-orphan')

    messages_from = db.relationship('CFPMessage',
                                    primaryjoin='CFPMessage.from_user_id == User.id',
                                    backref='from_user', lazy='dynamic')

    purchases = db.relationship('Purchase', lazy='dynamic',
                                primaryjoin='Purchase.purchaser_id == User.id')

    owned_purchases = db.relationship('Purchase', lazy='dynamic',
                                      primaryjoin='Purchase.owner_id == User.id')

    owned_tickets = db.relationship('Ticket', lazy='dynamic',
                                      primaryjoin='Ticket.owner_id == User.id')


    transfers_to = db.relationship('PurchaseTransfer',
                                   backref='to_user', lazy='dynamic',
                                   primaryjoin='PurchaseTransfer.to_user_id == User.id',
                                   cascade='all, delete-orphan')
    transfers_from = db.relationship('PurchaseTransfer',
                                     backref='from_user', lazy='dynamic',
                                     primaryjoin='PurchaseTransfer.from_user_id == User.id',
                                     cascade='all, delete-orphan')

    def __init__(self, email, name):
        self.email = email
        self.name = name

    @classmethod
    def get_export_data(cls):
        data = {
            'public': {
                'users': {
                    'count': cls.query.count(),
                },
            },
            'tables': ['user'],
        }

        return data

    def login_code(self, key):
        return generate_login_code(key, int(time.time()), self.id)

    def sso_code(self, key):
        return generate_sso_code(key, int(time.time()), self.id)

    @property
    def checkin_code(self):
        return generate_checkin_code(app.config['SECRET_KEY'], self.id)

    def has_permission(self, name, cascade=True):
        if cascade:
            if name != 'admin' and self.has_permission('admin'):
                return True
            if name.startswith('cfp_') and name != 'cfp_admin' and self.has_permission('cfp_admin'):
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

    def revoke_permission(self, name):
        for user_perm in self.permissions:
            if user_perm.name == name:
                self.permissions.remove(user_perm)

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

    @classmethod
    def get_export_data(cls):
        valid_ages = []
        ages = defaultdict(int)
        sexes = defaultdict(int)
        ethnicities = defaultdict(int)

        for row in cls.query:
            matches = re.findall(r'\b[0-9]{1,3}\b', row.age)
            if matches:
                valid_ages += map(int, matches)
            elif not row.age:
                ages[''] += 1
            else:
                ages['other'] += 1

            # Someone might put "more X than Y" or "both X",
            # but this mostly works. 'other' includes the error rate.
            matches_m = re.findall(r'\b(male|man|m)\b', row.gender, re.I)
            matches_f = re.findall(r'\b(female|woman|f)\b', row.gender, re.I)
            if matches_m or matches_f:
                sexes['male'] += len(matches_m)
                sexes['female'] += len(matches_f)
            elif not row.gender:
                sexes[''] += 1
            else:
                sexes['other'] += 1

            # This is largely junk, because people put jokes or expressions of surprise, which can
            # only reasonably be categorised as "other". Next time, we should use an autocomplete,
            # explain why we're collecting this information, and separate "other" from "unknown".
            matches_white = re.findall(r'\b(white|caucasian|wasp)\b', row.ethnicity, re.I)
            # People really like putting their heritage, which gives another data point or two.
            matches_anglo = re.findall(r'\b(british|english|irish|scottish|welsh|american|australian|canadian|zealand|nz)\b', row.ethnicity, re.I)
            if matches_white or matches_anglo:
                if matches_white and matches_anglo:
                    ethnicities['both'] += 1
                elif matches_white:
                    ethnicities['white'] += 1
                elif matches_anglo:
                    ethnicities['anglosphere'] += 1
            elif not row.ethnicity:
                ethnicities[''] += 1
            else:
                ethnicities['other'] += 1

        ages.update(bucketise(valid_ages, [0, 15, 25, 35, 45, 55, 65]))

        data = {
            'private': {
                'diversity': {
                    'age': ages,
                    'sex': sexes,
                    'ethnicity': ethnicities,
                },
            },
            'tables': ['diversity'],
        }

        return data


class AnonymousUser(AnonymousUserMixin):
    """ An anonymous user - the only persistent item here is the ID
        which is stored in the session.
    """
    def __init__(self, id):
        self.anon_id = id

    def get_id(self):
        return self.anon_id


def load_anonymous_user():
    """ Factory method for anonymous users which stores a user ID in
        the session. This is assigned to `login_manager.anonymous_user`
        in main.py.
    """
    if 'anon_id' in session:
        au = AnonymousUser(session['anon_id'])
    else:
        aid = ''.join(random.choice(string.ascii_lowercase + string.digits)
                      for _ in range(8))
        session['anon_id'] = aid
        au = AnonymousUser(aid)

    set_user_id(au.get_id())
    return au
