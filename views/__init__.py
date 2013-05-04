from main import app, db
from models.cfp import Proposal

from flask import \
    render_template, redirect, request, flash, \
    url_for, abort, send_from_directory, session

from sqlalchemy.sql import text

from decorator import decorator
import os, csv, time
from datetime import datetime

def feature_flag(flag):
    def call(f, *args, **kw):
        if app.config.get(flag, False) == True:
            return f(*args, **kw)
        return abort(404)
    return decorator(call)

@app.route("/")
def main():
    return render_template('main.html')

@app.route("/wave")
def wave():
    return render_template('wave.html')

@app.route("/wave/cfp", methods=['POST'])
def wave_cfp():
    prop = Proposal()
    for field in ('email', 'name', 'title', 'description', 'length'):
        setattr(prop, field, request.form.get(field))
    db.session.add(prop)
    db.session.commit()
    flash("Thanks for your submission, we'll be in touch by email.")
    return redirect(url_for("wave"))

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

@app.route("/wave-talks")
@app.route("/wave/talks")
def wave_talks():
    import json
    
    talk_path = os.path.abspath(os.path.join(__file__, '..', '..', 'talks'))
    raw_json = open(os.path.join(talk_path, 'emw-talks.json'), 'r').read()

    json_data = json.loads(raw_json)

    stages = {}
    for stage in json_data['stages']:
        events = []
        for event in stage['events']:
            # OH GOD WHAT I HAVE STOPPED CARING
            event['start'] = datetime.fromtimestamp(time.mktime(time.strptime(event['start'], '%Y-%m-%d %H:%M:%S')))
            events.append(event)

        stages[stage['name']] = stage['events']

    main_stages = zip(stages['Stage Alpha'], stages['Stage Beta'])
    workshops = stages['Workshop']

    return render_template('wave-talks.html', main_stages=main_stages, workshops=workshops)

@app.route("/about/company")
def company():
    return render_template('company.html')

@app.route("/about")
def about():
    return render_template('about.html')
    
@app.route("/contact")
def contact():
    return render_template('contact.html')    

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

@app.route('/sine')
@app.route('/wave/sine')
@app.route('/wave/SiNE')
def sine():
    return redirect('http://wiki.emfcamp.org/wiki/SiNE')

import users, admin, tickets, volunteers, radio
