from decorator import decorator
from datetime import datetime
import json
import re
import os.path
from textwrap import wrap
import pendulum
from dataclasses import dataclass

from main import db, external_url
from flask import session, abort, current_app as app, render_template
from markupsafe import Markup
from flask.json import jsonify
from flask_login import login_user, current_user
from werkzeug.wrappers import Response
from werkzeug.exceptions import HTTPException
from jinja2.utils import urlize

from models.basket import Basket
from models.product import Price
from models.purchase import Ticket
from models.site_state import (
    get_refund_state,
    get_sales_state,
    get_signup_state,
    get_site_state,
)
from models.feature_flag import get_db_flags
from models import User, event_start, event_end

from .preload import init_preload


@dataclass
class Currency():
    code: str
    symbol: str


CURRENCIES = [Currency("GBP", "£"), Currency("EUR", "€")]
CURRENCY_SYMBOLS = {c.code: c.symbol for c in CURRENCIES}


def load_utility_functions(app_obj):
    # NOTE: do not reference the session, request, or g objects in
    # template functions. It will raise an error when called outside
    # of a request context (for example when sending emails from a
    # command line job)

    init_preload(app_obj)

    @app_obj.template_filter("time_ago")
    def time_ago(date):
        return pendulum.instance(date).diff_for_humans()

    @app_obj.template_filter("iban")
    def format_iban(iban):
        return " ".join(wrap(iban, 4))

    @app_obj.template_filter("sort_code")
    def format_sort_code(sort_code):
        return "-".join(wrap(sort_code, 2))

    @app_obj.template_filter("price")
    def format_price(price, currency=None, after=False):
        if isinstance(price, Price):
            currency = price.currency
            amount = price.value
            # TODO: look up after from CURRENCIES
        else:
            amount = price
        amount = "{0:.2f}".format(amount)
        symbol = CURRENCY_SYMBOLS[currency]
        if after:
            return amount + symbol
        return symbol + amount

    @app_obj.template_filter("bankref")
    def format_bankref(bankref):
        if bankref.startswith("RF"):
            return " ".join(wrap(bankref, 4))
        return "%s-%s" % (bankref[:4], bankref[4:])

    @app_obj.template_filter("vatrate")
    def format_vatrate(vat_rate):
        if vat_rate is None:
            return "Exempt"
        normalized = (vat_rate * 100).normalize()
        sign, digit, exp = normalized.as_tuple()
        pct = normalized if exp <= 0 else normalized.quantize(1)
        return f"{pct}%"

    @app_obj.context_processor
    def utility_processor():
        SALES_STATE = get_sales_state()
        SITE_STATE = get_site_state()
        REFUND_STATE = get_refund_state()
        SIGNUP_STATE = get_signup_state()

        return dict(
            SALES_STATE=SALES_STATE,
            SITE_STATE=SITE_STATE,
            REFUND_STATE=REFUND_STATE,
            SIGNUP_STATE=SIGNUP_STATE,
            CURRENCIES=CURRENCIES,
            CURRENCY_SYMBOLS=CURRENCY_SYMBOLS,
            external_url=external_url,
            feature_enabled=feature_enabled,
            get_user_currency=get_user_currency,
            year=datetime.utcnow().year,
        )

    @app_obj.context_processor
    def event_date_processor():
        def suffix(d):
            return (
                "th" if 11 <= d <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(d % 10, "th")
            )

        s = event_start()
        e = event_end()
        assert s.year == e.year
        if s.month == e.month:
            fancy_dates = f"""{s.strftime('%B')}<span style="white-space: nowrap">
                {s.day}<sup>{suffix(s.day)}</sup>&ndash;{e.day}<sup>{suffix(e.day)}</sup>
                {s.year}
                </span>"""

            simple_dates = f"{s.day}&ndash;{e.day} {s.strftime('%B')}"

        else:
            fancy_dates = f"""{s.strftime("%B")}
                {s.day}<sup>{suffix(s.day)}</sup>&ndash;{e.strftime("%B")}
                {e.day}<sup>{suffix(e.day)}</sup>"""

            simple_dates = (
                f"""{s.day} {s.strftime("%B")}&ndash;{e.day} {e.strftime("%B")}"""
            )

        return {
            "fancy_dates": Markup(fancy_dates),
            "simple_dates": Markup(simple_dates),
            "event_start": s,
            "event_end": e,
            "event_year": s.year,
        }

    @app_obj.context_processor
    def octicons_processor():
        def octicon(name, **kwargs):
            cls_list = kwargs.get("class", [])
            if type(cls_list) != list:
                cls_list = list(cls_list)
            classes = " ".join(cls_list)

            alt = kwargs.get("alt", name)
            return Markup(
                f'<img src="/static/icons/{name}.svg" class="octicon {classes}" alt="{alt}">'
            )

        return {"octicon": octicon}

    @app_obj.template_filter("pretty_text")
    def pretty_text(text):
        text = text.strip(" \n\r")
        text = urlize(text, trim_url_limit=40)
        text = "\n".join(f"<p>{para}</p>" for para in re.split(r"[\r\n]+", text))
        return Markup(text)

    @app_obj.context_processor
    def contact_form_processor():
        def contact_form(list):
            """Renders a contact form for the requested list."""
            if list not in app_obj.config["LISTMONK_LISTS"]:
                msg = f"The list '{list}' is not configured. Add it to your config file under LISTMONK_LISTS."
                raise ValueError(msg)

            return Markup(render_template("home/_mailing_list_form.html", list=list))

        return {"contact_form": contact_form}

    @app_obj.template_filter("ticket_state_label")
    def ticket_state_label(ticket: Ticket):
        # see docs/ticket_states.md

        match ticket.state:
            case "paid":
                cls = "success"
            case "cancelled":
                cls = "danger"
            case "payment-pending":
                cls = "warning"
            case "refunded":
                cls = "default"
            case "reserved":
                cls = "info"
            case "admin-reserved":
                cls = "info"
            case _:
                cls = "default"

        return Markup(f'<span class="label label-{cls}">{ticket.state}</span>')


