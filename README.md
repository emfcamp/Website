This is the www.emfcamp.org web site, built with Flask & Postgres by the 
EMF web team.

## Get Involved

If you want to get involved, the best way is to join us on IRC, on #emfcamp-web on chat.freenode.net.

Join with IRCCloud: <a href="https://www.irccloud.com/invite?channel=%23emfcamp-web&amp;hostname=irc.freenode.net&amp;port=6697&amp;ssl=1" target="_blank"><img src="https://www.irccloud.com/invite-svg?channel=%23emfcamp-web&amp;hostname=irc.freenode.net&amp;port=6697&amp;ssl=1" height="18"></a>

## Getting Started

The only supported way to develop is to use [Docker](https://docker.com/) with Docker Compose (on Linux you'll need to install [Docker Compose](https://docs.docker.com/compose/install/) separately).

[Lazydocker](https://github.com/jesseduffield/lazydocker) is highly recommended
to monitor the containers.

To start all containers (and rebuild any which may have changed):
```
docker-compose up --build
```
You should then be able to view your development server on [http://localhost:5000](http://localhost:5000).

To create some fake data in your DB, run:
```
docker-compose exec app pipenv run make dev-data
```
To stop all containers, use `docker-compose stop`
To delete all data and start over fresh you can use `docker-compose down`.

To run management commands, prefix them with `docker-compose exec app pipenv run`.

### Adding accounts

Once you've created an account on the website, you can use `make admin` to make your user an administrator.
Or, you can create an account and simultaneously make it an admin by using `make admin ARGS="-e email@domain.tld"`

E-mail sending is disabled in development (but is printed out on the console). You can also login directly by setting BYPASS_LOGIN=True in config/development.cfg and then using a URL of the form e.g. `/login/admin@test.invalid` and navigate to `/admin/`.

For more, see:

* [Documentation](docs/documentation.md)
* [Testing](docs/testing.md)
* [Deployment](docs/deployment.md)
* [Contributing](.github/CONTRIBUTING.md)


### Additional Notes

- `make migrate` to generate migration scripts when models have been updated.
- `make db` to run any migration scripts you've generated.
