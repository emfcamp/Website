import os
import csv
import json
from mailchimp3 import MailChimp
from mailchimp3.helpers import get_subscriber_hash
from requests import HTTPError

from flask import (
    render_template, redirect, request, flash, Blueprint,
    url_for, send_from_directory, abort, current_app as app
)

from .common import feature_flag, feature_enabled, site_flag
from models.product import Product
from models.payment import StripePayment
from models.site_state import get_site_state


base = Blueprint('base', __name__)


@base.route("/")
def main():
    full_price = Product.get_cheapest_price('full')
    if not (feature_enabled('BANK_TRANSFER') or feature_enabled('GOCARDLESS')) and full_price is not None:
        # Only card payment left
        # FIXME - can't do this anymore
        full_price += StripePayment.premium('GBP', full_price)

    state = get_site_state()
    if app.config.get('DEBUG'):
        state = request.args.get("site_state", state)

    return render_template('home/%s.html' % state,
                           full_price=full_price)


@base.route("/", methods=['POST'])
@site_flag('TICKETS_SITE')
def main_post():
    # mc_user will be removed in v2.1.0
    mc = MailChimp(mc_secret=app.config['MAILCHIMP_KEY'], mc_user='python-mailchimp')
    try:
        email = request.form.get('email')

        try:
            data = mc.lists.members.create_or_update(
                list_id=app.config['MAILCHIMP_LIST'],
                subscriber_hash=get_subscriber_hash(email),
                data={'email_address': email, 'status': 'subscribed', 'status_if_new': 'pending'}
            )
            status = data.get('status')
            if status == 'pending':
                flash('Thanks for subscribing! You will receive a confirmation email shortly.')
            elif status == 'subscribed':
                flash('You were already subscribed! Thanks for checking back.')
            else:
                raise ValueError('Unexpected status %s' % status)

        except ValueError as e:
            # ugh, this library is awful
            app.logger.info('ValueError from mailchimp3 %s, assuming bad email: %r', e, email)
            flash("Your email address was not accepted - please check and try again.")

        # should also be changed to exceptions in v2.1.0
        except HTTPError as e:
            if e.response.status_code != 400:
                raise

            data = e.response.json()
            title = data.get('title')
            if title == "Member In Compliance State":
                app.logger.info('Member in compliance state: %r', email)
                flash("""You've already been unsubscribed from our list, so we can't add you again.
                         Please contact %s to update your settings.""" % app.config['TICKETS_EMAIL'][1])

            elif title == 'Invalid Resource':
                app.logger.warn('Invalid Resource from MailChimp, assuming bad email: %r', email)
                flash("Your email address was not accepted - please check and try again.")

            else:
                app.logger.warn('MailChimp returned %s: %s', title, data.get('detail'))
                flash('Sorry, an error occurred: %s.' % (title or 'unknown'))

    except Exception as e:
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


@base.route("/about/privacy")
def privacy():
    return render_template('privacy.html')


@base.route("/network")
def network():
    return redirect('https://wiki.emfcamp.org/wiki/Network')


@base.route("/talks")
@base.route("/talks/")
@site_flag('TICKETS_SITE')
def talks():
    return redirect(url_for('schedule.line_up'))


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
            cells = ['' if c == '"' else c for c in row]
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

@base.route("/google3189d9169f2faf7f.html")
def google_verification_mark():
    return "google-site-verification: google3189d9169f2faf7f.html"

@base.route("/herald")
def herald():
    return redirect('https://wiki.emfcamp.org/wiki/Herald')


