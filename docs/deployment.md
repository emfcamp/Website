How to deploy to production

# First install

    PIPENV_VENV_IN_PROJECT=1 pipenv install --deploy

# Updating

cd to the site directory:

    cd /var/www/www.emfcamp.org

Install/update the virtualenv:

    sudo pipenv install --deploy

Update the DB:

    sudo make db

Restart gunicorn:

    systemctl restart gunicorn

Monitor `/var/log/syslog` or `journalctl -fu gunicorn` for errors.
