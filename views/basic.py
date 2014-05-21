from main import app

from mailsnake import MailSnake
from mailsnake.exceptions import MailSnakeException

from flask import (
    render_template, redirect, request, flash,
    url_for, send_from_directory,
)

import os, csv


@app.route("/")
def main():
    return render_template('main.html', ticket_sales=app.config.get('TICKET_SALES', False))

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

@app.route("/sponsors")
def sponsors():
    return render_template('sponsors.html')

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

@app.route("/about")
def about():
    return render_template('about.html')

@app.route("/contact")
def contact():
    return render_template('splashcontact.html')
    #return render_template('contact.html')

@app.route("/location")
def location():
    return render_template('location.html')

@app.route("/participating")
def participating():
    return render_template('participating.html')

@app.route("/get_involved")
def get_involved():
    return render_template('get_involved.html')

@app.route('/badge')
def badge():
  return redirect('http://wiki-archive.emfcamp.org/2012/wiki/TiLDA')


# WAAAAAAAAAAAAAAAAAAAAAAAAAAVE
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

