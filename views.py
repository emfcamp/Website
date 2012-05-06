from main import app
from flask import render_template, redirect, request
from flaskext.login import login_user, login_required, logout_user
from flaskext.wtf import Form, TextField, PasswordField, Required

@app.route("/")
def main():
    return render_template('main.html')

class LoginForm(Form):
    username = TextField('User Name', [Required()])
    password = PasswordField('Password', [Required()])

@app.route("/login", methods=['GET', 'POST'])
def login():
    form = LoginForm(request.form)
    if request.method == 'POST' and form.validate():
        return redirect('/')
    return render_template("login.html", form=form)

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
