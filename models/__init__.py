from bisect import bisect
from collections import OrderedDict
from decimal import Decimal
from itertools import groupby
from dateutil.parser import parse

from flask import current_app as app

from main import db
from sqlalchemy import true, inspect
from sqlalchemy.orm.base import NO_VALUE
from sqlalchemy.sql.functions import func
from sqlalchemy.engine.row import Row
from sqlalchemy_continuum.utils import version_class, transaction_class

from typing import TypeAlias


# This alias *was* required to apply type annotations to the model objects,
# but I don't think it even does that any more.
# MyPy doesn't support this nested class syntax which flask-sqlalchemy uses,
# even though type annotations are now present. https://github.com/pallets-eco/flask-sqlalchemy/issues/1112
BaseModel: TypeAlias = db.Model  # type: ignore[name-defined]

""" Type alias for ISO currency (GBP or EUR currently). """
# Note: A better type for this would be Union[Literal['GBP'], Literal['EUR']] but setting this
# results in a world of pain currently.
#
# Ideally needs to be unified with the Currency class in app/common/__init__.py, but this is
# non-trivial.
Currency = str


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
    return OrderedDict(
        (a.key, getattr(obj, a.key))
        for a in inspect(obj).attrs
        if a.loaded_value != NO_VALUE
    )


def count_groups(query, *entities):
    return (
        query.with_entities(func.count().label("count"), *entities)
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
    ranges = [
        "%s-%s" % (a, b - 1) if isinstance(b, int) and b - 1 > a else str(a)
        for a, b in zip(boundaries[:-1], boundaries[1:])
    ]
    ranges.append("%s+" % boundaries[-1])
    counts = OrderedDict.fromkeys(ranges, 0)

    for val in vals:
        if isinstance(val, (tuple, Row)):
            # As a convenience for fetching counts/single columns in sqla
            val, *_ = val

        i = bisect(boundaries, val)
        if i == 0:
            raise IndexError(
                "{} is below the lowest boundary {}".format(val, boundaries[0])
            )
        counts[ranges[i - 1]] += 1

    return counts


def export_intervals(query, date_entity, interval, fmt):
    return nest_count_keys(
        count_groups(query, func.to_char(func.date_trunc(interval, date_entity), fmt))
    )


def export_counts(query, cols):
    counts = OrderedDict()
    for col in cols:
        counts[col.name] = nest_count_keys(count_groups(query, col))

    return counts


def export_attr_counts(cls, attrs):
    cols = [getattr(cls, a) for a in attrs]
    return export_counts(cls.query, cols)


def export_attr_edits(cls, attrs):
    edits_iter = iter_attr_edits(cls, attrs)
    maxes = dict.fromkeys(attrs, 0)
    totals = dict.fromkeys(attrs, 0)
    count = 0

    for pk, attr_times in edits_iter:
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
        for version in versions:
            for attr in attrs:
                val = getattr(version, attr)
                if val != attr_vals[attr]:
                    attr_times[attr].append(version.issued_at)
                    attr_vals[attr] = val

        yield (pk, attr_times)


def config_date(key):
    return parse(app.config.get(key))


from .user import *  # noqa: F401,F403
from .payment import *  # noqa: F401,F403
from .cfp import *  # noqa: F401,F403
from .permission import *  # noqa: F401,F403
from .email import *  # noqa: F401,F403
from .ical import *  # noqa: F401,F403
from .product import *  # noqa: F401,F403
from .purchase import *  # noqa: F401,F403
from .basket import *  # noqa: F401,F403
from .admin_message import *  # noqa: F401,F403
from .volunteer import *  # noqa: F401,F403
from .village import *  # noqa: F401,F403
from .scheduled_task import *  # noqa: F401,F403
from .feature_flag import *  # noqa: F401,F403
from .site_state import *  # noqa: F401,F403
from .arrivals import *  # noqa: F401,F403
from .event_tickets import *  # noqa: F401,F403


db.configure_mappers()
