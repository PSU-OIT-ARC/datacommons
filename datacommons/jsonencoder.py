import decimal
import json
from django.contrib.gis.geos import GEOSGeometry
# since Python's default JSONEncoder doesn't handle decimal types, we have to
# add support for that on our own. Same with date types
class JSONEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, decimal.Decimal):
            return str(o)
        if hasattr(o, 'isoformat'):
            return o.isoformat()
        if isinstance(o, GEOSGeometry):
            return str(o)
        return super(JSONEncoder, self).default(o)
