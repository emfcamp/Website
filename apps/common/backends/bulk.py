from flask import current_app as app
from flask_mailman.backends.smtp import EmailBackend


# We don't wrap the filebased or locmem backends for now
# as I can't think of a reason they can't share config.
# We also use the main MAIL_DEFAULT_CHARSET.


class BulkEmailBackend(EmailBackend):
    """
    Wrapper to use only BULK_MAIL_ config, as the default backend inherits anything
    set to None from MAIL_ config, which makes things hard to reason about.
    """

    def __init__(self, fail_silently=False, **kwargs):
        # This is based on:
        #  https://github.com/waynerv/flask-mailman/blob/eead080/flask_mailman/backends/smtp.py#L16
        #  https://github.com/waynerv/flask-mailman/blob/eead080/flask_mailman/__init__.py#L185

        super().__init__(
            host=app.config.get("BULK_MAIL_SERVER", "localhost"),
            port=app.config.get("BULK_MAIL_PORT", 25),
            username=app.config.get("BULK_MAIL_USERNAME"),
            password=app.config.get("BULK_MAIL_PASSWORD"),
            use_tls=app.config.get("BULK_MAIL_USE_TLS", False),
            fail_silently=fail_silently,
            use_ssl=app.config.get("BULK_MAIL_USE_SSL", False),
            timeout=app.config.get("BULK_MAIL_TIMEOUT"),
            ssl_keyfile=app.config.get("BULK_MAIL_SSL_KEYFILE"),
            ssl_certfile=app.config.get("BULK_MAIL_SSL_CERTFILE"),
            **kwargs
        )
