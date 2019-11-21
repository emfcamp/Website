#!/usr/bin/env bash
set -e
PSQL="/usr/bin/psql -h postgres -U postgres"

until $PSQL -c '\q'; do
  >&2 echo "Waiting for Postgres to be available"
  sleep 1
done

$PSQL -c 'CREATE DATABASE emf_site' || true
$PSQL emf_site -c 'CREATE EXTENSION postgis' || true

export prometheus_multiproc_dir=/var/prometheus
exec poetry run gunicorn -k gthread -c gunicorn.py -w 3 -b '0.0.0.0:8000' --preload wsgi:app
