URLS = ["/", "/about", "/cfp", "/login", "/metrics"]


def test_url(client):
    for url in URLS:
        rv = client.get(url)
        assert rv.status_code == 200, "Fetching %s results in HTTP 200" % url
