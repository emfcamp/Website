import re
from typing import Pattern

from flask import current_app as app
from flask_wtf import FlaskForm
from flask_sqlalchemy import SQLAlchemy
from wtforms import SelectField, BooleanField, FieldList, FormField, SubmitField
from wtforms.validators import InputRequired

from .fields import HiddenIntegerField

from models.user import UserDiversity
from models.cfp_tag import DEFAULT_TAGS, Tag
from models.payment import (
    Payment,
    BankRefund,
    StripeRefund,
)
from models.purchase import AdmissionTicket

from ..payments.stripe import stripe_payment_refunded


class Form(FlaskForm):
    """
    Re-override these back to their wtforms defaults
    """

    class Meta(FlaskForm.Meta):
        csrf = False
        csrf_class = None
        csrf_context = None


OPT_OUT = [
    ("", "Prefer not to say"),
]

GENDER_VALUES = ("female", "male", "non-binary", "other")
GENDER_CHOICES = tuple(OPT_OUT + [(v, v.capitalize()) for v in GENDER_VALUES])

ETHNICITY_VALUES = ("asian", "black", "mixed", "white", "other")
ETHNICITY_CHOICES = tuple(OPT_OUT + [(v, v.capitalize()) for v in ETHNICITY_VALUES])

AGE_VALUES = ("0-15", "16-25", "26-35", "36-45", "46-55", "56-65", "66+")
AGE_CHOICES = tuple(OPT_OUT + [(v, v) for v in AGE_VALUES])


# FIXME these are matchers for transition from freetext diversity form -> select boxes
# This should be deleted for 2026


def guess_age(age_str: str) -> str:
    if age_str in AGE_VALUES:
        return age_str
    try:
        age = int(age_str)
    except ValueError:  # Can't parse as an int so reset
        return ""

    if age > 66:
        return "66+"

    for age_range in AGE_VALUES:
        if age_range == "66+":
            continue
        low_val, high_val = age_range.split("-")

        if int(low_val) <= age <= int(high_val):
            return age_range

    return ""


def __guess_value(match_str: str, matchers_dict: dict[str, Pattern]) -> str:
    match_str = match_str.lower().strip()
    for key, matcher in matchers_dict.items():
        if matcher.fullmatch(match_str):
            return key

    return ""


def guess_gender(gender_str: str) -> str:
    gender_matchers = app.config.get("GENDER_MATCHERS", {})
    gender_re_matchers = {k: re.compile(v, re.I) for k, v in gender_matchers.items()}
    return __guess_value(gender_str, gender_re_matchers)


def guess_ethnicity(ethnicity_str: str) -> str:
    ethnicity_matchers = app.config.get("ETHNICITY_MATCHERS", {})
    ethnicity_re_matchers = {
        k: re.compile(v, re.I) for k, v in ethnicity_matchers.items()
    }
    return __guess_value(ethnicity_str, ethnicity_re_matchers)


# End of stuff to delete for 2026


class DiversityForm(Form):
    age = SelectField("Age", default=OPT_OUT[0], choices=AGE_CHOICES)
    gender = SelectField("Gender", default=OPT_OUT[0], choices=GENDER_CHOICES)
    ethnicity = SelectField("Ethnicity", default=OPT_OUT[0], choices=ETHNICITY_CHOICES)

    # Track CfP reviewer tags
    cfp_tag_0 = SelectField("Topic 1", default=DEFAULT_TAGS[0], choices=DEFAULT_TAGS)
    cfp_tag_1 = SelectField("Topic 2", default=DEFAULT_TAGS[1], choices=DEFAULT_TAGS)
    cfp_tag_2 = SelectField("Topic 3", default=DEFAULT_TAGS[2], choices=DEFAULT_TAGS)

    def update_user(self, user):
        if not user.diversity:
            user.diversity = UserDiversity()

        user.diversity.age = self.age.data
        user.diversity.gender = self.gender.data
        user.diversity.ethnicity = self.ethnicity.data

        if user.has_permission("cfp_reviewer"):
            user.cfp_reviewer_tags = [
                Tag.get_by_value(self.cfp_tag_0.data),
                Tag.get_by_value(self.cfp_tag_1.data),
                Tag.get_by_value(self.cfp_tag_2.data),
            ]

        return user

    def set_from_user(self, user):
        if user.diversity:
            self.age.data = guess_age(user.diversity.age)
            self.gender.data = guess_gender(user.diversity.gender)
            self.ethnicity.data = guess_ethnicity(user.diversity.ethnicity)

        if user.cfp_reviewer_tags:
            self.cfp_tag_0.data = user.cfp_reviewer_tags[0].tag
            self.cfp_tag_1.data = user.cfp_reviewer_tags[1].tag
            self.cfp_tag_2.data = user.cfp_reviewer_tags[2].tag

        return self

    def validate(self, extra_validators=None):
        if not super().validate(extra_validators):
            return False
        result = True
        seen = set()
        for field in [self.cfp_tag_0, self.cfp_tag_1, self.cfp_tag_2]:
            if field.data in seen:
                field.errors = ["Please select three different choices."]
                result = False
            else:
                seen.add(field.data)
        return result


