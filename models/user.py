from __future__ import annotations

import base64
import hashlib
import hmac
import random
import string
import struct
import time
import typing
from datetime import datetime, timedelta

from flask import current_app as app
from flask import session
from flask_login import AnonymousUserMixin, UserMixin
from sqlalchemy import Column, ForeignKey, Index, Integer, Table, func, select, text
from sqlalchemy.exc import NoResultFound
from sqlalchemy.ext.associationproxy import association_proxy
from sqlalchemy.orm import Mapped, mapped_column, relationship

from loggingmanager import set_user_id
from main import db

from . import BaseModel
from .permission import Permission, UserPermission
from .volunteer.shift import ShiftEntry

if typing.TYPE_CHECKING:
    from .admin_message import AdminMessage
    from .cfp import CFPMessage, CFPVote
    from .cfp_tag import Tag
    from .diversity import UserDiversity
    from .event_tickets import EventTicket
    from .payment import Payment
    from .purchase import AdmissionTicket, Purchase, PurchaseTransfer, Ticket
    from .village import VillageMember
    from .volunteer import RoleAdmin, Volunteer

__all__ = [
    "AnonymousUser",
    "User",
    "UserShipping",
]

CHECKIN_CODE_LEN = 16
checkin_code_re = rf"[0-9a-zA-Z_-]{{{CHECKIN_CODE_LEN}}}"


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
    msg = f"{timestamp}-{uid}"
    return _generate_hmac(prefix, key, msg).decode("ascii")


def generate_unlimited_hmac(prefix, key, uid):
    """Intended for user tokens, long-lived but low-importance"""
    msg = f"{uid}"
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
        age = datetime.fromtimestamp(current_timestamp) - datetime.fromtimestamp(timestamp)
        if age > timedelta(hours=valid_hours):
            return None
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


def verify_signup_code(key, current_timestamp, code):
    return verify_timed_hmac("signup-", key, current_timestamp, code, valid_hours=6)


def verify_api_token(key, uid):
    return verify_unlimited_hmac("api-", key, uid)


def verify_bar_training_token(key, uid):
    return verify_unlimited_hmac("bar-training-", key, uid)


def verify_checkin_code(key, uid):
    return verify_unlimited_short_hmac("checkin-", key, uid)


CFPReviewerTags = Table(
    "cfp_reviewer_tags",
    BaseModel.metadata,
    Column("user_id", Integer, ForeignKey("user.id"), primary_key=True),
    Column("tag_id", Integer, ForeignKey("tag.id"), primary_key=True),
)


