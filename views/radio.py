from main import db, app

from flask import render_template, request, redirect, url_for, flash

@app.route("/radio", methods=['GET'])
def radio():
    return render_template('radio.html')

