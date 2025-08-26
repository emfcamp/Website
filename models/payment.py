from __future__ import annotations

import random
import re
import typing
from collections.abc import Iterable
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import column, event, func
from sqlalchemy.orm import Mapped, Session, aliased, relationship
from sqlalchemy.orm.exc import MultipleResultsFound, NoResultFound
from sqlalchemy_continuum.utils import transaction_class, version_class
from stdnum import iso11649
from stdnum.iso7064 import mod_97_10

from main import db

from . import (
    BaseModel,
    Currency,
    bucketise,
    event_year,
    export_attr_counts,
    export_intervals,
)
from .product import Voucher
from .purchase import Ticket
from .site_state import get_refund_state

safechars = "2346789BCDFGHJKMPQRTVWXY"

if typing.TYPE_CHECKING:
    from .purchase import Purchase


class StateException(Exception):
    pass


class Payment(BaseModel):
    __tablename__ = "payment"
    __versioned__: dict = {}

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)

    provider = db.Column(db.String, nullable=False)
    currency = db.Column(db.String, nullable=False)
    amount_int = db.Column(db.Integer, nullable=False)

    state = db.Column(db.String, nullable=False, default="new")
    reminder_sent_at = db.Column(db.DateTime, nullable=True)

    created = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    expires = db.Column(db.DateTime, nullable=True)
    voucher_code = db.Column(db.String, db.ForeignKey("voucher.code"), nullable=True, default=None)

    # VAT invoice number, if issued
    vat_invoice_number = db.Column(db.Integer, nullable=True)

    refunds: Mapped[list[Refund]] = relationship(backref="payment", cascade="all")
    purchases: Mapped[list[Purchase]] = relationship(backref="payment", cascade="all")
    refund_requests: Mapped[list[RefundRequest]] = relationship(
        backref="payment", cascade="all, delete-orphan"
    )

    __mapper_args__ = {"polymorphic_on": provider}

    def __init__(self, currency: Currency, amount, voucher_code: str | None = None):
        self.currency = currency
        self.amount = amount

        if voucher_code:
            self.voucher_code = voucher_code

    @classmethod
    def get_export_data(cls):
        if cls.__name__ == "Payment":
            # Export stats for each payment type separately
            return {}

        purchase_counts = (
            cls.query.outerjoin(cls.purchases).group_by(cls.id).with_entities(func.count(Ticket.id))
        )
        refund_counts = cls.query.outerjoin(cls.refunds).group_by(cls.id).with_entities(func.count(Refund.id))

        cls_version = version_class(cls)
        cls_transaction = transaction_class(cls)
        changes = cls.query.join(cls.versions).group_by(cls.id)
        change_counts = changes.with_entities(func.count(cls_version.id))
        first_changes = db.select(column("created")).select_from(
            changes.join(cls_version.transaction)
            .with_entities(func.min(cls_transaction.issued_at).label("created"))
            .subquery()
        )

        cls_ver_new = aliased(cls_version)
        cls_ver_paid = aliased(cls_version)
        cls_txn_new = aliased(cls_transaction)
        cls_txn_paid = aliased(cls_transaction)
        active_time = func.max(cls_txn_paid.issued_at) - func.max(cls_txn_new.issued_at)
        active_times = (
            cls.query.join(cls_ver_new, cls_ver_new.id == cls.id)
            .join(cls_ver_paid, cls_ver_paid.id == cls.id)
            .join(cls_txn_new, cls_txn_new.id == cls_ver_new.transaction_id)
            .join(cls_txn_paid, cls_txn_paid.id == cls_ver_paid.transaction_id)
            .filter(cls_ver_new.state == "new")
            .filter(cls_ver_paid.state == "paid")
            .with_entities(active_time.label("active_time"))
            .group_by(cls.id)
        )

        time_buckets = [timedelta(0), timedelta(minutes=1), timedelta(hours=1)] + [
            timedelta(d) for d in [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 28, 60]
        ]

        data = {
            "public": {
                "payments": {
                    "counts": {
                        "purchases": bucketise(purchase_counts, [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 20]),
                        "refunds": bucketise(refund_counts, [0, 1, 2, 3, 4]),
                        "changes": bucketise(change_counts, range(10)),
                        "created_week": export_intervals(
                            first_changes, column("created"), "week", "YYYY-MM-DD"
                        ),
                        "active_time": bucketise([r.active_time for r in active_times], time_buckets),
                        "amounts": bucketise(
                            cls.query.with_entities(cls.amount_int / 100),
                            [0, 10, 20, 30, 40, 50, 100, 150, 200],
                        ),
                    }
                }
            },
            "tables": ["payment", "payment_version"],
        }

        count_attrs = ["state", "currency"]
        data["public"]["payments"]["counts"].update(export_attr_counts(cls, count_attrs))

        return data

    def is_refundable(self, ignore_event_refund_state=False) -> bool:
        return self.state in [
            "charged",
            "paid",
            "refunding",
            "partrefunded",
            "refund-requested",
        ] and (get_refund_state() != "off" or ignore_event_refund_state)

    @property
    def amount(self):
        return Decimal(self.amount_int) / 100

    @amount.setter
    def amount(self, val):
        self.amount_int = int(val * 100)

    def change_currency(self, currency: Currency):
        if self.state in {"paid", "partrefunded", "refunded"}:
            raise StateException("Cannot change currency after payment is reconciled")

        if self.currency == currency:
            raise Exception(f"Currency is already {currency}")

        # Sanity check
        assert self.amount == sum(p.price.value for p in self.purchases)

        for p in self.purchases:
            p.change_currency(currency)

        self.amount = sum(p.price.value for p in self.purchases)
        # If we added a premium, it would need to be added again here
        self.currency = currency

    def paid(self):
        if self.state == "paid":
            raise StateException("Payment is already paid")

        for purchase in self.purchases:
            purchase.set_state("paid")
        self.state = "paid"

    def cancel(self):
        if self.state == "cancelled":
            raise StateException("Payment is already cancelled")

        if self.state == "refunded":
            raise StateException("Refunded payments cannot be cancelled")

        with db.session.no_autoflush:
            for purchase in self.purchases:
                purchase.cancel()

        self.state = "cancelled"

        if self.voucher_code:
            # Restore capacity to the voucher
            voucher = Voucher.get_by_code(self.voucher_code)
            if voucher is not None:
                voucher.return_capacity(self)

        db.session.flush()

    def manual_refund(self):
        # Only to be called for full out-of-band refunds, for book-keeping.
        # Providers should cancel purchases individually and insert their
        # own Refunds subclass for partial refunds.

        if self.state == "refunded":
            raise StateException("Payment is already refunded")

        if self.state == "cancelled":
            # If we receive money for a cancelled payment, it will be set to paid
            raise StateException("Refunded payments cannot be cancelled")

        refund = BankRefund(self, self.amount)
        with db.session.no_autoflush:
            for purchase in self.purchases:
                if purchase.owner != self.user:
                    raise StateException("Cannot refund transferred purchase")
                if purchase.price_tier.get_price(self.currency).value > 0 and not purchase.is_paid_for:
                    # This might turn out to be too strict
                    raise StateException("Purchase is not paid, so cannot be refunded")

                purchase.refund_purchase(refund)

        db.session.add(refund)
        self.state = "refunded"

    # TESTME
    def clone(self, ignore_capacity=False):
        other = self.__class__(self.currency, self.amount)
        for purchase in self.purchases:
            new_purchase = purchase.clone(ignore_capacity=ignore_capacity)
            self.user.purchases.append(new_purchase)
            new_purchase.payment = other

        self.user.payments.append(other)
        return other

    def order_number(self):
        """Note this is not a VAT invoice number."""
        return f"WEB-{event_year()}-{self.id:05d}"

    def issue_vat_invoice_number(self):
        if not self.vat_invoice_number:
            sequence_name = "vat_invoice"
            try:
                seq = PaymentSequence.query.filter_by(name=sequence_name).with_for_update().one()
                seq.value += 1
            except NoResultFound:
                seq = PaymentSequence()
                seq.name = sequence_name
                seq.value = 1
                db.session.add(seq)

            self.vat_invoice_number = seq.value
        return f"WEBV-{event_year()}-{self.vat_invoice_number:05d}"

    @property
    def expires_in(self):
        return self.expires - datetime.utcnow()

    def lock(self):
        Payment.query.with_for_update().get(self.id)


