import base64
import hashlib
import hmac
import logging
import random
import string
import struct
import time
from collections.abc import Iterable
from datetime import date, datetime, timedelta
from datetime import time as dttime
from typing import TYPE_CHECKING, Literal, cast

from flask import current_app as app
from flask import session
from flask_login import AnonymousUserMixin, UserMixin
from sqlalchemy import Column, ForeignKey, Index, Integer, Table, func, select, text
from sqlalchemy.exc import NoResultFound
from sqlalchemy.ext.associationproxy import AssociationProxy, association_proxy
from sqlalchemy.orm import Mapped, mapped_column, relationship

from apps.config import config
from loggingmanager import set_user_id
from main import NaiveDT, db

from . import BaseModel
from .permission import Permission, UserPermission
from .volunteer.shift import ShiftEntry

if TYPE_CHECKING:
    from .admin_message import AdminMessage
    from .content.cfp import ProposalMessage, ProposalVote
    from .content.lightning_talk import LightningTalk
    from .content.lottery import LotteryEntry
    from .content.schedule import Occurrence, ScheduleItem, ScheduleItemPresenter
    from .content.tagging import Tag
    from .diversity import UserDiversity
    from .email import EmailJobRecipient
    from .payment import Payment
    from .product import Voucher
    from .purchase import AdmissionTicket, Purchase, PurchaseTransfer, Ticket
    from .village import VillageJoinRequest, VillageMember
    from .volunteer import BuildupVolunteer, Volunteer

__all__ = [
    "AnonymousUser",
    "User",
    "UserShipping",
]

CHECKIN_CODE_LEN = 16
checkin_code_re = rf"[0-9a-zA-Z_-]{{{CHECKIN_CODE_LEN}}}"

log = logging.getLogger(__name__)


