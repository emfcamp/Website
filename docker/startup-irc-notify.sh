#!/bin/bash
set -e

if [[ -z "$IRCCAT" ]]; then
  exit
fi
MIGRATION_GRACE_SECS=${MIGRATION_GRACE_SECS:-90}

send() {
  echo "Sending IRC notification: $1"
  echo "$1" | curl -m5 telnet://$IRCCAT ||:
}

db_head=$(poetry run flask db current)
heads=$(poetry run flask db heads)
git_head=$(git rev-parse HEAD|cut -c -8)

SGR_BOLD=$'\x1b[1m'
SGR_GREEN=$'\x1b[32m'
SGR_RESET=$'\x1b[0m'

msg="${SGR_BOLD}Website${SGR_RESET} starting (${SGR_GREEN}${git_head}${SGR_RESET}),"
if [[ "$db_head" == "$heads" ]]; then
  send "$msg no DB changes"
  exit
fi
send "$msg DB migration required"

sleep $MIGRATION_GRACE_SECS

db_head=$(poetry run flask db current)
heads=$(poetry run flask db heads)

if [[ "$db_head" != "$heads" ]]; then
  send "${SGR_BOLD}Website${SGR_RESET} DB migration ${SGR_BOLD}not complete${SGR_RESET} after $MIGRATION_GRACE_SECS seconds"
fi

