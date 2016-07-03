# coding=utf-8
from __future__ import division, absolute_import, print_function, unicode_literals
from . import admin, admin_required
import textwrap
import markdown
from inlinestyler.utils import inline_css
from flask import (
    render_template, redirect, request, flash,
    url_for, current_app as app, Markup
)
from wtforms import (
    SubmitField, BooleanField, HiddenField,
    FieldList, FormField, SelectField, StringField
)
from wtforms.validators import Required
from wtforms.widgets import TextArea
from main import db
from models.user import User
from models.ticket import Ticket
from models.email import EmailJob, EmailJobRecipient
from ..common.forms import Form


def format_html_email(markdown_text, subject):
    markdown_html = Markup(markdown.markdown(markdown_text))
    return inline_css(render_template('admin/email/email_template.html',
                      subject=subject, content=markdown_html))


def format_plaintext_email(markdown_text):
    return markdown_text


class EmailComposeForm(Form):
    subject = StringField('Subject', [Required()])
    text = StringField('Text', [Required()], widget=TextArea())
    preview = SubmitField('Preview Email')
    send = SubmitField('Send Email')


@admin.route("/email", methods=['GET', 'POST'])
@admin_required
def email():
    form = EmailComposeForm()
    if form.validate_on_submit() and form.preview.data is True:
        return render_template('admin/email.html', html=format_html_email(form.text.data, form.subject.data),
                               form=form)
    elif form.validate_on_submit() and form.send.data is True:
        job = EmailJob(form.subject.data, format_plaintext_email(form.text.data),
                       format_html_email(form.text.data, form.subject.data))
        db.session.add(job)
        users = User.query.join(Ticket).filter(Ticket.paid == True).group_by(User.id).all()
        for user in users:
            db.session.add(EmailJobRecipient(job, user))
        db.session.commit()
        flash("Email queued for sending to %s users" % len(users))
        return redirect(url_for('.email'))
    return render_template('admin/email.html', form=form)
