""" Monitors static_url_for calls and inserts HTTP Link rel=preload headers
    for them.

    If the "nopush" option is not set, the upstream NGINX server will use
    HTTP/2 server push to send these assets along with the page, which is
    a significant performance improvement on first page load. However, it's
    wasteful to push the same assets on subsequent page loads.

    Otherwise, the browser still knows about the asset earlier and can start
    loading them before it's parsed the HTML.
"""

from main import static_digest
from flask import g, session

# If this file changes its hash, content will be pushed.
PUSH_TRIGGER_FILE = "css/main.css"


def get_link_type(url):
    ext = url.split(".")[-1]
    return {
        "css": "style",
        "js": "script",
        "jpg": "image",
        "png": "image",
        "webp": "image",
    }.get(ext, None)


def static_url_for(endpoint, **values):
    """ Intercept static_url_for calls and store them in the
        request context to allow preload header to be added for HTTP/2 push.
    """
    if "static_urls" not in g:
        g.static_urls = {}
    result = static_digest.static_url_for(endpoint, **values)

    if endpoint == "static":
        g.static_urls[values["filename"]] = result

    return result


def init_preload(app_obj):
    @app_obj.context_processor
    def static_url_for_processor():
        return {"static_url_for": static_url_for}

    @app_obj.after_request
    def static_urls_to_preload(response):
        """ Collect static URLs and send in Link header for preloading and HTTP/2 push """
        if "static_urls" not in g:
            return response

        do_push = False
        # Has the hashed URL of the push trigger file changed?
        if (
            PUSH_TRIGGER_FILE in g.static_urls
            and session.get("push") != g.static_urls[PUSH_TRIGGER_FILE]
        ):
            do_push = True
            session["push"] = g.static_urls[PUSH_TRIGGER_FILE]

        links = []
        for filename, url in g.static_urls.items():
            link_as = get_link_type(filename)
            if link_as is None:
                continue

            nopush = ''
            if do_push is False:
                nopush = '; nopush'

            links.append(f"<{url}>; as={link_as}; rel=preload{nopush}")

        if len(links) > 0:
            response.headers.add("Link", ", ".join(links))

        return response
