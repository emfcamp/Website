How to deploy to production

TODO: make this nicer

Production is on maxwell.emfcamp.org.

# First install
```
docker-compose -f ./docker-compose.prod.yml up -d
docker-compose -f ./docker-compose.prod.yml exec app poetry run make data
```

# To update

First, make sure the [build has completed successfully](https://github.com/emfcamp/Website/actions).

As root:
```
/root/deploy.sh
```
If there are any DB migrations which need to be applied, you'll also need to manually run:
```
docker-compose -f /root/Website/docker-compose.prod.yml exec app poetry run flask db upgrade
```
