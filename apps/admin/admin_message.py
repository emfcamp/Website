# coding=utf-8
from flask import render_template, redirect, url_for, flash
from flask_login import current_user

from wtforms import SubmitField, StringField, DateField, BooleanField
from wtforms.widgets import TextArea
from wtforms.validators import Optional

from main import db
from models.admin_message import AdminMessage

from . import admin
from .forms import Form


class AdminMessageForm(Form):
    message = StringField("Message", widget=TextArea())
    show = BooleanField("Show message")
    end = DateField("Hide message after", [Optional()])

    submit = SubmitField("Publish")

    def init_with_message(self, message):
        self.message.data = message.message
        self.show.data = message.show
        self.end.data = message.end

    def update_message(self, message):
        message.message = self.message.data
        message.show = self.show.data
        message.end = self.end.data


@admin.route("/message/<message_id>", methods=["GET", "POST"])
def message(message_id):
    msg = AdminMessage.get_by_id(message_id)
    form = AdminMessageForm()

    if form.validate_on_submit():
        form.update_message(msg)
        db.session.commit()

        flash("Updated message")
        return redirect(url_for(".all_messages"))

    form.init_with_message(msg)
    return render_template("admin/messages/edit.html", message=msg, form=form)


@admin.route("/message")
@admin.route("/message/all")
def all_messages():
    return render_template("admin/messages/all.html", messages=AdminMessage.get_all())


@admin.route("/message/new", methods=["GET", "POST"])
def new_message():
    form = AdminMessageForm()

    if form.validate_on_submit():
        msg = AdminMessage(creator=current_user)
        form.update_message(msg)

        db.session.add(msg)
        db.session.commit()

        flash("Created new message")
        return redirect(url_for(".all_messages"))

    return render_template("admin/messages/new.html", form=form)
