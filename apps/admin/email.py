# coding=utf-8
from __future__ import division, absolute_import, print_function, unicode_literals
from . import admin
import markdown
from inlinestyler.utils import inline_css
from flask import (
    render_template, redirect, flash,
    url_for, Markup
)
from flask import current_app as app
from flask_mail import Message
from wtforms import SubmitField, StringField
from wtforms.validators import Required
from wtforms.widgets import TextArea
from main import db, mail
from models.user import User
from models.email import EmailJob, EmailJobRecipient
from ..common.forms import Form


def format_html_email(markdown_text, subject):
    extensions = ['markdown.extensions.nl2br', 'markdown.extensions.smarty']
    markdown_html = Markup(markdown.markdown(markdown_text, extensions=extensions))
    return inline_css(render_template('admin/email/email_template.html',
                      subject=subject, content=markdown_html))


def format_plaintext_email(markdown_text):
    return markdown_text


class EmailComposeForm(Form):
    subject = StringField('Subject', [Required()])
    text = StringField('Text', [Required()], widget=TextArea())
    preview = SubmitField('Preview Email')
    send_preview_address = StringField('Preview Email Address')
    send_preview = SubmitField('Send Preview Email')
    send = SubmitField('Send Email')


@admin.route("/email", methods=['GET', 'POST'])
def email():
    form = EmailComposeForm()
    if form.validate_on_submit():
        if form.preview.data is True:
            return render_template('admin/email.html', html=format_html_email(form.text.data, form.subject.data),
                                form=form)

        elif form.send_preview.data is True:
            subject = '[PREVIEW] ' + form.subject.data
            formatted_html = format_html_email(form.text.data, subject)
            preview_email = form.send_preview_address.data

            with mail.connect() as conn:
                msg = Message(subject, sender=app.config['CONTACT_EMAIL'])
                msg.add_recipient(preview_email)
                msg.body = format_plaintext_email(form.text.data)
                msg.html = formatted_html
                conn.send(msg)

            flash("Email preview sent to %s" % preview_email)
            return render_template('admin/email.html', html=formatted_html, form=form)

        elif form.send.data is True:
            job = EmailJob(form.subject.data, format_plaintext_email(form.text.data),
                        format_html_email(form.text.data, form.subject.data))
            db.session.add(job)
            users = User.query.join(User.owned_purchases).filter_by(type='admission_ticket', is_paid_for=True).group_by(User.id).all()
            for user in users:
                db.session.add(EmailJobRecipient(job, user))
            db.session.commit()
            flash("Email queued for sending to %s users" % len(users))
            return redirect(url_for('.email'))

    return render_template('admin/email.html', form=form)
