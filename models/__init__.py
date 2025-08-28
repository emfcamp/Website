from bisect import bisect
from collections import OrderedDict
from datetime import UTC, datetime
from decimal import Decimal
from itertools import groupby, pairwise
from typing import TYPE_CHECKING, Literal

import datetype
from dateutil.parser import parse
from flask import current_app as app
from sqlalchemy import inspect, true
from sqlalchemy.engine.row import Row
from sqlalchemy.orm import Query
from sqlalchemy.orm.base import NO_VALUE
from sqlalchemy.sql.functions import func
from sqlalchemy_continuum.utils import transaction_class, version_class

from main import db

# If we're type checking, we want models to inherit from the BaseModel (trivial subclass
# of DeclarativeBase) as mypy can't handle using the sqlalchemy-flask generated db.Model
if TYPE_CHECKING:
    from main import BaseModel
else:
    BaseModel = db.Model

""" Type alias for ISO currency (GBP or EUR currently). """

# Ideally needs to be unified with the Currency class in app/common/__init__.py, but this is
# non-trivial.
type Currency = Literal["GBP", "EUR"]


def naive_utcnow() -> datetype.DateTime[None]:
    return datetype.naive(datetime.now(UTC).replace(tzinfo=None))


def event_start():
    return config_date("EVENT_START")


def event_year():
    """Year of the current event"""
    return event_start().year


def event_end():
    return config_date("EVENT_END")


def exists(query):
    return db.session.query(true()).filter(query.exists()).scalar()


def to_dict(obj):
    return OrderedDict((a.key, getattr(obj, a.key)) for a in inspect(obj).attrs if a.loaded_value != NO_VALUE)


def count_groups(selectable, *entities):
    if isinstance(selectable, Query):
        return (
            selectable.with_entities(func.count().label("count"), *entities)
            .group_by(*entities)
            .order_by(*entities)
        )
    return db.session.execute(
        selectable.with_only_columns(func.count().label("count"), *entities)
        .group_by(*entities)
        .order_by(*entities)
    )


def nest_count_keys(rows):
    """For JSON's sake, because it doesn't support tuples as keys"""
    tree = OrderedDict()
    for c, *key in rows:
        node = tree
        for k in key[:-1]:
            node = node.setdefault(k, OrderedDict())
        node[key[-1]] = c

    return tree


def bucketise(vals, boundaries) -> OrderedDict[str, int]:
    """Sort values into bins, like pandas.cut"""
    ranges = [f"{a}-{b - 1}" if isinstance(b, int) and b - 1 > a else str(a) for a, b in pairwise(boundaries)]
    ranges.append(f"{boundaries[-1]}+")
    counts = OrderedDict.fromkeys(ranges, 0)

    for val in vals:
        if isinstance(val, tuple | Row):
            # As a convenience for fetching counts/single columns in sqla
            val, *_ = val

        i = bisect(boundaries, val)
        if i == 0:
            raise IndexError(f"{val} is below the lowest boundary {boundaries[0]}")
        counts[ranges[i - 1]] += 1

    return counts


def export_intervals(selectable, date_entity, interval, fmt):
    return nest_count_keys(
        count_groups(selectable, func.to_char(func.date_trunc(interval, date_entity), fmt))
    )


def export_counts(selectable, cols):
    counts = OrderedDict()
    for col in cols:
        counts[col.name] = nest_count_keys(count_groups(selectable, col))

    return counts


def export_attr_counts(cls, attrs):
    cols = [getattr(cls, a) for a in attrs]
    return export_counts(cls.query, cols)


def export_attr_edits(cls, attrs):
    edits_iter = iter_attr_edits(cls, attrs)
    maxes = dict.fromkeys(attrs, 0)
    totals = dict.fromkeys(attrs, 0)
    count = 0

    for _pk, attr_times in edits_iter:
        for a in attrs:
            maxes[a] = max(maxes[a], len(attr_times[a]))
            totals[a] += len(attr_times[a])
        count += 1

    edits = OrderedDict()
    for a in attrs:
        if count == 0:
            edits[a] = {"max": 0, "avg": Decimal("0.00")}

        else:
            avg = Decimal(totals[a]) / count
            edits[a] = {"max": maxes[a], "avg": avg.quantize(Decimal("0.01"))}

    return edits


def iter_attr_edits(cls, attrs, query=None):
    pk_cols = [k for k in inspect(cls).primary_key]

    cls_version = version_class(cls)
    pk_cols_version = [getattr(cls_version, k.name) for k in pk_cols]
    attrs_version = [getattr(cls_version, a) for a in attrs]
    cls_transaction = transaction_class(cls)

    if query is None:
        query = cls_version.query

    all_versions = (
        query.join(cls_version.transaction)
        .with_entities(*pk_cols_version + attrs_version + [cls_transaction.issued_at])
        .order_by(*pk_cols_version + [cls_version.transaction_id])
    )

    def get_pk(row):
        return [getattr(row, k.name) for k in pk_cols_version]

    for pk, versions in groupby(all_versions, get_pk):
        # We don't yet process inserts/deletes, but should
        first = next(versions)
        attr_vals = {a: getattr(first, a) for a in attrs}
        attr_times = {a: [first.issued_at] for a in attrs}
        for version in versions:  # noqa: B031
            for attr in attrs:
                val = getattr(version, attr)
                if val != attr_vals[attr]:
                    attr_times[attr].append(version.issued_at)
                    attr_vals[attr] = val

        yield (pk, attr_times)


def config_date(key):
    return parse(app.config.get(key))


from .admin_message import *  # noqa: F403
from .arrivals import *  # noqa: F403
from .basket import *  # noqa: F403
from .cfp import *  # noqa: F403
from .diversity import *  # noqa: F403
from .email import *  # noqa: F403
from .event_tickets import *  # noqa: F403
from .feature_flag import *  # noqa: F403
from .payment import *  # noqa: F403
from .permission import *  # noqa: F403
from .product import *  # noqa: F403
from .purchase import *  # noqa: F403
from .scheduled_task import *  # noqa: F403
from .site_state import *  # noqa: F403
from .user import *  # noqa: F403
from .village import *  # noqa: F403
from .volunteer import *  # noqa: F403

db.configure_mappers()