class User(BaseModel, UserMixin):
    __tablename__ = "user"
    __versioned__ = {"exclude": ["favourites"]}

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str | None] = mapped_column(unique=True, index=True)
    name: Mapped[str] = mapped_column(index=True)
    company: Mapped[str | None]
    will_have_ticket: Mapped[bool] = mapped_column(default=False)  # for CfP filtering
    checkin_note: Mapped[str | None]
    # Whether the user has opted in to receive promo emails after this event:
    promo_opt_in: Mapped[bool] = mapped_column(default=False)

    cfp_invite_reason: Mapped[str | None]

    cfp_reviewer_tags: Mapped[list[Tag]] = relationship(
        back_populates="reviewers",
        cascade="all",
        secondary=CFPReviewerTags,
    )

    diversity: Mapped[UserDiversity | None] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    shipping: Mapped[UserShipping | None] = relationship(back_populates="user", cascade="all, delete-orphan")
    payments: Mapped[list[Payment]] = relationship(lazy="dynamic", back_populates="user", cascade="all")
    permissions: Mapped[list[Permission]] = relationship(
        back_populates="user",
        cascade="all",
        secondary=UserPermission,  # type: ignore[has-type]  # mypy can't see that this is a Table for some reason
        lazy="joined",
    )
    votes: Mapped[list[CFPVote]] = relationship(back_populates="user", lazy="dynamic")

    proposals: Mapped[list[Proposal]] = relationship(
        primaryjoin="Proposal.user_id == User.id",
        back_populates="user",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )
    anonymised_proposals: Mapped[list[Proposal]] = relationship(
        primaryjoin="Proposal.anonymiser_id == User.id",
        back_populates="anonymiser",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )
    favourites: Mapped[list[Proposal]] = relationship(
        back_populates="favourites", secondary="favourite_proposal"
    )

    messages_from: Mapped[list[CFPMessage]] = relationship(
        primaryjoin="CFPMessage.from_user_id == User.id",
        back_populates="from_user",
        lazy="dynamic",
    )

    event_tickets: Mapped[list[EventTicket]] = relationship(back_populates="user", lazy="dynamic")

    purchases: Mapped[list[Purchase]] = relationship(
        lazy="dynamic", primaryjoin="Purchase.purchaser_id == User.id"
    )

    owned_purchases: Mapped[list[Purchase]] = relationship(
        lazy="dynamic", primaryjoin="Purchase.owner_id == User.id"
    )

    owned_tickets: Mapped[list[Ticket]] = relationship(
        lazy="select", primaryjoin="Ticket.owner_id == User.id", viewonly=True
    )

    owned_admission_tickets: Mapped[list[AdmissionTicket]] = relationship(
        lazy="select",
        primaryjoin="AdmissionTicket.owner_id == User.id",
        viewonly=True,
    )

    transfers_to: Mapped[list[PurchaseTransfer]] = relationship(
        back_populates="to_user",
        lazy="dynamic",
        primaryjoin="PurchaseTransfer.to_user_id == User.id",
        cascade="all, delete-orphan",
    )
    transfers_from: Mapped[list[PurchaseTransfer]] = relationship(
        back_populates="from_user",
        lazy="dynamic",
        primaryjoin="PurchaseTransfer.from_user_id == User.id",
        cascade="all, delete-orphan",
    )

    village_membership: Mapped[VillageMember] = relationship(
        cascade="all, delete-orphan",
        back_populates="user",
        uselist=False,
    )
    village = association_proxy("village_membership", "village")

    admin_messages: Mapped[list[AdminMessage]] = relationship("AdminMessage", back_populates="creator")

    volunteer: Mapped[Volunteer | None] = relationship(back_populates="user")
    volunteer_admin_roles: Mapped[list[RoleAdmin]] = relationship(back_populates="user")
    shift_entries: Mapped[list[ShiftEntry]] = relationship(back_populates="user")

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
                    for u in User.query.join(Proposal, Proposal.user_id == User.id).filter(
                        Proposal.is_accepted
                    )
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
            if (paid is True and not ticket.is_paid_for) or (paid is False and ticket.is_paid_for):
                continue
            if type is not None and ticket.type != type:
                continue
            yield ticket

    def login_code(self, key):
        return generate_login_code(key, int(time.time()), self.id)

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
            if name.startswith("cfp_") and name != "cfp_admin" and self.has_permission("cfp_admin"):
                return True
        for permission in self.permissions:
            if permission.name == name:
                return True
        return False

    def grant_permission(self, name: str):
        try:
            perm = db.session.execute(select(Permission).where(Permission.name == name)).scalar_one()
        except NoResultFound:
            perm = Permission(name)
            db.session.add(perm)
        self.permissions.append(perm)

    def revoke_permission(self, name: str):
        for user_perm in self.permissions:
            if user_perm.name == name:
                self.permissions.remove(user_perm)

    def has_ticket_for_event(self, proposal_id: int) -> bool:
        return any([t for t in self.event_tickets if t.proposal_id == proposal_id and t.state == "ticket"])

    def has_lottery_ticket_for_event(self, proposal_id: int) -> bool:
        return any(
            [t for t in self.event_tickets if t.proposal_id == proposal_id and t.state == "entered-lottery"]
        )

    def __repr__(self):
        return f"<User {self.email}>"

    @classmethod
    def get_by_email(cls, email) -> User | None:
        return User.query.filter(func.lower(User.email) == func.lower(email)).one_or_none()

    @classmethod
    def does_user_exist(cls, email):
        return bool(User.get_by_email(email))

    @classmethod
    def get_by_code(cls, key, code) -> User | None:
        uid = verify_login_code(key, time.time(), code)
        if uid is None:
            return None

        return User.query.filter_by(id=uid).one()

    @classmethod
    def get_by_checkin_code(cls, key, code) -> User | None:
        uid = verify_checkin_code(key, code)
        if uid is None:
            return None

        return User.query.filter_by(id=uid).one()

    @classmethod
    def get_by_api_token(cls, key, code) -> User | None:
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

    @property
    def has_proposals(self):
        for _ in self.proposals:
            return True
        return False


Index("ix_user_email_lower", func.lower(User.email), unique=True)
Index(
    "ix_user_email_tsearch",
    text("to_tsvector('simple', replace(email, '@', ' '))"),
    postgresql_using="gin",
)
Index("ix_user_name_tsearch", text("to_tsvector('simple', name)"), postgresql_using="gin")


class UserShipping(BaseModel):
    __tablename__ = "shipping"
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"), primary_key=True)
    name: Mapped[str | None]
    address_1: Mapped[str | None]
    address_2: Mapped[str | None]
    town: Mapped[str | None]
    postcode: Mapped[str | None]
    country: Mapped[str | None]

    user: Mapped[User] = relationship(back_populates="shipping")


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
        aid = "".join(random.choice(string.ascii_lowercase + string.digits) for _ in range(8))
        session["anon_id"] = aid
        au = AnonymousUser(aid)

    set_user_id(au.get_id())
    return au


from .cfp import Proposal
