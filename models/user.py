from __future__ import annotations
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
from typing import Optional

from sqlalchemy import func, Index, text, Table
from sqlalchemy.ext.associationproxy import association_proxy
from sqlalchemy.orm.exc import NoResultFound
from flask import current_app as app, session
from flask_login import UserMixin, AnonymousUserMixin

from main import db
from loggingmanager import set_user_id
from . import bucketise, BaseModel
from .permission import UserPermission, Permission
from .volunteer.shift import ShiftEntry

CHECKIN_CODE_LEN = 16
checkin_code_re = r"[0-9a-zA-Z_-]{%s}" % CHECKIN_CODE_LEN


def _generate_hmac(prefix, key, msg):
    """
    Generate a keyed HMAC for a unique purpose. You don't want to call this directly.

    This returns bytes because we don't want to assume the encoding of msg.
    """
    if isinstance(key, str):
        key = key.encode("utf-8")

    if isinstance(prefix, str):
        prefix = prefix.encode("utf-8")

    if isinstance(msg, str):
        msg = msg.encode("utf-8")

    mac = hmac.new(key, prefix + msg, digestmod=hashlib.sha256)
    # Truncate the digest to 20 base64 characters (120 bits)
    return msg + b"-" + base64.urlsafe_b64encode(mac.digest())[:20]


def generate_timed_hmac(prefix, key, timestamp, uid):
    """Typical time-limited HMAC used for logins, etc"""
    timestamp = int(timestamp)  # to truncate floating point, not coerce strings
    msg = "{}-{}".format(timestamp, uid)
    return _generate_hmac(prefix, key, msg).decode("ascii")


def generate_unlimited_hmac(prefix, key, uid):
    """Intended for user tokens, long-lived but low-importance"""
    msg = "{}".format(uid)
    return _generate_hmac(prefix, key, msg).decode("ascii")


def verify_timed_hmac(prefix, key, current_timestamp, code, valid_hours):
    # FIXME: this should raise an exception instead of returning None on error
    try:
        timestamp, uid, _ = code.split("-", 2)
        timestamp, uid = int(timestamp), int(uid)
    except ValueError:
        return None

    expected_code = generate_timed_hmac(prefix, key, timestamp, uid)
    if hmac.compare_digest(expected_code, code):
        age = datetime.fromtimestamp(current_timestamp) - datetime.fromtimestamp(
            timestamp
        )
        if age > timedelta(hours=valid_hours):
            return None
        else:
            return uid

    return None


def verify_unlimited_hmac(prefix, key, code):
    # FIXME: this should raise an exception instead of returning None on error
    try:
        uid, _ = code.split("-", 1)
        uid = int(uid)
    except ValueError:
        return None

    expected_code = generate_unlimited_hmac(prefix, key, uid)
    if hmac.compare_digest(expected_code, code):
        return uid
    return None


def generate_unlimited_short_hmac(prefix, key, user_id, version=1):
    if isinstance(key, str):
        key = key.encode("utf-8")

    if isinstance(prefix, str):
        prefix = prefix.encode("utf-8")

    # H = short (< 65536), B = byte (< 256)
    msg = struct.pack("HB", user_id, version)
    mac = hmac.new(key, prefix + msg, digestmod=hashlib.sha256)

    # An input length that's a multiple of 3 ensures no wasted output
    # 9 bytes (72 bits) won't resist offline attacks, so be careful
    code = base64.urlsafe_b64encode(msg + mac.digest()[:9]).decode("ascii")

    # The output length should be (len(msg) + 9) / 3 * 4
    assert len(code) == CHECKIN_CODE_LEN
    return code


def verify_unlimited_short_hmac(prefix, key, code):
    msg = base64.urlsafe_b64decode(code.encode("utf-8")[:4])
    user_id, version = struct.unpack("HB", msg)
    if version != 1:
        return None

    expected_code = generate_unlimited_short_hmac(prefix, key, user_id, version=version)
    if hmac.compare_digest(expected_code, code):
        return user_id
    return None


""" Wrapper functions that you should actually call """