@event.listens_for(Session, "after_flush")
def payment_change(session, flush_context):
    for obj in session.deleted:
        if isinstance(obj, Payment):
            raise Exception("Payments cannot be deleted")


class BankPayment(Payment):
    name = "Bank transfer"

    __mapper_args__ = {"polymorphic_identity": "banktransfer"}
    bankref = db.Column(db.String, unique=True)

    def __init__(self, currency: Currency, amount, voucher_code: str | None = None):
        Payment.__init__(self, currency, amount, voucher_code)

        # not cryptographic
        self.bankref = "".join(random.sample(safechars, 8))

    def __repr__(self):
        return f"<BankPayment: {self.state} {self.bankref}>"

    def manual_refund(self):
        if self.state not in {"paid", "refund-requested"}:
            raise StateException("Only BankPayments that have been paid can be marked as refunded")

        super().manual_refund()

    @property
    def recommended_destination(self):
        for currency in [self.currency, "GBP"]:
            try:
                return BankAccount.query.filter_by(currency=currency, active=True).one()
            except (MultipleResultsFound, NoResultFound):
                continue
        return None

    @property
    def customer_reference(self):
        if self.id is None:
            raise Exception(
                "Customer references can only be generated for payments that have been persisted to the database."
            )

        # Derive an ISO-11649 payment reference for EUR-currency payments
        if self.currency == "EUR":
            order_check_digits = mod_97_10.calc_check_digits(f"{self.bankref}RF")
            customer_reference = f"RF{order_check_digits}{self.bankref}"
            assert iso11649.is_valid(customer_reference)
            return customer_reference
        return self.bankref


