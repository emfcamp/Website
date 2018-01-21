How to deploy to production

# Updating

cd to the site directory:

    cd /var/www/www.emfcamp.org

Install/update the virtualenv:

    PIPENV_VENV_IN_PROJECT=1 pipenv install --deploy

Update the DB:

    PIPENV_VENV_IN_PROJECT=1 make db

Restart gunicorn:

    systemctl restart gunicorn

Monitor `/var/log/syslog` for errors.