def generate_login_code(key, timestamp, uid):
    return generate_timed_hmac("login-", key, timestamp, uid)


def generate_sso_code(key, timestamp, uid):
    return generate_timed_hmac("sso-", key, timestamp, uid)


def generate_signup_code(key, timestamp, uid):
    return generate_timed_hmac("signup-", key, timestamp, uid)


def generate_api_token(key, uid):
    return generate_unlimited_hmac("api-", key, uid)


def generate_bar_training_token(key, uid):
    return generate_unlimited_hmac("bar-training-", key, uid)


def generate_checkin_code(key, uid, version=1):
    return generate_unlimited_short_hmac("checkin-", key, uid, version=version)


def verify_login_code(key, current_timestamp, code):
    return verify_timed_hmac("login-", key, current_timestamp, code, valid_hours=6)


def verify_sso_code(key, current_timestamp, code):
    return verify_timed_hmac("sso-", key, current_timestamp, code, valid_hours=6)


def verify_signup_code(key, current_timestamp, code):
    return verify_timed_hmac("signup-", key, current_timestamp, code, valid_hours=6)


def verify_api_token(key, uid):
    return verify_unlimited_hmac("api-", key, uid)


def verify_bar_training_token(key, uid):
    return verify_unlimited_hmac("bar-training-", key, uid)


def verify_checkin_code(key, uid):
    return verify_unlimited_short_hmac("checkin-", key, uid)


CFPReviewerTags: Table = db.Table(
    "cfp_reviewer_tags",
    BaseModel.metadata,
    db.Column("user_id", db.Integer, db.ForeignKey("user.id"), primary_key=True),
    db.Column("tag_id", db.Integer, db.ForeignKey("tag.id"), primary_key=True),
)


