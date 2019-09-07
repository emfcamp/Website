#!/usr/bin/env bash
set -e
PSQL="/usr/bin/psql -h postgres -U postgres"

until $PSQL -c '\q'; do
  >&2 echo "Waiting for Postgres to be available"
  sleep 1
done

$PSQL -c 'CREATE DATABASE emf_site' || true
$PSQL emf_site -c 'CREATE EXTENSION postgis' || true
$PSQL -c 'CREATE DATABASE emf_site_test' || true
$PSQL emf_site_test -c 'CREATE EXTENSION postgis' || true


while :
do
	pipenv run make db || true
	pipenv run make data || true
	pipenv run make run || true
	sleep 5
done;
