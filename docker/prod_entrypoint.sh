#!/usr/bin/env bash
set -e

docker/startup-irc-notify.sh &

export PGPASSWORD=postgres
PSQL="/usr/bin/psql -h postgres -U postgres"

until $PSQL -c '\q'; do
  >&2 echo "Waiting for Postgres to be available"
  sleep 1
done

$PSQL -c 'CREATE DATABASE emf_site' || true
$PSQL emf_site -c 'CREATE EXTENSION postgis' || true

mkdir -p $PROMETHEUS_MULTIPROC_DIR

exec poetry run gunicorn -k gthread -c gunicorn.py -w 6 -b '0.0.0.0:8000' --preload wsgi:app
