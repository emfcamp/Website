#!/usr/bin/env bash
PSQL="docker-compose run postgres psql postgres://postgres@postgres"

until $PSQL -c '\q'; do
  >&2 echo "Waiting for Postgres to be available"
  sleep 1
done

$PSQL -c 'CREATE DATABASE emf_site'
$PSQL/emf_site -c 'CREATE EXTENSION postgis'
$PSQL -c 'CREATE DATABASE emf_site_test'
$PSQL/emf_site_test -c 'CREATE EXTENSION postgis'
