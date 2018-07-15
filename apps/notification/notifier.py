import logging
import nexmo

logger = logging.getLogger(__name__)

from flask import (
    render_template
)
# from flask_login import current_user
from flask_mail import Message

from main import mail

# client = nexmo.Client(key = '5eca7e22', secret = 'LmQYJ3A3HkK9y1pL')

# def notify(phone_number, message):
#     logger.info("Sending SMS Message to %s (%s)", phone_number, message)
#     client.send_message({
#         'from' : 'EMF Camp',
#         'to' : phone_number,
#         'text': message,
#     })

# notify('+447786128622', 'this is a test3')

class Notifier:
    client = nexmo.Client(key = '5eca7e22', secret = 'LmQYJ3A3HkK9y1pL')

    def notify(phone_number, message):
        logger.info("Sending SMS Message to %s (%s)", phone_number, message)
        client.send_message({
            'from' : 'EMF Camp',
            'to' : phone_number,
            'text': message,
        })
    
    def notify_many(phone_numbers, message):
        for phone_number in phone_numbers:
            notify(phone_number, message)


    def notify_emails(emails, subject, message):
        for email in emails:
            notifiy(email, subject, message)

    def notify_email(email, subject, message):
        template = 'notification/email/volunteer_request'
        
        while True:
            msg = Message(subject, sender=app.config['CONTENT_EMAIL'],
                        recipients=[email])
            msg.body = render_template(template)

            # Due to https://bugs.python.org/issue27240 heaader re-wrapping may
            # occasionally fail on arbitrary strings. We try and avoid this by
            # removing the talk title in the subject when the error occurrs.
            # FIXME: This is disgusting and we should remove it when we're on a
            # fixed version of python.
            try:
                mail.send(msg)
                return True
            except AttributeError as e:
                if proposal_title:
                    app.logger.error('Failed to email proposal %s, with title, retrying: %s', proposal.id, e)
                    proposal_title = ""
                else:
                    app.logger.error('Failed to email proposal %s without title, ABORTING: %s', proposal.id, e)
                    return False