class BankAccount(BaseModel):
    __tablename__ = "bank_account"
    __export_data__ = False
    id = db.Column(db.Integer, primary_key=True)
    sort_code = db.Column(db.String)
    acct_id = db.Column(db.String)
    currency = db.Column(db.String, nullable=False)
    active = db.Column(db.Boolean)
    payee_name = db.Column(db.String)
    institution = db.Column(db.String, nullable=False)
    address = db.Column(db.String, nullable=False)
    swift = db.Column(db.String)
    iban = db.Column(db.String)
    wise_balance_id = db.Column(db.Integer)

    def __init__(
        self,
        sort_code,
        acct_id,
        currency,
        active,
        payee_name,
        institution,
        address,
        swift,
        iban,
        wise_balance_id=None,
    ):
        self.sort_code = sort_code
        self.acct_id = acct_id
        self.currency = currency
        self.active = active
        self.payee_name = payee_name
        self.institution = institution
        self.address = address
        self.swift = swift
        self.iban = iban
        self.wise_balance_id = wise_balance_id

    @classmethod
    def get(cls, sort_code, acct_id):
        return cls.query.filter_by(acct_id=acct_id, sort_code=sort_code).one()

    def __repr__(self):
        return f"<BankAccount: {self.sort_code} {self.acct_id}>"


db.Index(
    "ix_bank_account_sort_code_acct_id",
    BankAccount.sort_code,
    BankAccount.acct_id,
    unique=True,
)


class BankTransaction(BaseModel):
    __tablename__ = "bank_transaction"
    __export_data__ = False

    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey(BankAccount.id), nullable=False)
    posted = db.Column(db.DateTime, nullable=False)
    type = db.Column(db.String, nullable=False)
    amount_int = db.Column(db.Integer, nullable=False)
    fit_id = db.Column(db.String, index=True)  # allegedly unique, but don't trust it
    wise_id = db.Column(db.String, index=True)
    payee = db.Column(db.String, nullable=False)  # this is what OFX calls it. it's really description
    payment_id = db.Column(db.Integer, db.ForeignKey("payment.id"))
    suppressed = db.Column(db.Boolean, nullable=False, default=False)
    account: Mapped[BankAccount] = relationship(backref="transactions")
    payment: Mapped[BankPayment] = relationship(backref="transactions")

    def __init__(self, account_id, posted, type, amount, payee, fit_id=None, wise_id=None):
        self.account_id = account_id
        self.posted = posted
        self.type = type
        self.amount = amount
        self.payee = payee
        self.fit_id = fit_id
        self.wise_id = wise_id

    def __repr__(self):
        return f"<BankTransaction: {self.amount}, {self.payee}>"

    @property
    def amount(self):
        return Decimal(self.amount_int) / 100

    @amount.setter
    def amount(self, val):
        self.amount_int = int(val * 100)

    def get_matching(self):
        # fit_ids can change, and payments can be reposted
        matching = self.query.filter_by(
            account_id=self.account_id,
            posted=self.posted,
            type=self.type,
            amount_int=self.amount_int,
            payee=self.payee,
        )
        return matching

    def match_payment(self) -> BankPayment | None:
        for bankref in self._recognized_bankrefs:
            try:
                return BankPayment.query.filter_by(bankref=bankref).one()
            except NoResultFound:
                continue

        return None

    @property
    def _recognized_bankrefs(self) -> Iterable[str]:
        """
        Given a customer reference text received on a bank transfer, scan for
        substrings that appear to be valid bank references that we can match
        against bank transfer records in the database.

        We need to deal with human error and character deletion without colliding.
        Unless we use some sort of coding, the minimum length of a bankref should
        be 8, although 7 is workable. For reference:

                    Transactions
        Keyspace    10^2  10^3  10^4
        24^8 ~2^36  2^24  2^18  2^11
        24^7 ~2^32  2^20  2^13  2^7
        24^6 ~2^28  2^15  2^9   2^2
        24^5 ~2^23  2^11  2^4   2^-3

        For GBP transactions, we tend to see:

          name ref type

        where type is BGC or BBP.

        For EUR, it's:

          name*serial*ref

        where serial is a 6-digit number, and ref is often the payee
        name again, or REFERENCE, and always truncated to 8 chars.

        We've also received ISO-11649 payment references formatted:

          ref/timestamp_plus_iban

        Where the timestamp contains digits and is immediately followed by
        the payer's IBAN (no delimiter between the two).
        """

        ref = self.payee.upper()
        hdr = "(RF[0-9][0-9] ?)?"  # optional ISO11649 header + check-digits

        found = re.findall(f"{hdr}([{safechars}]{{4}}[- ]?[{safechars}]{{4}})", ref)
        for iso_header, f in found:
            bankref = f.replace("-", "").replace(" ", "")
            if iso_header and not iso11649.is_valid(iso_header + bankref):
                continue
            yield bankref


