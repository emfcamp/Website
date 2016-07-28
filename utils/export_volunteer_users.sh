#!/bin/bash
sudo -u postgres psql emfcamp-site -c '\copy (select id user_id, name, email, phone, 0 checked_in from "user") to stdout with csv;' >EMFUser.csv

mysqlimport -u engelsystem -pengelsystem engelsystem --local --fields-terminated-by=',' --fields-optionally-enclosed-by='"' EMFUser.csv

