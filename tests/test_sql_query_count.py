import pytest
import sqlalchemy
from main import db


class QueryLog:
    def __init__(self):
        self.count = 0
        self.queries = []

    def _query_callback(self, _conn, _cur, query, params, *_):
        self.count += 1
        self.queries.append(query)

    def __enter__(self):
        sqlalchemy.event.listen(
            db.engine, "before_cursor_execute", self._query_callback
        )
        return self

    def __exit__(self, *args):
        sqlalchemy.event.remove(
            db.engine, "before_cursor_execute", self._query_callback
        )

    def __repr__(self):
        return "<SQLAlchemy Query Logger>"


@pytest.mark.parametrize("url,queries", [("/tickets", 2), ("/", 0)])
def test_query_count(app_with_cache, url, queries):
    """ Test how many SQL queries a page generates. """
    client = app_with_cache.test_client()
    client.get(url)  # Initial fetch to fill caches

    with QueryLog() as log:
        rv = client.get(url)
        assert rv.status_code == 200, f"Fetching {url} results in HTTP 200"
        assert log.count <= queries, f"{url} query count"
