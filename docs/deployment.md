How to deploy to production

TODO: make this nicer

Production is on maxwell.emfcamp.org.

# First install
```
docker-compose -f ./docker-compose.prod.yml up -d
docker-compose -f ./docker-compose.prod.yml exec app pipenv run make data
```

# To update
```
cd /root/Website
git pull
docker pull emfcamp/website:latest
docker-compose -f ./docker-compose.prod.yml up -d app
```
