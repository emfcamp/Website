Deploying outside a development environment
===========================================

Production is on maxwell.emfcamp.org.
Staging (https://www.emfcamp-test.org) is on kelvin.emfcamp.org.

# First install

This is done after each event, following a clear of the database:
```
docker compose -f ./docker-compose.environment.yml up -d
docker compose -f ./docker-compose.environment.yml exec app flask db upgrade
```

# Deployments

Deployments run automatically when a new container is built by Github Actions
and pushed to Github Container Registry. This is done using [Watchtower](https://containrrr.dev/watchtower/).

If there are any DB migrations which need to be applied, you still need to manually run:
```
docker compose -f /root/Website/docker-compose.prod.yml exec app poetry run flask db upgrade
```

or, if the app won't start:

```
docker compose -f /root/Website/docker-compose.prod.yml run --rm --entrypoint=poetry app run flask db upgrade
```

