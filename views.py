from main import app
from flask import render_template

@app.route("/")
def main():
    return render_template('main.html')

@app.route("/sponsors")
def sponsors():
    return render_template('sponsors.html')

@app.route("/about/company")
def company():
    return render_template('company.html')