class User(BaseModel, UserMixin):
    __tablename__ = "user"
    __versioned__ = {"exclude": ["favourites", "calendar_favourites"]}

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String, unique=True, index=True)
    name = db.Column(db.String, nullable=False, index=True)
    company = db.Column(db.String)
    will_have_ticket = db.Column(
        db.Boolean, nullable=False, default=False
    )  # for CfP filtering
    checkin_note = db.Column(db.String, nullable=True)
    # Whether the user has opted in to receive promo emails after this event:
    promo_opt_in = db.Column(db.Boolean, nullable=False, default=False)

    cfp_invite_reason = db.Column(db.String, nullable=True)

    cfp_reviewer_tags = db.relationship(
        "Tag",
        backref="reviewers",
        cascade="all",
        secondary=CFPReviewerTags,
    )

    diversity = db.relationship(
        "UserDiversity", uselist=False, backref="user", cascade="all, delete-orphan"
    )
    shipping = db.relationship(
        "UserShipping", uselist=False, backref="user", cascade="all, delete-orphan"
    )
    payments = db.relationship("Payment", lazy="dynamic", backref="user", cascade="all")
    permissions = db.relationship(
        "Permission",
        backref="user",
        cascade="all",
        secondary=UserPermission,
        lazy="joined",
    )
    votes = db.relationship("CFPVote", backref="user", lazy="dynamic")

    proposals = db.relationship(
        "Proposal",
        primaryjoin="Proposal.user_id == User.id",
        backref="user",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )
    anonymised_proposals = db.relationship(
        "Proposal",
        primaryjoin="Proposal.anonymiser_id == User.id",
        backref="anonymiser",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )

    messages_from = db.relationship(
        "CFPMessage",
        primaryjoin="CFPMessage.from_user_id == User.id",
        backref="from_user",
        lazy="dynamic",
    )

    event_tickets = db.relationship("EventTicket", backref="user", lazy="dynamic")

    purchases = db.relationship(
        "Purchase", lazy="dynamic", primaryjoin="Purchase.purchaser_id == User.id"
    )

    owned_purchases = db.relationship(
        "Purchase", lazy="dynamic", primaryjoin="Purchase.owner_id == User.id"
    )

    owned_tickets = db.relationship(
        "Ticket", lazy="select", primaryjoin="Ticket.owner_id == User.id", viewonly=True
    )

    owned_admission_tickets = db.relationship(
        "AdmissionTicket",
        lazy="select",
        primaryjoin="AdmissionTicket.owner_id == User.id",
        viewonly=True,
    )

    transfers_to = db.relationship(
        "PurchaseTransfer",
        backref="to_user",
        lazy="dynamic",
        primaryjoin="PurchaseTransfer.to_user_id == User.id",
        cascade="all, delete-orphan",
    )
    transfers_from = db.relationship(
        "PurchaseTransfer",
        backref="from_user",
        lazy="dynamic",
        primaryjoin="PurchaseTransfer.from_user_id == User.id",
        cascade="all, delete-orphan",
    )

    village_membership = db.relationship(
        "VillageMember",
        cascade="all, delete-orphan",
        back_populates="user",
        uselist=False,
    )
    village = association_proxy("village_membership", "village")

    def __init__(self, email: str, name: str):
        self.email = email
        self.name = name

    @classmethod
    def get_export_data(cls):
        data = {
            "public": {"users": {"count": cls.query.count()}},
            "tables": ["user"],
            "private": {
                # Volunteer and speaker emails are exported here in order to issue vouchers for the next event
                "volunteer_emails": [u.email for u in User.query.join(ShiftEntry)],
                "speaker_emails": [
                    u.email
                    for u in User.query.join(
                        Proposal, Proposal.user_id == User.id
                    ).filter(Proposal.is_accepted)
                ],
            },
        }

        return data

    @property
    def transferred_tickets(self):
        return [t.purchase for t in self.transfers_from]

    @property
    def is_invited_speaker(self):
        return self.cfp_invite_reason and len(self.cfp_invite_reason.strip()) > 0

    def get_owned_tickets(self, paid=None, type=None):
        "Get tickets owned by a user, filtered by type and payment state."
        for ticket in self.owned_tickets:
            if (
                paid is True
                and not ticket.is_paid_for
                or paid is False
                and ticket.is_paid_for
            ):
                continue
            if type is not None and ticket.type != type:
                continue
            yield ticket

    def login_code(self, key):
        return generate_login_code(key, int(time.time()), self.id)

    def sso_code(self, key):
        return generate_sso_code(key, int(time.time()), self.id)

    @property
    def checkin_code(self):
        return generate_checkin_code(app.config["SECRET_KEY"], self.id)

    @property
    def bar_training_token(self):
        return generate_bar_training_token(app.config["SECRET_KEY"], self.id)

    def has_permission(self, name, cascade=True) -> bool:
        if cascade:
            if name != "admin" and self.has_permission("admin"):
                return True
            if (
                name.startswith("cfp_")
                and name != "cfp_admin"
                and self.has_permission("cfp_admin")
            ):
                return True
        for permission in self.permissions:
            if permission.name == name:
                return True
        return False

    def grant_permission(self, name: str):
        try:
            perm = Permission.query.filter_by(name=name).one()
        except NoResultFound:
            perm = Permission(name)
            db.session.add(perm)
        self.permissions.append(perm)

    def revoke_permission(self, name: str):
        for user_perm in self.permissions:
            if user_perm.name == name:
                self.permissions.remove(user_perm)

    def __repr__(self):
        return "<User %s>" % self.email

    @classmethod
    def get_by_email(cls, email) -> Optional[User]:
        return User.query.filter(
            func.lower(User.email) == func.lower(email)
        ).one_or_none()

    @classmethod
    def does_user_exist(cls, email):
        return bool(User.get_by_email(email))

    @classmethod
    def get_by_code(cls, key, code) -> Optional[User]:
        uid = verify_login_code(key, time.time(), code)
        if uid is None:
            return None

        return User.query.filter_by(id=uid).one()

    @classmethod
    def get_by_checkin_code(cls, key, code) -> Optional[User]:
        uid = verify_checkin_code(key, code)
        if uid is None:
            return None

        return User.query.filter_by(id=uid).one()

    @classmethod
    def get_by_api_token(cls, key, code) -> Optional[User]:
        uid = verify_api_token(key, code)
        if uid is None:
            # FIXME: raise an exception instead of returning None
            return None

        return User.query.filter_by(id=uid).one()

    @classmethod
    def get_by_bar_training_token(cls, code) -> User:
        uid = verify_bar_training_token(app.config["SECRET_KEY"], code)
        if uid is None:
            raise ValueError("Invalid token")

        return User.query.filter_by(id=uid).one()

    @property
    def is_cfp_accepted(self):
        for proposal in self.proposals:
            if proposal.is_accepted:
                return True
        return False


