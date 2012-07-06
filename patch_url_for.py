# Until these are released:
#   https://github.com/mitsuhiko/flask/pull/346
#   https://github.com/mitsuhiko/werkzeug/pull/136

from functools import wraps
import flask

def wrap_url_for(f):
    @wraps(f)
    def url_for(*args, **kwargs):
        if kwargs.pop('_secure', False):
            kwargs['_external'] = True
            url = f(*args, **kwargs)
            if url.startswith('http:'):
                return url.replace('http:', 'https:', 1)
            return url
        return f(*args, **kwargs)
    return url_for

url_for = flask.url_for
flask.url_for = flask.app.url_for = flask.helpers.url_for = wrap_url_for(url_for)
