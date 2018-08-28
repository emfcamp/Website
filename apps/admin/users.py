# coding=utf-8
from __future__ import division, absolute_import, print_function, unicode_literals
import time

from flask import (
    render_template, redirect, flash,
    url_for, current_app as app
)
from flask_login import current_user
from flask_mail import Message
from sqlalchemy.orm import joinedload
from wtforms import SubmitField, BooleanField, StringField
from wtforms.fields.html5 import EmailField
from wtforms.validators import Required, Email, ValidationError

from . import admin
from main import db, mail
from models.user import User, generate_signup_code
from models.permission import Permission
from ..common.forms import Form


class NewUserForm(Form):
    name = StringField('Name', [Required()])
    email = EmailField('Email', [Email(), Required()])
    add = SubmitField('Add User')

    def validate_email(form, field):
        if User.does_user_exist(field.data):
            field.was_duplicate = True
            raise ValidationError('Account already exists')


@admin.route("/users", methods=['GET', 'POST'])
def users():
    form = NewUserForm()

    if form.validate_on_submit():
        email, name = form.email.data, form.name.data
        user = User(email, name)

        db.session.add(user)
        db.session.commit()
        app.logger.info('%s manually created new user with email %s and id: %s',
                        current_user.id, email, user.id)

        code = user.login_code(app.config['SECRET_KEY'])
        msg = Message('Welcome to the EMF website',
                      sender=app.config['CONTACT_EMAIL'],
                      recipients=[email])
        msg.body = render_template('emails/manually-added-user.txt',
                                   user=user, code=code)
        mail.send(msg)

        flash('Created account for: %s' % name)
        return redirect(url_for('.users'))

    users = User.query.order_by(User.id).options(joinedload(User.permissions)).all()
    return render_template('admin/users/users.html', users=users, form=form)


@admin.route("/users/<int:user_id>", methods=['GET', 'POST'])
def user(user_id):
    user = User.query.filter_by(id=user_id).one()
    permissions = Permission.query.all()

    class UserForm(Form):
        note = StringField('Check-in note (will be shown to check-in operator)')
        add_note = SubmitField('Save Note')
        change_permissions = SubmitField('Change')

    for permission in permissions:
        setattr(UserForm, "permission_" + permission.name,
                BooleanField(permission.name, default=user.has_permission(permission.name, False)))

    form = UserForm()

    if form.validate_on_submit():
        if form.change_permissions.data:
            for permission in permissions:
                field = getattr(form, "permission_" + permission.name)
                if user.has_permission(permission.name, False) != field.data:
                    app.logger.info("user %s (%s) %s: %s -> %s",
                                    user.name,
                                    user.id,
                                    permission.name,
                                    user.has_permission(permission.name, False),
                                    field.data)

                    if field.data:
                        user.grant_permission(permission.name)
                    else:
                        user.revoke_permission(permission.name)

                    db.session.commit()

        elif form.add_note.data:
            user.checkin_note = form.note.data
            db.session.commit()

        return redirect(url_for('.user', user_id=user.id))

    form.note.data = user.checkin_note
    return render_template('admin/users/user.html',
                           user=user,
                           form=form,
                           permissions=permissions)

class SignupForm(Form):
    create = SubmitField('Create link')

@admin.route("/user/signup", methods=['GET', 'POST'])
def user_signup():
    form = SignupForm()

    code = None
    if form.validate_on_submit():
        app.logger.info('User %s creating signup link', current_user)
        code = generate_signup_code(app.config['SECRET_KEY'], time.time(), current_user.id)

    return render_template('admin/users/signup.html', form=form, code=code)


