How to deploy to production

TODO: make this nicer

Production is on maxwell.emfcamp.org.

# First install
```
docker-compose -f ./docker-compose.prod.yml up --build -d
docker-compose -f ./docker-compose.prod.yml exec app pipenv run make data
```

# To update
```
git pull
docker-compose -f ./docker-compose.prod.yml up --build -d app
```
