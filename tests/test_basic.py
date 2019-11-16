URLS = [
    "/",
    "/about",
    "/cfp",
    "/login",
    "/metrics",
    "/schedule/2012",
    "/schedule/2013",
    "/schedule/2014",
    "/schedule/2016",
    "/schedule/2018",
    "/schedule/2018/329-powerpoint-karaoke",
    "/schedule/2016/306-using-printed-circuit-boards-to-make-snowflakes",
]


def test_url(client):
    for url in URLS:
        rv = client.get(url)
        assert rv.status_code == 200, "Fetching %s results in HTTP 200" % url
