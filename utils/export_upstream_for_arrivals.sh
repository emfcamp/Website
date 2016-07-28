#!/bin/bash

CONNSTR=postgresql://emfcamp-site@localhost/emfcamp-site

pg_dump -a \
  -t user \
  -t permission \
  -t ticket_type \
  -t ticket_price \
  -t ticket \
  -t ticket_transfer \
  --dbname "$CONNSTR"
