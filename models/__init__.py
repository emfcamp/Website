from bisect import bisect
from collections import OrderedDict
from decimal import Decimal

from main import db
from sqlalchemy import true, distinct, inspect
from sqlalchemy.orm.base import NO_VALUE
from sqlalchemy.sql.functions import func
from sqlalchemy_continuum.utils import version_class

def exists(query):
    return db.session.query(true()).filter(query.exists()).scalar()

def to_dict(obj):
    return OrderedDict((a.key, getattr(obj, a.key)) for a in inspect(obj).attrs if a.loaded_value != NO_VALUE)

def count_groups(query, *entities):
    return query.with_entities(func.count(), *entities).group_by(*entities).order_by(*entities)

def nest_count_keys(rows):
    """ For JSON's sake, because it doesn't support tuples as keys """
    tree = OrderedDict()
    for c, *key in rows:
        node = tree
        for k in key[:-1]:
            node = node.setdefault(k, OrderedDict())
        node[key[-1]] = c

    return tree

def range_dict(rows, boundaries):
    ranges = ['%s-%s' % (a, b - 1) if b - 1 > a else str(a) for a, b in zip(boundaries[:-1], boundaries[1:])]
    ranges.append('%s+' % boundaries[-1])
    counts = OrderedDict.fromkeys(ranges, 0)

    for c, *_ in rows:
        i = bisect(boundaries, c)
        if i == 0:
            raise IndexError('{} is below the lowest boundary {}'.format(
                             c, boundaries[0]))
        counts[ranges[i - 1]] += 1

    return counts

def export_field_intervals(cls, field, interval, fmt):
    return nest_count_keys(count_groups(cls.query, func.to_char(func.date_trunc(interval, getattr(cls, field)), fmt)))

def export_field_counts(cls, fields):
    return {f: nest_count_keys(count_groups(cls.query, getattr(cls, f))) for f in fields}

def export_field_edits(cls, fields):
    cls_version = version_class(cls)
    edits = {}
    for f in fields:
        c = func.count(distinct(getattr(cls_version, f)))
        max_, avg = cls_version.query.with_entities(cls_version.id, c).group_by(cls_version.id) \
            .from_self().with_entities(func.max(c), func.avg(c)).one()

        edits[f] = {
            'max': max_,
            'avg': avg.quantize(Decimal('0.01')) if avg else None,
        }

    return edits


from .user import *  # noqa
from .payment import *  # noqa
from .ticket import *  # noqa
from .cfp import *  # noqa
from .permission import *  # noqa
from .email import *  # noqa
from .ical import *  # noqa

db.configure_mappers()
