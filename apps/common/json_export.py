from collections import OrderedDict
from datetime import datetime
from decimal import Decimal
from json import JSONEncoder

from sqlalchemy.engine.row import Row

from main import db
from models import to_dict


class ExportEncoder(JSONEncoder):
    def default(self, obj):
        if isinstance(obj, datetime):
            return obj.isoformat(" ")

        if isinstance(obj, Decimal):
            return str(obj)

        return JSONEncoder.default(self, obj)

    def iterencode(self, obj):
        def _iterconvert(obj):
            # namedtuple/sqlalchemy result
            if isinstance(obj, tuple | Row) and hasattr(obj, "_asdict"):
                # this doesn't include any columns without label()s
                dct = obj._asdict()
                # sqlalchemy result's asdict has broken ordering
                if not isinstance(dct, OrderedDict):
                    dct = OrderedDict((k, dct[k]) for k in obj._fields)
                obj = dct

            if isinstance(obj, db.Model.query_class):
                return [_iterconvert(o) for o in obj]
            if isinstance(obj, db.Model):
                return to_dict(obj)
            if isinstance(obj, list | tuple):
                return [_iterconvert(o) for o in obj]
            if isinstance(obj, dict):
                items = obj.items()
                if not isinstance(obj, OrderedDict):
                    # same as sort_keys=True
                    items = sorted(items, key=lambda kv: kv[0])
                return OrderedDict([(k, _iterconvert(v)) for k, v in items])

            return obj

        return JSONEncoder.iterencode(self, _iterconvert(obj))
