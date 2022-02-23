#!/bin/bash
set -e

if [[ -z "$IRCCAT" ]]; then
  exit
fi
MIGRATION_GRACE_SECS=${MIGRATION_GRACE_SECS:-90}

send() {
  echo "Sending IRC notification: $1"
  echo "#emfcamp-web $1" | curl -s -m5 telnet://$IRCCAT ||:
}

db_head=$(poetry run flask db current)
heads=$(poetry run flask db heads)
git_head=$(git rev-parse HEAD|cut -c -8)

msg="%BOLDWebsite%NORMAL starting (%DGREEN${git_head}%NORMAL),"
if [[ "$db_head" == "$heads" ]]; then
  send "$msg no DB changes"
  exit
fi
send "$msg DB migration required"

sleep $MIGRATION_GRACE_SECS

db_head=$(poetry run flask db current)
heads=$(poetry run flask db heads)

if [[ "$db_head" != "$heads" ]]; then
  send "%BOLDWebsite%NORMAL DB migration %BOLDnot complete%NORMAL after $MIGRATION_GRACE_SECS seconds"
fi

