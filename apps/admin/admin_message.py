from flask import flash, redirect, render_template, url_for
from flask_login import current_user
from wtforms import BooleanField, DateField, SelectField, StringField, SubmitField
from wtforms.validators import Optional, ValidationError
from wtforms.widgets import TextArea

from main import db
from models.admin_message import AdminMessage

from . import admin
from .forms import Form


class AdminMessageForm(Form):
    message = StringField("Message", widget=TextArea())
    show = BooleanField("Show message")
    end = DateField("Hide message after", [Optional()])

    topic = SelectField("Topic")
    new_topic = StringField("New Topic")

    submit = SubmitField("Publish")

    def populate_topics(self):
        self.topic.choices = []
        for topic in AdminMessage.get_topic_counts():
            self.topic.choices.append(topic)

    def validate_topic(form, field):
        if form.new_topic.data and form.topic.data:
            raise ValidationError("Can't create new topic and set an existing one.")

    def init_with_message(self, message):
        self.message.data = message.message
        self.show.data = message.show
        self.end.data = message.end
        self.topic.data = message.topic

    def update_message(self, message):
        message.message = self.message.data
        message.show = self.show.data
        message.end = self.end.data

        if self.topic.data:
            message.topic = self.topic.data
        else:
            message.topic = self.new_topic.data.strip().lower()


@admin.route("/message/<message_id>", methods=["GET", "POST"])
def message(message_id):
    msg = AdminMessage.get_by_id(message_id)
    form = AdminMessageForm()
    form.populate_topics()

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
    form.populate_topics()

    if form.validate_on_submit():
        msg = AdminMessage(form.message.data, current_user)

        form.update_message(msg)

        db.session.add(msg)
        db.session.commit()

        flash("Created new message")
        return redirect(url_for(".all_messages"))

    return render_template("admin/messages/new.html", form=form)
