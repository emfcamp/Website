#!/bin/bash

set -e

. utils/databases.cfg

pg_dump -a \
  -t user \
  -t permission \
  -t ticket_type \
  -t ticket_price \
  -t ticket \
  -t ticket_transfer \
  -d $PG_CONNSTR
