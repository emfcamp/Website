import json
import logging
import os.path
import re
from decimal import Decimal
from os import path
from pathlib import Path
from textwrap import wrap
from typing import Any, cast, overload
from urllib.parse import urljoin, urlparse, urlunparse

import pendulum
from decorator import decorator
from flask import (
    abort,
    render_template,
    render_template_string,
    request,
    session,
    url_for,
)
from flask import (
    current_app as app,
)
from flask.json import jsonify
from flask_login import current_user, login_user
from jinja2.utils import urlize
from markdown import markdown
from markupsafe import Markup
from werkzeug.exceptions import HTTPException
from werkzeug.wrappers import Response
from yaml import safe_load as parse_yaml

from main import JSONValue, db, external_url
from models import Currency, User, event_end, event_start, naive_utcnow
from models.basket import Basket
from models.capacity import UnlimitedType
from models.feature_flag import get_db_flags
from models.product import Price
from models.purchase import Ticket
from models.site_state import (
    get_refund_state,
    get_sales_state,
    get_signup_state,
    get_site_state,
)

from .preload import init_preload

logger = logging.getLogger(__name__)

CURRENCY_SYMBOLS = {c.value: c.symbol for c in Currency}


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
    def format_price(
        _price: Price | int | float | Decimal, _currency: Currency | str | None = None, after: bool = False
    ) -> str:
        match _price, _currency:
            case Price(), None:
                amount = f"{_price.value:.2f}"
                currency = _price.currency
            case int() | float() | Decimal(), Currency():
                amount = f"{_price:.2f}"
                currency = _currency
            case int() | float() | Decimal(), str():
                amount = f"{_price:.2f}"
                currency = Currency(_currency)
            case _:
                raise ValueError("Invalid use of price filter!")
        symbol = currency.symbol
        if after:
            return amount + symbol
        return symbol + amount

    @app_obj.template_filter("bankref")
    def format_bankref(bankref):
        if bankref.startswith("RF"):
            return " ".join(wrap(bankref, 4))
        return f"{bankref[:4]}-{bankref[4:]}"

    @app_obj.template_filter("vatrate")
    def format_vatrate(vat_rate):
        if vat_rate is None:
            return "Exempt"
        normalized = (vat_rate * 100).normalize()
        sign, digit, exp = normalized.as_tuple()
        pct = normalized if exp <= 0 else normalized.quantize(1)
        return f"{pct}%"

    @app_obj.template_test("unlimited")
    def test_unlimited(obj):
        return isinstance(obj, UnlimitedType)

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
            CURRENCY_SYMBOLS=CURRENCY_SYMBOLS,
            external_url=external_url,
            feature_enabled=feature_enabled,
            get_user_currency=get_user_currency,
            year=naive_utcnow().year,
        )

    @app_obj.context_processor
    def event_date_processor():
        def suffix(d):
            return "th" if 11 <= d <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(d % 10, "th")

        s = event_start()
        e = event_end()
        assert s.year == e.year
        if s.month == e.month:
            fancy_dates = f"""{s.strftime("%B")}<span style="white-space: nowrap">
                {s.day}<sup>{suffix(s.day)}</sup>&ndash;{e.day}<sup>{suffix(e.day)}</sup>
                {s.year}
                </span>"""

            simple_dates = f"{s.day}&ndash;{e.day} {s.strftime('%B')}"

        else:
            fancy_dates = f"""{s.strftime("%B")}
                {s.day}<sup>{suffix(s.day)}</sup>&ndash;{e.strftime("%B")}
                {e.day}<sup>{suffix(e.day)}</sup>"""

            simple_dates = f"""{s.day} {s.strftime("%B")}&ndash;{e.day} {e.strftime("%B")}"""

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
            if not isinstance(cls_list, list):
                cls_list = list(cls_list)
            classes = " ".join(cls_list)

            alt = kwargs.get("alt", name)
            return Markup(f'<img src="/static/icons/{name}.svg" class="octicon {classes}" alt="{alt}">')

        return {"octicon": octicon}

    @app_obj.template_filter("pretty_text")
    def pretty_text(text):
        text = text.strip(" \n\r")
        # urlize calls markupsafe.escape before anything else
        text = urlize(text, trim_url_limit=40)
        text = "\n".join(f"<p>{para}</p>" for para in re.split(r"[\r\n]+", text))
        return Markup(text)

    @app_obj.context_processor
    def mailing_list_processor():
        def mailing_list(list):
            """Renders a signup form for the requested list."""
            if list not in app_obj.config["LISTMONK_LISTS"]:
                msg = f"The list '{list}' is not configured. Add it to your config file under LISTMONK_LISTS."
                raise ValueError(msg)

            return Markup(render_template("home/_mailing_list_form.html", list=list))

        return {"mailing_list": mailing_list}

    @app_obj.template_filter("ticket_state_label")
    def ticket_state_label(ticket: Ticket) -> Markup:
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


