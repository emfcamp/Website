import os
import csv
import json
from main import app
from views import feature_flag

from models.ticket import TicketType
from models.payment import StripePayment

from mailsnake import MailSnake
from mailsnake.exceptions import MailSnakeException, ListAlreadySubscribedException

from flask import (
    render_template, redirect, request, flash,
    url_for, send_from_directory, abort, Markup,
)
from jinja2.exceptions import TemplateNotFound


@app.route("/")
def main():
    if app.config.get('ARRIVALS_SITE'):
        return redirect(url_for('arrivals'))

    full_price = TicketType.get_price_cheapest_full()
    if not (app.config.get('BANK_TRANSFER') or app.config.get('GOCARDLESS')):
        # Only card payment left
        full_price += StripePayment.premium('GBP', full_price)

    return render_template('splash.html',
        ticket_sales=app.config.get('TICKET_SALES', False),
        full_price=full_price)


@app.route("/", methods=['POST'])
@feature_flag('TICKETS_SITE')
def main_post():
    ms = MailSnake(app.config['MAILCHIMP_KEY'])
    try:
        email = request.form.get('email')
        ms.listSubscribe(id='d1798f7c80', email_address=email)
        flash('Thanks for subscribing! You will receive a confirmation email shortly.')

    except ListAlreadySubscribedException, e:
        app.logger.info('Already subscribed: %s', email)
        if e.message:
            msg = Markup(e.message)
        else:
            msg = "You are already subscribed to our list. Please contact %s to update your settings." % app.config['TICKETS_EMAIL'][1]
        flash(msg)

    except MailSnakeException, e:
        app.logger.error('Error subscribing: %s', e)
        flash('Sorry, an error occurred.')

    return redirect(url_for('main'))


@app.route('/favicon.ico')
def favicon():
    return send_from_directory(os.path.join(app.root_path, 'static/images'),
                                   'favicon.ico', mimetype='image/vnd.microsoft.icon')

@app.route("/about")
def about():
    return render_template('about.html')

@app.route("/talks/")
@feature_flag('TICKETS_SITE')
def talks():
    return redirect(url_for('talks_2014'))

@app.route("/talks/2014")
@feature_flag('TICKETS_SITE')
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

    return render_template('talks_2014.html', talks=talks)

@app.route("/talks/2012")
@feature_flag('TICKETS_SITE')
def talks_2012():

    days = {}
    talk_path = os.path.abspath(os.path.join(__file__, '..', '..', 'talks', '2012'))
    for day in ('friday', 'saturday', 'sunday'):
        reader = csv.reader(open(os.path.join(talk_path, '%s.csv' % day), 'r'))
        rows = []
        for row in reader:
            rows.append([unicode(cell, 'utf-8') for cell in row])

        days[day] = rows

    return render_template('talks_2012.html', **days)


@app.route("/about/company")
def company():
    return render_template('company.html')

@app.route('/sponsors')
def sponsors():
    return render_template('sponsors/sponsors.html')

@app.route('/sponsors/<sponsor>')
def sponsor_page(sponsor):
    try:
        return render_template('sponsors/%s.html' % sponsor)
    except TemplateNotFound:
        abort(404)

@app.route("/participating")
@app.route("/get_involved")
@app.route("/contact")
@app.route("/location")
@app.route("/about")
def old_urls_2012():
    return redirect(url_for('main'))


@app.route('/badge')
def badge():
    return redirect('http://wiki-archive.emfcamp.org/2012/wiki/TiLDA')


@app.route("/code-of-conduct")
def code_of_conduct():
    return render_template('code-of-conduct.html')


@app.route("/diversity")
def diversity():
    return render_template('diversity.html')


@app.route("/wave")
def wave():
    return redirect('https://web.archive.org/web/20130627201413/https://www.emfcamp.org/wave')


@app.route("/wave-talks")
@app.route("/wave/talks")
def wave_talks():
    return redirect('https://web.archive.org/web/20130627201413/https://www.emfcamp.org/wave/talks')


@app.route('/sine')
@app.route('/wave/sine')
@app.route('/wave/SiNE')
def sine():
    return redirect('http://wiki.emfcamp.org/wiki/SiNE')
