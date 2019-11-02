How to deploy to production

TODO: make this nicer

# First install
```
docker-compose -f ./docker-compose.yml -f ./docker-compose.prod.yml up --build -d
docker-compose -f ./docker-compose.yml -f ./docker-compose.prod.yml exec app pipenv run make data
```

# To update
```
git pull
docker-compose -f ./docker-compose.yml -f ./docker-compose.prod.yml build app
docker-compose -f ./docker-compose.yml -f ./docker-compose.prod.yml stop app
docker-compose -f ./docker-compose.yml -f ./docker-compose.prod.yml up -d app
```
