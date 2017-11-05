# encoding=utf-8
from decorator import decorator

from main import db, mail, external_url
from flask import session, render_template, abort, current_app as app, request
from flask.json import jsonify
from flask_login import login_user, current_user
from werkzeug import BaseResponse
from werkzeug.exceptions import HTTPException

# from models.ticket import Ticket, TicketType
from models.product import PriceTier
from models.purchase import Purchase
from models.site_state import get_site_state, get_sales_state
from models.feature_flag import get_db_flags
from models import User

from flask_mail import Message


class Currency(object):
    def __init__(self, code, symbol):
        self.code = code
        self.symbol = symbol

CURRENCIES = [
    Currency('GBP', u'£'),
    Currency('EUR', u'€'),
]
CURRENCY_SYMBOLS = dict((c.code, c.symbol) for c in CURRENCIES)


def load_utility_functions(app_obj):
    @app_obj.template_filter('price')
    def format_price(amount, currency, after=False):
        amount = '{0:.2f}'.format(amount)
        symbol = CURRENCY_SYMBOLS[currency]
        if after:
            return amount + symbol
        return symbol + amount

    @app_obj.template_filter('bankref')
    def format_bankref(bankref):
        return '%s-%s' % (bankref[:4], bankref[4:])

    @app_obj.template_filter('gcid')
    def format_gcid(gcid):
        if len(gcid) > 12:
            return 'ending %s' % gcid[-12:]
        return gcid

    @app_obj.context_processor
    def utility_processor():
        SALES_STATE = get_sales_state()
        SITE_STATE = get_site_state()

        if app.config.get('DEBUG'):
            SITE_STATE = request.args.get("site_state", SITE_STATE)
            SALES_STATE = request.args.get("sales_state", SALES_STATE)

        return dict(
            SALES_STATE=SALES_STATE,
            SITE_STATE=SITE_STATE,
            CURRENCIES=CURRENCIES,
            CURRENCY_SYMBOLS=CURRENCY_SYMBOLS,
            external_url=external_url,
            feature_enabled=feature_enabled
        )

    @app_obj.context_processor
    def currency_processor():
        currency = get_user_currency()
        return {'user_currency': currency}


def send_template_email(subject, to, sender, template, **kwargs):
    msg = Message(subject, recipients=[to], sender=sender)
    msg.body = render_template(template, **kwargs)
    mail.send(msg)


def create_current_user(email, name):
    user = User(email, name)

    db.session.add(user)
    db.session.commit()
    app.logger.info('Created new user with email %s and id: %s', email, user.id)

    # Login & make sure everything's set correctly
    login_user(user)
    assert current_user.id == user.id
    current_user.id = user.id
    return user


def get_user_currency(default='GBP'):
    return session.get('currency', default)


def set_user_currency(currency):
    session['currency'] = currency


def get_basket_cost(basket):
    return sum([p.price.value for p in basket], 0)

def get_basket_and_total():
    basket = current_user.purchased_products.filter_by(state='reserved').all()
    currency = basket[0].price.currency

    total = get_basket_cost(basket)
    app.logger.debug('Got basket %s with total %s', basket, total)
    return basket, total, currency

# This creates the user's items in the reserved state.
def create_basket(items):
    user = current_user
    currency = get_user_currency()

    basket = Purchase.safe_create_instances(db.session, user, items, currency)
    app.logger.info('Make basket with: %s', basket)

    total = get_basket_cost(basket)
    app.logger.debug('Added tickets to db for basket %s with total %s', basket, total)
    return basket, total


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
        data = {'error': str(e),
                'description': e.description}
        return jsonify(data), e.code

    except Exception as e:
        app.logger.error('Exception during json request: %r', e)
        # Werkzeug sends the response and then logs, which is fiddly
        from werkzeug.debug.tbtools import get_current_traceback
        traceback = get_current_traceback(ignore_system_exceptions=True)
        app.logger.info('Traceback %s', traceback.plaintext)

        data = {'error': e.__class__.__name__,
                'description': str(e)}
        return jsonify(data), 500

    else:
        if isinstance(response, (app.response_class, BaseResponse)):
            return response

        return jsonify(response), 200

def feature_enabled(feature):
    """
    If a feature flag is defined in the database return that,
    otherwise fall back to the config setting.
    """
    db_flags = get_db_flags()

    if feature in db_flags:
        return db_flags[feature]

    return app.config.get(feature, False)

