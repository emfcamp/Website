How to deploy to production

Production is on maxwell.emfcamp.org.

# First install

This is done after each event, following a clear of the database:
```
docker-compose -f ./docker-compose.prod.yml up -d
docker-compose -f ./docker-compose.prod.yml exec app flask db upgrade
```

# Deployments

Deployments run automatically when a new container is built by Github Actions
and pushed to Github Container Registry. This is done using [Watchtower](https://containrrr.dev/watchtower/).

If there are any DB migrations which need to be applied, you still need to manually run:
```
docker-compose -f /root/Website/docker-compose.prod.yml exec app poetry run flask db upgrade
```
