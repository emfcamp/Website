from flask import current_app as app
from flask_script import Command, Option
from flask_mail import Message

from main import mail, db
from models.user import User
from models.permission import Permission
from models.email import EmailJobRecipient

class MakeAdmin(Command):
    """
    Make the first user in the DB an admin for testing purposes
    """
    option_list = (Option('-u', '--user-id', dest='user_id', help="The user_id to make an admin (defaults to first)"),)

    def run(self, user_id):
        if user_id:
            user = User.query.get(user_id)
        else:
            user = User.query.order_by(User.id).first()

        user.grant_permission('admin')
        db.session.commit()

        print('%r is now an admin' % user.name)

class CreatePermissions(Command):
    def run(self):
        for permission in ('admin', 'arrivals', 'cfp_reviewer', 'cfp_anonymiser', 'cfp_schedule'):
            if not Permission.query.filter_by(name=permission).first():
                db.session.add(Permission(permission))

        db.session.commit()

class SendEmails(Command):
    def run(self):
        with mail.connect() as conn:
            for rec in EmailJobRecipient.query.filter(EmailJobRecipient.sent == False):  # noqa
                self.send_email(conn, rec)

    def send_email(self, conn, rec):
        msg = Message(rec.job.subject, sender=app.config['CONTACT_EMAIL'])
        msg.add_recipient(rec.user.email)
        msg.body = rec.job.text_body
        msg.html = rec.job.html_body
        conn.send(msg)
        rec.sent = True
        db.session.add(rec)
        db.session.commit()
