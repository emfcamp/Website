from main import app
from flask import render_template, redirect
from flaskext.login import login_user, login_required, logout_user

@app.route("/")
def main():
    return render_template('main.html')

@app.route("/login")
def login():
    return render_template("login.html")

@app.route("/signup")
def signup():
    return render_template("signup.html")

@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect('/')

@app.route("/sponsors")
def sponsors():
    return render_template('sponsors.html')

@app.route("/about/company")
def company():
    return render_template('company.html')
