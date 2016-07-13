import os
import csv
import json
from mailsnake import MailSnake
from mailsnake.exceptions import (
    MailSnakeException, ListAlreadySubscribedException,
    InvalidEmailException,
)

from flask import (
    render_template, redirect, request, flash, Blueprint,
    url_for, send_from_directory, abort, Markup, current_app as app
)

from .common import feature_flag, feature_enabled, site_flag
from models.ticket import TicketType
from models.payment import StripePayment
from models.site_state import get_site_state


base = Blueprint('base', __name__)


@base.route("/")
def main():
    full_price = TicketType.get_price_cheapest_full()
    if not (feature_enabled('BANK_TRANSFER') or feature_enabled('GOCARDLESS')):
        # Only card payment left
        full_price += StripePayment.premium('GBP', full_price)

    state = get_site_state()
    if app.config.get('DEBUG'):
        state = request.args.get("site_state", state)

    return render_template('home/%s.html' % state,
                           full_price=full_price)


@base.route("/", methods=['POST'])
@site_flag('TICKETS_SITE')
def main_post():
    ms = MailSnake(app.config['MAILCHIMP_KEY'])
    try:
        email = request.form.get('email')
        ms.listSubscribe(id=app.config['MAILCHIMP_LIST'], email_address=email)
        flash('Thanks for subscribing! You will receive a confirmation email shortly.')

    except InvalidEmailException as e:
        app.logger.info('Invalid email address: %r', email)
        flash("Your email address was not accepted - please check and try again.")

    except ListAlreadySubscribedException as e:
        app.logger.info('Already subscribed: %s', email)
        if e.message:
            msg = Markup(e.message)
        else:
            msg = """You are already subscribed to our list.
                     Please contact %s to update your settings.""" % app.config['TICKETS_EMAIL'][1]
        flash(msg)

    except MailSnakeException as e:
        app.logger.error('Error subscribing: %r', e)
        flash('Sorry, an error occurred.')

    return redirect(url_for('.main'))


@base.route('/favicon.ico')
def favicon():
    return send_from_directory(os.path.join(app.root_path, 'static/images'),
                               'favicon.ico', mimetype='image/vnd.microsoft.icon')


@base.route('/404')
def raise_404():
    abort(404)


@base.route('/500')
def raise_500():
    abort(500)


@base.route("/about")
def about():
    return render_template('about.html')


@base.route("/talks/")
@site_flag('TICKETS_SITE')
def talks():
    return redirect(url_for('.talks_2014'))


@base.route("/talks/2014")
@site_flag('TICKETS_SITE')
def talks_2014():
    talks = []
    talk_path = os.path.abspath(os.path.join(__file__, '..', '..', 'talks', '2014'))
    data = json.load(open(os.path.join(talk_path, 'events.json'), 'r'))
    for event in data['conference_events']['events']:
        if event['type'] not in ('lecture', 'workshop', 'other'):
            continue
        talks.append((", ".join(map(lambda speaker: speaker['full_public_name'], event['speakers'])),
                     event['title'],
                     event['abstract']
                      ))

    return render_template('talks-2014.html', talks=talks)


@base.route("/talks/2012")
@site_flag('TICKETS_SITE')
def talks_2012():
    days = {}
    talk_path = os.path.abspath(os.path.join(__file__, '..', '..', 'talks', '2012'))
    for day in ('friday', 'saturday', 'sunday'):
        reader = csv.reader(open(os.path.join(talk_path, '%s.csv' % day), 'r'))
        rows = []
        for row in reader:
            cells = [unicode(cell, 'utf-8') for cell in row]
            cells = ['' if c == '"' else c for c in cells]
            app.logger.debug(cells)
            rows.append(cells)

        days[day] = rows

    return render_template('talks-2012.html', **days)


@base.route("/about/company")
def company():
    return render_template('company.html')


@base.route('/sponsors')
def sponsors():
    return render_template('sponsors/sponsors.html')


@base.route('/sponsor')
def sponsor():
    return render_template('sponsors/sponsor.html')


@base.route("/participating")
@base.route("/get_involved")
@base.route("/contact")
@base.route("/location")
@base.route("/about")
def old_urls_2012():
    return redirect(url_for('.main'))


@base.route('/badge')
def badge():
    return redirect('https://wiki-archive.emfcamp.org/2012/wiki/TiLDA')


@base.route("/code-of-conduct")
def code_of_conduct():
    return render_template('code-of-conduct.html')


@base.route("/diversity")
def diversity():
    return render_template('diversity.html')


@base.route("/wave")
def wave():
    return redirect('https://web.archive.org/web/20130627201413/https://www.emfcamp.org/wave')


@base.route("/wave-talks")
@base.route("/wave/talks")
def wave_talks():
    return redirect('https://web.archive.org/web/20130627201413/https://www.emfcamp.org/wave/talks')


@base.route('/sine')
@base.route('/wave/sine')
@base.route('/wave/SiNE')
def sine():
    return redirect('https://wiki-archive.emfcamp.org/2014/wiki/SiNE')


@base.route("/radio", methods=['GET'])
@feature_flag('RADIO')
def radio():
    return render_template('radio.html')


@base.route('/about/branding')
def branding():
    return render_template('branding.html')


@base.route('/about/design-elements')
def design_elements():
    return render_template('design.html')


@base.route("/googlec108e6ab4f75019d.html")
def google_verification_russ():
    return "google-site-verification: googlec108e6ab4f75019d.html"
