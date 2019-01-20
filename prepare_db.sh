#!/usr/bin/env bash
docker-compose run postgres psql postgres://postgres@postgres -c 'CREATE DATABASE emf_site'
docker-compose run postgres psql postgres://postgres@postgres/emf_site -c 'CREATE EXTENSION postgis'
docker-compose run postgres psql postgres://postgres@postgres -c 'CREATE DATABASE emf_site_test'
docker-compose run postgres psql postgres://postgres@postgres/emf_site_test -c 'CREATE EXTENSION postgis'
