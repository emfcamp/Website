from main import app, db
from models.user import User
from flask import render_template, redirect, request, flash, url_for
from flaskext.login import login_user, login_required, logout_user
from flaskext.wtf import Form, TextField, PasswordField, Required, Email, EqualTo
from sqlalchemy.exc import IntegrityError

@app.route("/")
def main():
    return render_template('main.html')

class LoginForm(Form):
    email = TextField('Email', [Email(), Required()])
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

class SignupForm(Form):
    name = TextField('Name', [Required()])
    email = TextField('Email', [Email(), Required()])
    password = PasswordField('Password', [Required(), EqualTo('confirm', message='Passwords do not match')])
    confirm = PasswordField('Confirm password', [Required()])

@app.route("/signup", methods=['GET', 'POST'])
def signup():
    form = SignupForm(request.form)
    if request.method == 'POST' and form.validate():
        user = User(form.email.data, form.name.data)
        user.set_password(form.password.data)
        db.session.add(user)
        try:
            db.session.commit()
        except IntegrityError, e:
            raise
        login_user(user)
        return redirect(url_for('pay'))

    return render_template("signup.html", form=form)

@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect('/')

@app.route("/pay")
@login_required
def pay():
    return render_template("pay.html")


@app.route("/sponsors")
def sponsors():
    return render_template('sponsors.html')

@app.route("/about/company")
def company():
    return render_template('company.html')
