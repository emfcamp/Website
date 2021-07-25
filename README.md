This is the www.emfcamp.org web site, built with Flask & Postgres by the 
EMF web team.

[![CI Status](https://github.com/emfcamp/Website/workflows/CI/badge.svg)](https://github.com/emfcamp/Website/actions?query=workflow%3ACI)
[![Coverage Status](https://coveralls.io/repos/github/emfcamp/Website/badge.svg?branch=master)](https://coveralls.io/github/emfcamp/Website?branch=master)

## Get Involved

If you want to get involved, the best way is to join us on IRC, on #emfcamp-web on irc.libera.chat.

Join with IRCCloud: <a href="https://www.irccloud.com/invite?channel=%23emfcamp-web&amp;hostname=irc.libera.chat&amp;port=6697&amp;ssl=1" target="_blank"><img src="https://www.irccloud.com/invite-svg?channel=%23emfcamp-web&amp;hostname=irc.libera.chat&amp;port=6697&amp;ssl=1" height="18"></a>

## Getting Started

The only supported way to develop is to use [Docker](https://docker.com/) with Docker Compose (on Linux you'll need to install [Docker Compose](https://docs.docker.com/compose/install/) separately) version 1.24.0 or newer.

[Lazydocker](https://github.com/jesseduffield/lazydocker) is highly recommended
to monitor the containers.

To start all containers (and rebuild any which may have changed):
```
docker-compose build --parallel
docker-compose up
```
You should then be able to view your development server on [http://localhost:5000](http://localhost:5000).

To create some fake data in your DB, run:
```
./flask dev data
```
To stop all containers, use `docker-compose stop`
To delete all data and start over fresh you can use `docker-compose down`.

Management commands can be listed and run using the `./flask` command, which
forwards them to the flask command line within the container.

### Tests

Tests are run using the `./run_tests` script.

### Code Style

For Python, we currently use [Black](https://github.com/psf/black) and
[flake8](https://github.com/PyCQA/flake8) to enforce code style. These checks
are run by `./run_tests`.

However, it's easy to forget these checks, so you can also run them as a git
pre-commit hook using [pre-commit](https://pre-commit.com/). To set this up on
the host where you'll be using git:
```
pip3 install pre-commit
pre-commit install
```

### Adding accounts

Once you've created an account on the website, you can use `./flask make_admin` to make your user an administrator.
Or, you can create an account and simultaneously make it an admin by using `./flask make_admin -e email@domain.tld`

E-mail sending is disabled in development (but is printed out on the console). You can also log in directly by setting BYPASS_LOGIN=True in config/development.cfg and then using a URL of the form e.g. `/login/admin@test.invalid` and navigate to `/admin/`.

### Database Migrations

- `./flask db migrate -m 'Migration name'` to generate migration scripts when models have been updated.
- `./flask db upgrade` to run any migration scripts you've generated.
- `./flask db downgrade` to undo the last migration.

For more migration commands, see the [flask-migrate docs](https://flask-migrate.readthedocs.io/en/latest/).

### More Docs 

For more, see:

* [Documentation](docs/documentation.md)
* [Testing](docs/testing.md)
* [Deployment](docs/deployment.md)
* [Contributing](.github/CONTRIBUTING.md)
