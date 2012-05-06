from main import app
from models.user import User
from flask import render_template, redirect, request, flash, url_for
from flaskext.login import login_user, login_required, logout_user
from flaskext.wtf import Form, TextField, PasswordField, Required, Email

@app.route("/")
def main():
    return render_template('main.html')

class LoginForm(Form):
    email = TextField('Email', [Email()])
    password = PasswordField('Password', [Required()])

@app.route("/login", methods=['GET', 'POST'])
def login():
    form = LoginForm(request.form)
    if request.method == 'POST' and form.validate():
        user = User.query.filter_by(email=form.email.data).first()
        if user is None or not user.check_password(form.password.data):
            flash("Invalid login details!")
            return redirect(url_for('login'))
        login_user(user)
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
