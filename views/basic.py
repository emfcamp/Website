import os
import csv
from main import app

from models.ticket import TicketType

from mailsnake import MailSnake
from mailsnake.exceptions import MailSnakeException

from flask import (
    render_template, redirect, request, flash,
    url_for, send_from_directory,
)


@app.route("/")
def main():
    full_price = TicketType.query.get('full').get_price('GBP')
    return render_template('main.html',
        ticket_sales=app.config.get('TICKET_SALES', False),
        full_price=full_price)


@app.route("/", methods=['POST'])
def main_post():
    ms = MailSnake(app.config['MAILCHIMP_KEY'])
    try:
        email = request.form.get('email')
        ms.listSubscribe(id='d1798f7c80', email_address=email)
        flash('Thanks for subscribing! You will receive a confirmation email shortly.')
    except MailSnakeException, e:
        print e
        flash('Sorry, an error occurred.')
    return redirect(url_for('main'))


@app.route('/favicon.ico')
def favicon():
    return send_from_directory(os.path.join(app.root_path, 'static/images'),
                                   'favicon.ico', mimetype='image/vnd.microsoft.icon')

@app.route("/about")
def about():
    return render_template('about.html')


@app.route("/talks")
def talks():

    days = {}
    talk_path = os.path.abspath(os.path.join(__file__, '..', '..', 'talks'))
    for day in ('friday', 'saturday', 'sunday'):
        reader = csv.reader(open(os.path.join(talk_path, '%s.csv' % day), 'r'))
        rows = []
        for row in reader:
            rows.append([unicode(cell, 'utf-8') for cell in row])

        days[day] = rows

    return render_template('talks.html', **days)


@app.route("/about/company")
def company():
    return render_template('company.html')


@app.route("/participating")
@app.route("/get_involved")
@app.route("/contact")
@app.route("/location")
@app.route("/about")
@app.route("/sponsors")
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
