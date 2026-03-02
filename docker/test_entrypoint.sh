#!/usr/bin/env bash
#
# Entrypoint script for test app - skips migrations since test DB is created by pytest
#
set -e

export PGPASSWORD=postgres
PSQL="/usr/bin/psql -h postgres -U postgres"

until $PSQL -c '\q'; do
  >&2 echo "Waiting for Postgres to be available"
  sleep 1
done

# uv run doesn't remove dependencies, so run uv sync explicitly to do this.
uv sync

echo "Starting test app server (no migrations - test DB created by pytest)..."
exec uv run flask run --extra-files ./config/test.cfg -h 0.0.0.0 -p 2342 --debug
