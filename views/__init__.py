from main import app, db
from models.cfp import Proposal

from flask import \
    render_template, redirect, request, flash, \
    url_for, abort, send_from_directory, session

from sqlalchemy.sql import text

from decorator import decorator
import os, csv

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
    for day in ('friday', 'saturday', 'sunday'):
        reader = csv.reader(open('talks/%s.csv' % day, 'r'))
        
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

import users, admin, tickets, volunteers, radio
