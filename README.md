This is the www.emfcamp.org web site, built with Flask & Postgres by the
EMF web team.

[![Deploy Status](https://github.com/emfcamp/Website/workflows/Deploy/badge.svg)](https://github.com/emfcamp/Website/actions?query=workflow%3ADeploy)
[![Coverage Status](https://coveralls.io/repos/github/emfcamp/Website/badge.svg?branch=main)](https://coveralls.io/github/emfcamp/Website?branch=main)

## Get Involved

If you want to get involved, the best way is to join us on IRC, on #emfcamp-web on irc.libera.chat.

Join with IRCCloud: <a href="https://www.irccloud.com/invite?channel=%23emfcamp-web&amp;hostname=irc.libera.chat&amp;port=6697&amp;ssl=1" target="_blank"><img src="https://www.irccloud.com/invite-svg?channel=%23emfcamp-web&amp;hostname=irc.libera.chat&amp;port=6697&amp;ssl=1" height="18"></a>

## Getting Started

The only supported way to develop is to use [Docker](https://docker.com/) with Docker Compose (on Linux you'll need to install [Docker Compose](https://docs.docker.com/compose/install/) separately) version 1.24.0 or newer.

[Lazydocker](https://github.com/jesseduffield/lazydocker) is highly recommended
to monitor the containers.

To start all containers (and rebuild any which may have changed):

> [!TIP]
> **Apple Silicon Users**
> You'll probably want to build your own version of the base images as well, as
> the ones we build are amd64 only, and so painfully slow on ARM devices. This
> is unlikely to be resolved until GitHub Actions has ARM runners.
>
> ```sh
> docker build -t ghcr.io/emfcamp/website-base -f ./docker/Dockerfile.base .
> docker build -t ghcr.io/emfcamp/website-base-dev -f ./docker/Dockerfile.base-dev .
> ```

```
docker compose build --parallel
docker compose up
```

You should then be able to view your development server on [http://localhost:2342](http://localhost:2342).

To create some fake data in your DB, run:

```
./flask dev data
```

To stop all containers, use `docker compose stop`
To delete all data and start over fresh you can use `docker compose down`.

Management commands can be listed and run using the `./flask` command, which
forwards them to the flask command line within the container.

### Errors starting the dev server

e.g. `Error: While importing 'dev_server', an ImportError was raised.`

If you've just updated and you're seeing errors when starting the dev server, first make sure you
try:

        docker compose up --build

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

E-mail sending is disabled in development (but is printed out on the console). You can also log in directly by setting `BYPASS_LOGIN=True` in `config/development.cfg` and then using a URL of the form e.g. `/login/admin@test.invalid`.

### Database Migrations

- `./flask db migrate -m 'Migration name'` to generate migration scripts when models have been updated.
- `./flask db upgrade` to run any migration scripts you've generated (or populate a fresh DB).
- `./flask db downgrade` to undo the last migration.

For more migration commands, see the [flask-migrate docs](https://flask-migrate.readthedocs.io/en/latest/).

### More Docs

For more, see:

- [Documentation](docs/documentation.md)
- [Testing](docs/testing.md)
- [Deployment](docs/deployment.md)
- [Contributing](.github/CONTRIBUTING.md)