class RefundFormException(Exception):
    pass


class RefundPurchaseForm(Form):
    purchase_id = HiddenIntegerField("Purchase ID", [InputRequired()])
    refund = BooleanField("Refund purchase", default=True)


class RefundForm(Form):
    purchases = FieldList(FormField(RefundPurchaseForm))
    refund = SubmitField("Refunded these by bank transfer")
    stripe_refund = SubmitField("Refund through Stripe (preferred)")

    def intialise_with_payment(self, payment: Payment, set_purchase_ids: bool):
        if payment.provider != "stripe":
            # Make sure the stripe_refund submit won't count as pressed
            self.stripe_refund.data = ""

        if set_purchase_ids:
            for purchase in payment.purchases:
                self.purchases.append_entry()
                self.purchases[-1].purchase_id.data = purchase.id

        purchases_dict = {p.id: p for p in payment.purchases}

        for f in self.purchases:
            f._purchase = purchases_dict[f.purchase_id.data]
            f.refund.label.text = "%s - %s" % (
                f._purchase.id,
                f._purchase.product.display_name,
            )

            if (
                f._purchase.refund_id is None
                and f._purchase.is_paid_for
                and f._purchase.owner == payment.user
            ):
                # Purchase is owned by the user and not already refunded
                f._disabled = False

                if type(f._purchase) == AdmissionTicket and f._purchase.checked_in:
                    f.refund.data = False
                    f.refund.label.text += " (checked in)"
            elif f._purchase.refund_id is not None:
                f._disabled = True
                f.refund.data = False
                f.refund.label.text += " (refunded)"
            else:
                f._disabled = True
                f.refund.data = False
                f.refund.label.text += " (transferred)"

    def process_refund(self, payment: Payment, db: SQLAlchemy, logger, stripe) -> int:
        payment.lock()

        purchases = [
            f._purchase for f in self.purchases if f.refund.data and not f._disabled
        ]
        total = sum(p.price_tier.get_price(payment.currency).value for p in purchases)

        if not total:
            raise RefundFormException(
                "Please select some purchases to refund. You cannot refund only free purchases from this page."
            )

        if any(p.owner != payment.user for p in purchases):
            raise RefundFormException("Cannot refund transferred purchase")

        # This is where you'd add the premium if it existed
        logger.info(
            "Refunding %s purchases from payment %s, totalling %s %s",
            len(purchases),
            payment.id,
            total,
            payment.currency,
        )

        if self.stripe_refund.data:
            logger.info("Refunding using Stripe")
            charge = stripe.Charge.retrieve(payment.charge_id)

            if charge.refunded:
                # This happened unexpectedly - send the email as usual
                stripe_payment_refunded(payment)
                raise RefundFormException(
                    "This charge has already been fully refunded."
                )

            payment.state = "refunding"
            refund = StripeRefund(payment, total)

        else:
            logger.info("Refunding out of band")

            payment.state = "refunding"
            refund = BankRefund(payment, total)

        with db.session.no_autoflush:
            for purchase in purchases:
                purchase.refund_purchase(refund)

        priced_purchases = [
            p
            for p in payment.purchases
            if p.price_tier.get_price(payment.currency).value
        ]
        unpriced_purchases = [
            p
            for p in payment.purchases
            if not p.price_tier.get_price(payment.currency).value
        ]

        all_refunded = False
        if all(p.refund for p in priced_purchases):
            all_refunded = True
            # Remove remaining free purchases from the payment so they're still valid.
            for purchase in unpriced_purchases:
                if not purchase.refund:
                    logger.info(
                        "Removing free purchase %s from refunded payment",
                        purchase.id,
                    )
                    if not purchase.is_paid_for:
                        # The only thing keeping this purchase from being valid was the payment
                        logger.info(
                            "Setting orphaned free purchase %s to paid", purchase.id
                        )
                        purchase.state = "paid"

                        # Should we even put free purchases in a Payment?

                    purchase.payment = None
                    purchase.payment_id = None

        db.session.commit()

        if self.stripe_refund.data:
            try:
                stripe_refund = stripe.Refund.create(
                    charge=payment.charge_id, amount=refund.amount_int
                )

            except Exception as e:
                logger.exception("Exception %r refunding payment", e)

                raise RefundFormException(
                    "An error occurred refunding with Stripe. Please check the state of the payment."
                )

            refund.refundid = stripe_refund.id
            if stripe_refund.status not in ("pending", "succeeded"):

                # Should never happen according to the docs
                logger.warn(
                    "Refund status is %s, not pending or succeeded",
                    stripe_refund.status,
                )
                raise RefundFormException(
                    "The refund with Stripe was not successful. Please check the state of the payment."
                )

        if all_refunded:
            payment.state = "refunded"
        else:
            payment.state = "partrefunded"

        db.session.commit()
        return total