def create_current_user(email: str, name: str) -> User:
    user = User(email, name)

    db.session.add(user)
    db.session.commit()
    app.logger.info("Created new user with email %s and id: %s", email, user.id)

    # Login & make sure everything's set correctly
    login_user(user)
    assert current_user.id == user.id
    return user


def get_user_currency(default: Currency = Currency.GBP) -> Currency:
    """Fetch the user's currency from the session.

    If it's missing or invalid, returns `default`
    """
    if from_session := session.get("currency", None):
        try:
            return Currency(from_session)
        except ValueError:
            logger.warning(
                "Invalid currency retrieved from session '%s', defaulting to %s", from_session, default
            )
    return default


def set_user_currency(currency: Currency | str) -> None:
    """Set the user's currency in their session.

    If currency is str, raises ValueError if it's not one of the valid `Currency` options.
    """
    if isinstance(currency, str):
        currency = Currency(currency)
    basket = Basket.from_session(current_user, get_user_currency())
    basket.set_currency(currency)
    session["currency"] = currency.value


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
        if isinstance(response, app.response_class | Response):
            return response

        return jsonify(response), 200


def feature_enabled(feature: str) -> bool:
    """
    If a feature flag is defined in the database return that,
    otherwise fall back to the config setting.
    """
    # the cache decorator doesn't pass through types, so we have to cast here
    db_flags = cast(dict[str, bool], get_db_flags())

    if feature in db_flags:
        return db_flags[feature]

    from_conf = app.config.get(feature, False)
    if isinstance(from_conf, bool):
        return from_conf
    logger.warning("Feature '%s' read from config was not a boolean! using bool()")
    return bool(from_conf)


def archive_file(year, *path, raise_404=True):
    """Return the path to a given file within the archive.
    Optionally raise 404 if it doesn't exist.
    """
    file_path = os.path.abspath(os.path.join(__file__, "..", "..", "..", "exports", str(year), *path))

    if not os.path.exists(file_path):
        if raise_404:
            abort(404)
        else:
            return None

    return file_path


def load_archive_file(year: int, *path: str, raise_404: bool = True) -> JSONValue:
    """Load the contents of a JSON file from the archive, and optionally
    abort with a 404 if it doesn't exist.
    """
    json_path = archive_file(year, *path, raise_404=raise_404)
    if json_path is None:
        return None
    return cast(JSONValue, json.load(open(json_path)))


def page_template(metadata, template):
    if "page_template" in metadata:
        return metadata["page_template"]

    if "show_nav" not in metadata or metadata["show_nav"] is True:
        return template
    return "static_page.html"


def render_markdown(source: str, template: str = "about/template.html", **view_variables: Any) -> str:
    assert app.template_folder is not None
    template_root = Path(path.join(app.root_path, app.template_folder)).resolve()
    source_file = template_root.joinpath(f"{source}.md").resolve()

    if not source_file.is_relative_to(template_root) or not source_file.exists():
        return abort(404)

    with open(source_file) as f:
        source = f.read()
        (metadata, content) = source.split("---", 2)
        metadata = parse_yaml(metadata)
        content = Markup(
            markdown(
                render_template_string(content),
                extensions=["markdown.extensions.nl2br"],
            )
        )

    view_variables.update(content=content, title=metadata["title"])
    return render_template(page_template(metadata, template), **view_variables)


def make_safe_url(target: str) -> str | None:
    ref_url = urlparse(request.host_url)
    test_url = urlparse(urljoin(request.host_url, target))
    if test_url.scheme in ("http", "https") and ref_url.netloc == test_url.netloc:
        return urlunparse(test_url)
    return None


@overload
def get_next_url(default: str) -> str: ...


@overload
def get_next_url(default: None) -> str | None: ...


def get_next_url(default=None):
    next_url = request.args.get("next")
    if next_url:
        if safe_url := make_safe_url(next_url):
            return safe_url
        app.logger.error(f"Dropping unsafe next URL {repr(next_url)}")
    if default is None:
        default = url_for(".account")
    return default