db.Index(
    "ix_bank_transaction_u1",
    BankTransaction.account_id,
    BankTransaction.posted,
    BankTransaction.type,
    BankTransaction.amount_int,
    BankTransaction.payee,
    BankTransaction.fit_id,
    unique=True,
)


class StripePayment(Payment):
    name = "Stripe payment"

    __mapper_args__ = {"polymorphic_identity": "stripe"}
    intent_id = db.Column(db.String, unique=True)
    charge_id = db.Column(db.String, unique=True)

    def cancel(self):
        if self.state in ["charged", "paid"]:
            raise StateException("Cannot automatically cancel charging/charged Stripe payments")

        super().cancel()

    @property
    def description(self):
        return f"EMF {event_year()} purchase"

    def manual_refund(self):
        if self.state not in {"charged", "paid", "refund-requested"}:
            raise StateException(
                "Only StripePayments that have been paid or charged can be marked as refunded"
            )

        super().manual_refund()


class Refund(BaseModel):
    __versioned__: dict = {}
    __tablename__ = "refund"
    id = db.Column(db.Integer, primary_key=True)
    payment_id = db.Column(db.Integer, db.ForeignKey("payment.id"), nullable=False)
    provider = db.Column(db.String, nullable=False)
    amount_int = db.Column(db.Integer, nullable=False)
    timestamp = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    purchases: Mapped[list[Purchase]] = relationship(backref=db.backref("refund", cascade="all"))

    __mapper_args__ = {"polymorphic_on": provider}

    def __init__(self, payment, amount):
        self.payment_id = payment.id
        self.payment = payment
        self.amount = amount

    @classmethod
    def get_export_data(cls):
        if cls.__name__ == "Refund":
            # Export stats for each refund type separately
            return {}

        purchase_counts = (
            cls.query.outerjoin(cls.purchases).group_by(cls.id).with_entities(func.count("Ticket.id"))
        )
        data = {
            "public": {
                "refunds": {
                    "counts": {
                        "timestamp_week": export_intervals(cls.query, cls.timestamp, "week", "YYYY-MM-DD"),
                        "purchases": bucketise(purchase_counts, [0, 1, 2, 3, 4]),
                        "amounts": bucketise(
                            cls.query.with_entities(cls.amount_int / 100),
                            [0, 10, 20, 30, 40, 50, 100, 150, 200],
                        ),
                    }
                }
            },
            "tables": ["refund"],
        }

        return data

    @property
    def amount(self):
        return Decimal(self.amount_int) / 100

    @amount.setter
    def amount(self, val):
        self.amount_int = int(val * 100)


class BankRefund(Refund):
    __mapper_args__ = {"polymorphic_identity": "banktransfer"}


class StripeRefund(Refund):
    __mapper_args__ = {"polymorphic_identity": "stripe"}

    refundid = db.Column(db.String, unique=True)


class RefundRequest(BaseModel):
    id = db.Column(db.Integer, primary_key=True)
    payment_id = db.Column(db.Integer, db.ForeignKey("payment.id"))
    donation = db.Column(db.Numeric, nullable=False, default=0)
    currency = db.Column(db.String)
    sort_code = db.Column(db.String)
    account = db.Column(db.String)
    swiftbic = db.Column(db.String)
    iban = db.Column(db.String)
    payee_name = db.Column(db.String)
    note = db.Column(db.String)

    purchases: Mapped[list[Purchase]] = relationship(backref=db.backref("refund_request", cascade="all"))

    @property
    def method(self):
        """The method we use to refund this request.

        This will be "stripe" if the payment can be refunded through Stripe,
        and "banktransfer" otherwise.
        """
        if type(self.payment) is StripePayment and self.payment.currency == self.currency:
            return "stripe"
        return "banktransfer"


class PaymentSequence(BaseModel):
    """Table for storing sequence numbers.
    Currently used for storing VAT invoice sequences, which must be monotonic.
    """

    name = db.Column(db.String, primary_key=True)
    value = db.Column(db.Integer, nullable=False)

    @classmethod
    def get_export_data(cls):
        rows = db.session.scalars(db.select(cls))
        return {"public": {r.name: r.value for r in rows}}
