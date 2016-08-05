#!/bin/bash

set -e

. utils/databases.cfg

tempdir=$(mktemp -d)
cd $tempdir

psql -d $PG_CONNSTR -c '\copy (select id user_id, name, email, phone, case when exists (select 1 from ticket t, ticket_checkin tc where t.user_id = u.id and tc.ticket_id = t.id and tc.checked_in = true) then 1 else 0 end checked_in from "user" u) to stdout with csv;' >EMFUser.csv

mysqlimport -u $MYSQL_USER -p${MYSQL_PASS} -h $MYSQL_HOST $MYSQL_DB --local --fields-terminated-by=',' --fields-optionally-enclosed-by='"' -r EMFUser.csv
echo "update User u set Gekommen = 1 where exists (select 1 from EMFUserUser eu, EMFUser e where eu.user_id = e.user_id and u.UID = eu.UID and e.checked_in = 1) and Gekommen = 0;"|mysql -u $MYSQL_USER -p${MYSQL_PASS} -h $MYSQL_HOST $MYSQL_DB

cd

if [[ "$1" != '-k' ]]; then
  rm $tempdir/EMFUser.csv
  rmdir $tempdir
fi