def create_current_user(email: str, name: str):
    user = User(email, name)

    db.session.add(user)
    db.session.commit()
    app.logger.info("Created new user with email %s and id: %s", email, user.id)

    # Login & make sure everything's set correctly
    login_user(user)
    assert current_user.id == user.id
    # FIXME: why do we do this?
    current_user.id = user.id
    return user


def get_user_currency(default="GBP"):
    return session.get("currency", default)


def set_user_currency(currency):
    basket = Basket.from_session(current_user, get_user_currency())
    basket.set_currency(currency)
    session["currency"] = currency


def feature_flag(feature):
    """
    Decorator for toggling features within the app.

    For now, returns a 404 if the feature is disabled.
    """

    def call(f, *args, **kw):
        if feature_enabled(feature):
            return f(*args, **kw)
        return abort(404)

    return decorator(call)


def site_flag(site):
    """
    Used currently for toggling off features
    that haven't been separated by blueprint
    """

    def call(f, *args, **kw):
        if app.config.get(site):
            return f(*args, **kw)
        return abort(404)

    return decorator(call)


def require_permission(permission):
    def call(f, *args, **kwargs):
        if current_user.is_authenticated:
            if current_user.has_permission(permission):
                return f(*args, **kwargs)
            abort(404)
        return app.login_manager.unauthorized()

    return decorator(call)


@decorator
def json_response(f, *args, **kwargs):
    try:
        response = f(*args, **kwargs)

    except HTTPException as e:
        data = {"error": str(e), "description": e.description}
        return jsonify(data), e.code

    except Exception as e:
        app.logger.exception("Exception during json request: %r", e)

        data = {"error": e.__class__.__name__, "description": str(e)}
        return jsonify(data), 500

    else:
        if isinstance(response, (app.response_class, Response)):
            return response

        return jsonify(response), 200


def feature_enabled(feature) -> bool:
    """
    If a feature flag is defined in the database return that,
    otherwise fall back to the config setting.
    """
    db_flags = get_db_flags()

    if feature in db_flags:
        return db_flags[feature]

    return app.config.get(feature, False)


def archive_file(year, *path, raise_404=True):
    """Return the path to a given file within the archive.
    Optionally raise 404 if it doesn't exist.
    """
    file_path = os.path.abspath(
        os.path.join(__file__, "..", "..", "..", "exports", str(year), *path)
    )

    if not os.path.exists(file_path):
        if raise_404:
            abort(404)
        else:
            return None

    return file_path


def load_archive_file(year: int, *path, raise_404=True):
    """Load the contents of a JSON file from the archive, and optionally
    abort with a 404 if it doesn't exist.
    """
    json_path = archive_file(year, *path, raise_404=raise_404)
    if json_path is None:
        return None
    return json.load(open(json_path, "r"))
