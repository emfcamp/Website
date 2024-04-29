import logging
from datetime import datetime

from sqlalchemy.orm.exc import MultipleResultsFound

from main import cache, db
from . import config_date, BaseModel
from .product import Product, ProductGroup, ProductView, ProductViewProduct, PriceTier

log = logging.getLogger(__name__)


class SiteState(BaseModel):
    __tablename__ = "site_state"
    __export_data__ = False
    name = db.Column(db.String, primary_key=True)
    state = db.Column(db.String)

    def __init__(self, name, state=None):
        self.name = name
        self.state = state

    def __repr__(self):
        return f"<{self.__class__.__name__} {self.name}={self.state}>"


VALID_STATES = {
    "site_state": [
        "before-sales",
        "sales",
        "event",
        "after-event",
        "cancelled",
        "cancelled-time-machine",
    ],
    "sales_state": ["sold-out", "sales-ended", "unavailable", "available"],
    "refund_state": ["on", "off", "illness", "cancellation"],
    "signup_state": [
        "issue_lottery_tickets",
        "pending_tickets",
        "issue_tickets",
        "closed",
    ],
}


def calc_sales_state(date):
    site_capacity = ProductGroup.get_by_name("admissions")
    if site_capacity is None:
        return "unavailable"

    if site_capacity.get_total_remaining_capacity() < 1:
        # We've hit capacity - no more tickets will be sold
        return "sold-out"
    elif date > config_date("EVENT_END"):
        return "sales-ended"

    # Active price tier for the full ticket product in the main flow.
    view = ProductView.query.filter_by(name="main")
    product = view.join(ProductViewProduct, Product).filter_by(name="full")
    try:
        tier = (
            product.join(Product.price_tiers)
            .filter_by(active=True)
            .with_entities(PriceTier)
            .one_or_none()
        )
    except MultipleResultsFound:
        log.error(
            "Multiple active PriceTiers found. Forcing sales state to unavailable."
        )
        return "unavailable"

    if tier is None or tier.has_expired() or tier.get_total_remaining_capacity() <= 0:
        # Tickets not currently available, probably just for this round, but we haven't hit site capacity
        return "unavailable"

    return "available"


@cache.cached(timeout=60, key_prefix="get_states")
def get_states() -> dict[str, str]:
    states = SiteState.query.all()
    states = {s.name: s.state for s in states}

    date = datetime.utcnow()

    if states.get("site_state") is None:
        states["site_state"] = "before-sales"

    if states.get("sales_state") is None:
        states["sales_state"] = calc_sales_state(date)

    if states.get("refund_state") is None:
        states["refund_state"] = "off"

    if states.get("signup_state") is None:
        states["signup_state"] = "closed"

    return states


def refresh_states():
    key = get_states.make_cache_key()
    cache.delete(key)


def get_site_state():
    states = get_states()
    return states["site_state"]


def get_sales_state():
    states = get_states()
    return states["sales_state"]


def get_refund_state():
    states = get_states()
    return states["refund_state"]


def get_signup_state():
    states = get_states()
    return states["signup_state"]
