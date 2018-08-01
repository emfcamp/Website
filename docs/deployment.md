How to deploy to production

# First install

    PIPENV_VENV_IN_PROJECT=1 pipenv install --deploy

# Updating

cd to the site directory:

    cd /var/www/www.emfcamp.org

Update the code

    sudo git pull

Install/update the virtualenv:

    sudo make deploy

Update the DB:

    sudo make db

Restart gunicorn:

    systemctl restart gunicorn

Monitor `journalctl -fu gunicorn` for errors.