Index("ix_user_email_lower", func.lower(User.email), unique=True)
Index(
    "ix_user_email_tsearch",
    text("to_tsvector('simple', replace(email, '@', ' '))"),
    postgresql_using="gin",
)
Index(
    "ix_user_name_tsearch", text("to_tsvector('simple', name)"), postgresql_using="gin"
)


class UserDiversity(BaseModel):
    __tablename__ = "diversity"
    user_id = db.Column(
        db.Integer, db.ForeignKey("user.id"), nullable=False, primary_key=True
    )
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
            matches = re.findall(r"\b[0-9]{1,3}\b", row.age)
            if matches:
                valid_ages += map(int, matches)
            elif not row.age:
                ages[""] += 1
            else:
                ages["other"] += 1

            # Someone might put "more X than Y" or "both X",
            # but this mostly works. 'other' includes the error rate.
            matches_m = re.findall(r"\b(male|man|m)\b", row.gender, re.I)
            matches_f = re.findall(r"\b(female|woman|f)\b", row.gender, re.I)
            if matches_m or matches_f:
                sexes["male"] += len(matches_m)
                sexes["female"] += len(matches_f)
            elif not row.gender:
                sexes[""] += 1
            else:
                sexes["other"] += 1

            # This is largely junk, because people put jokes or expressions of surprise, which can
            # only reasonably be categorised as "other". Next time, we should use an autocomplete,
            # explain why we're collecting this information, and separate "other" from "unknown".
            matches_white = re.findall(
                r"\b(white|caucasian|wasp)\b", row.ethnicity, re.I
            )
            # People really like putting their heritage, which gives another data point or two.
            matches_anglo = re.findall(
                r"\b(british|english|irish|scottish|welsh|american|australian|canadian|zealand|nz)\b",
                row.ethnicity,
                re.I,
            )
            if matches_white or matches_anglo:
                if matches_white and matches_anglo:
                    ethnicities["both"] += 1
                elif matches_white:
                    ethnicities["white"] += 1
                elif matches_anglo:
                    ethnicities["anglosphere"] += 1
            elif not row.ethnicity:
                ethnicities[""] += 1
            else:
                ethnicities["other"] += 1

        ages.update(bucketise(valid_ages, [0, 15, 25, 35, 45, 55, 65]))

        data = {
            "private": {
                "diversity": {"age": ages, "sex": sexes, "ethnicity": ethnicities}
            },
            "tables": ["diversity"],
        }

        return data


class UserShipping(BaseModel):
    __tablename__ = "shipping"
    user_id = db.Column(
        db.Integer, db.ForeignKey("user.id"), nullable=False, primary_key=True
    )
    name = db.Column(db.String)
    address_1 = db.Column(db.String)
    address_2 = db.Column(db.String)
    town = db.Column(db.String)
    postcode = db.Column(db.String)
    country = db.Column(db.String)


class AnonymousUser(AnonymousUserMixin):
    """An anonymous user - the only persistent item here is the ID
    which is stored in the session.
    """

    def __init__(self, id):
        self.anon_id = id

    def get_id(self):
        return self.anon_id


def load_anonymous_user():
    """Factory method for anonymous users which stores a user ID in
    the session. This is assigned to `login_manager.anonymous_user`
    in main.py.
    """
    if "anon_id" in session:
        au = AnonymousUser(session["anon_id"])
    else:
        aid = "".join(
            random.choice(string.ascii_lowercase + string.digits) for _ in range(8)
        )
        session["anon_id"] = aid
        au = AnonymousUser(aid)

    set_user_id(au.get_id())
    return au


from .cfp import Proposal  # noqa