def _generate_hmac(prefix: bytes | str, key: bytes | str, msg: bytes | str) -> bytes:
    """Generate a keyed HMAC for a unique purpose. You don't want to call this directly.

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


def generate_checkin_code(key, uid, version=1):
    return generate_unlimited_short_hmac("checkin-", key, uid, version=version)


def verify_login_code(key, current_timestamp, code):
    return verify_timed_hmac("login-", key, current_timestamp, code, valid_hours=6)


def verify_signup_code(key, current_timestamp, code):
    return verify_timed_hmac("signup-", key, current_timestamp, code, valid_hours=6)


def verify_api_token(key, uid):
    return verify_unlimited_hmac("api-", key, uid)


def verify_checkin_code(key, uid):
    return verify_unlimited_short_hmac("checkin-", key, uid)


CFPReviewerTags = Table(
    "cfp_reviewer_tags",
    BaseModel.metadata,
    Column("user_id", Integer, ForeignKey("user.id"), primary_key=True),
    Column("tag_id", Integer, ForeignKey("tag.id"), primary_key=True),
)


EmailStatus = Literal["unverified", "verified", "bounced", "spam_report"]


class User(BaseModel, UserMixin):
    """A user of the EMF website

    User objects are usually created when a user purchases a ticket or submits a proposal
    to the Call for Participation.
    """

    __tablename__ = "user"
    __versioned__ = {"exclude": ["favourites"]}

    ### Basic user info
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(unique=True, index=True)

    #: Whether the user's email address has been verified or bounced
    email_state: Mapped[EmailStatus] = mapped_column(server_default="unverified", nullable=False)

    #: The user's name
    name: Mapped[str] = mapped_column(index=True)
    company: Mapped[str | None]
    #: A note shown to the entrance volunteer when this person is checked in
    checkin_note: Mapped[str | None]
    #: Whether the user has opted in to receive promotional emails after this event
    promo_opt_in: Mapped[bool] = mapped_column(default=False)

    diversity: Mapped[UserDiversity | None] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )

    #: Website permissions assigned to this user
    permissions: Mapped[list[Permission]] = relationship(
        back_populates="users",
        cascade="all",
        secondary=UserPermission,  # type: ignore[has-type]  # see https://github.com/sqlalchemy/sqlalchemy/discussions/9801
        lazy="joined",
    )

    ### Purchases
    shipping: Mapped[UserShipping | None] = relationship(back_populates="user", cascade="all, delete-orphan")

    #: Payments created by this user
    payments: Mapped[list[Payment]] = relationship(lazy="dynamic", back_populates="user", cascade="all")

    #: All purchases which this user has made (which may have been transferred to another user)
    purchases: Mapped[list[Purchase]] = relationship(
        lazy="dynamic", primaryjoin="Purchase.purchaser_id == User.id"
    )

    #: Purchases owned by this user
    owned_purchases: Mapped[list[Purchase]] = relationship(
        lazy="dynamic", primaryjoin="Purchase.owner_id == User.id"
    )

    #: Tickets owned by this user
    owned_tickets: Mapped[list[Ticket]] = relationship(
        lazy="select", primaryjoin="Ticket.owner_id == User.id", viewonly=True
    )

    #: Admission tickets owned by this user
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
    email_job_recipients: Mapped[list[EmailJobRecipient]] = relationship(back_populates="user")

    ### Content
    will_have_ticket: Mapped[bool] = mapped_column(default=False)  # for CfP filtering
    cfp_voucher_code: Mapped[str | None] = mapped_column(ForeignKey("voucher.code"))
    cfp_voucher: Mapped[Voucher | None] = relationship("Voucher")
    cfp_invite_reason: Mapped[str | None]

    proposals: Mapped[list[Proposal]] = relationship(
        primaryjoin="Proposal.user_id == User.id",
        back_populates="user",
    )

    schedule_items: Mapped[list[ScheduleItem]] = relationship(
        primaryjoin="ScheduleItem.user_id == User.id",
        back_populates="user",
    )

    schedule_item_presenters: Mapped[list[ScheduleItemPresenter]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )
    presented_schedule_items: AssociationProxy[list[ScheduleItem]] = association_proxy(
        "schedule_item_presenters", "schedule_item"
    )

    lightning_talks: Mapped[list[LightningTalk]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )

    favourites: Mapped[list[ScheduleItem]] = relationship(
        back_populates="favourited_by", secondary="favourite_schedule_item"
    )

    messages_from: Mapped[list[ProposalMessage]] = relationship(
        primaryjoin="ProposalMessage.from_user_id == User.id",
        back_populates="from_user",
    )

    lottery_entries: Mapped[list[LotteryEntry]] = relationship(back_populates="user")
    votes: Mapped[list[ProposalVote]] = relationship(back_populates="user")

    cfp_reviewer_tags: Mapped[list[Tag]] = relationship(
        back_populates="reviewers",
        cascade="all",
        secondary=CFPReviewerTags,
    )

    anonymised_proposals: Mapped[list[Proposal]] = relationship(
        primaryjoin="Proposal.anonymiser_id == User.id",
        back_populates="anonymiser",
    )

    ### Villages
    village_membership: Mapped[VillageMember] = relationship(
        cascade="all, delete-orphan",
        back_populates="user",
        uselist=False,
    )
    village_join_request: Mapped[VillageJoinRequest] = relationship(
        cascade="all, delete-orphan",
        back_populates="user",
        uselist=False,
    )
    # The village this user is a member of. Note that unaccepted requests to join a village won't populate this field
    village = association_proxy("village_membership", "village")

    ### Volunteering
    admin_messages: Mapped[list[AdminMessage]] = relationship("AdminMessage", back_populates="creator")

    buildup_volunteer: Mapped[BuildupVolunteer | None] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    volunteer: Mapped[Volunteer | None] = relationship(back_populates="user", cascade="all, delete-orphan")
    shift_entries: Mapped[list[ShiftEntry]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )

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
                        Proposal.state.in_({"accepted", "finalised"}),
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

    def get_owned_tickets(self, paid: bool | None = None, type: str | None = None) -> Iterable[Ticket]:
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

    def has_permission(self, name: str, cascade: bool = True) -> bool:
        if cascade:
            if name != "admin" and self.has_permission("admin"):
                return True
            if name.startswith("cfp_") and name != "cfp_admin" and self.has_permission("cfp_admin"):
                return True
        for permission in self.permissions:
            if permission.name == name:
                return True
        return False

    def grant_permission(self, name: str) -> None:
        if self.has_permission(name, cascade=False):
            return
        try:
            perm = db.session.execute(select(Permission).where(Permission.name == name)).scalar_one()
        except NoResultFound:
            perm = Permission(name)
            db.session.add(perm)
        self.permissions.append(perm)

    def revoke_permission(self, name: str) -> None:
        for user_perm in self.permissions:
            if user_perm.name == name:
                self.permissions.remove(user_perm)

    def issue_cfp_voucher(self) -> None:
        """
        Issue a CfP voucher to the user - this voucher is for a maximum of 2 adult tickets, minus
        the number of adult tickets the user already holds.

        If the voucher has already been issued, it will be extended.
        """
        ADULT_TICKETS = 2
        # The voucher code itself implements a 36-hour grace period, so we don't need to pad it here.
        voucher_expires_on_date = date.today() + timedelta(days=config.get("CFP_VOUCHER_EXPIRY_DAYS", 14))
        voucher_expires_at = cast(
            NaiveDT,
            datetime.combine(
                voucher_expires_on_date,
                dttime(),  # 00:00:00
                tzinfo=None,
            ),
        )
        if self.cfp_voucher is None:
            # Issue a pseudo-voucher, which may have 0 capacity if the user already has 2 tickets.
            product_view = ProductView.get_by_name("speakers")
            if not product_view:
                raise Exception("No 'speakers' product view created yet?")
            voucher = Voucher(
                view=product_view,
                email=self.email,
                tickets_remaining=max(ADULT_TICKETS - self.adult_tickets_held(voucher=True), 0),
                expiry=voucher_expires_at,
            )
            db.session.add(voucher)
            self.cfp_voucher = voucher
            log.info("Issuing user %s a CfP voucher until %s", self, voucher_expires_at)
        elif self.cfp_voucher.tickets_remaining > 0:
            # Give the user an extension on their voucher. It's easier and
            # friendlier than writing explanatory text in the email.
            self.cfp_voucher.expiry = voucher_expires_at
            log.info(
                "Extending user's %s CfP voucher to %s since a new proposal was accepted and their voucher has already expired",
                self,
                voucher_expires_at,
            )

    def __repr__(self):
        return f"<User {self.email}>"

    @classmethod
    def get_by_email(cls, email: str) -> User | None:
        return (
            db.session.execute(select(User).where(func.lower(User.email) == func.lower(email)))
            .unique()
            .scalar_one_or_none()
        )

    @classmethod
    def does_user_exist(cls, email):
        return bool(User.get_by_email(email))

    @classmethod
    def get_by_code(cls, key: str, code: str) -> User | None:
        uid = verify_login_code(key, time.time(), code)
        if uid is None:
            return None
        return db.session.get_one(User, uid)

    @classmethod
    def get_by_checkin_code(cls, key: str, code: str) -> User | None:
        uid = verify_checkin_code(key, code)
        if uid is None:
            return None
        return db.session.get_one(User, uid)

    @classmethod
    def get_by_api_token(cls, key: str, code: str) -> User | None:
        uid = verify_api_token(key, code)
        if uid is None:
            # FIXME: raise an exception instead of returning None
            return None
        return db.session.get_one(User, uid)

    def adult_tickets_held(self, voucher: bool = False) -> int:
        adult_tickets = [
            ticket
            for ticket in self.get_owned_tickets(paid=True, type="admission_ticket")
            if ticket.product.is_adult_ticket(voucher=voucher)
        ]
        return len(adult_tickets)

    @property
    def admission_tickets_held(self) -> int:
        return len(list(self.get_owned_tickets(paid=True, type="admission_ticket")))

    @property
    def has_admission_ticket(self) -> bool:
        """Whether the user has a ticket to the event."""
        return self.admission_tickets_held > 0

    @property
    def has_redeemed_tickets(self) -> bool:
        """Whether any of the user's tickets have been redeemed."""
        return any(t.redeemed for t in self.get_owned_tickets(paid=True, type="admission_ticket"))

    def check_will_have_ticket(self) -> bool:
        return self.will_have_ticket or self.has_admission_ticket

    @property
    def has_accepted_proposal(self):
        for proposal in self.proposals:
            if proposal.state in {"accepted", "finalised"}:
                return True
        return False

    def get_lottery_entry_for_occurrence(self, occurrence: Occurrence) -> LotteryEntry | None:
        for entry in self.lottery_entries:
            if entry.occurrence == occurrence:
                return entry
        return None

    @property
    def google_wallet_pass_url(self) -> str:
        # Avoid circular import
        from apps.common import walletpass

        return walletpass.generate_gwallet_pass_url(self)


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


from .content.cfp import Proposal
from .content.schedule import ScheduleItem
from .product import ProductView, Voucher
