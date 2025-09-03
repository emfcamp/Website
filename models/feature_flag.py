from sqlalchemy.orm import Mapped, mapped_column

from main import cache

from . import BaseModel

__all__ = [
    "DB_FEATURE_FLAGS",
    "FeatureFlag",
]

# feature flags that can be overridden in the DB
DB_FEATURE_FLAGS = [
    "ATTENDEE_CONTENT",
    "BANK_TRANSFER",
    "BANK_TRANSFER_EURO",
    "CFP",
    "CFP_CLOSED",
    "CFP_FINALISE",
    "ISSUE_TICKETS",
    "LINE_UP",
    "LIGHTNING_TALKS",
    "SCHEDULE",
    "SPONSORS_IN_NAV",
    "STRIPE",
    "VOLUNTEERS_SIGNUP",
    "VOLUNTEERS_SCHEDULE",
    "CFP_TALKS_CLOSED",
    "CFP_WORKSHOPS_CLOSED",
    "CFP_YOUTHWORKSHOPS_CLOSED",
    "CFP_PERFORMANCES_CLOSED",
    "CFP_INSTALLATIONS_CLOSED",
]


class FeatureFlag(BaseModel):
    __tablename__ = "feature_flag"
    __export_data__ = False
    __versioned__: dict = {}
    feature: Mapped[str] = mapped_column(primary_key=True)
    enabled: Mapped[bool] = mapped_column()

    def __init__(self, feature, enabled=False):
        self.feature = feature
        self.enabled = enabled


@cache.cached(timeout=60, key_prefix="get_db_flags")
def get_db_flags():
    flags = FeatureFlag.query.all()
    flags = {f.feature: f.enabled for f in flags}

    return flags


def refresh_flags():
    key = get_db_flags.make_cache_key()
    cache.delete(key)
