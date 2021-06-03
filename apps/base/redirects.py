""" Redirects for old pages or common URLs. """
from flask import redirect, url_for

from . import base


@base.route("/participating")
@base.route("/get_involved")
@base.route("/location")
def old_urls_2012():
    return redirect(url_for(".main"))

@base.route("/contact")
def contact_redirect():
    return redirect(url_for('.contact'))

@base.route("/wave")
def wave():
    return redirect(
        "https://web.archive.org/web/20130627201413/https://www.emfcamp.org/wave"
    )


@base.route("/wave-talks")
@base.route("/wave/talks")
def wave_talks():
    return redirect(
        "https://web.archive.org/web/20130627201413/https://www.emfcamp.org/wave/talks"
    )


@base.route("/sine")
@base.route("/wave/sine")
@base.route("/wave/SiNE")
def sine():
    return redirect("https://wiki-archive.emfcamp.org/2014/wiki/SiNE")
