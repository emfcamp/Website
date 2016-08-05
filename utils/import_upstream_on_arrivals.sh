#!/bin/bash

set -e

. utils/databases.cfg

if [[ "$1" == '' ]]; then
  upstream=$(ssh gauss.emfcamp.org sudo /var/www/www.emfcamp.org/utils/export_upstream_for_arrivals.sh)
else
  upstream=$(cat "$1")
fi

psql -d $PG_CONNSTR << SQLEND
update pg_constraint set condeferrable = true where conname like 'fk%';
-- We're not restoring these:
alter table ticket drop constraint fk_ticket_payment_id_payment;
alter table ticket drop constraint fk_ticket_refund_id_refund;
delete from payment;
delete from refund;

begin;
set constraints all deferred;
delete from ticket_transfer;
delete from ticket;
delete from ticket_price;
delete from ticket_type;
delete from permission;
delete from "user";

$upstream
commit;
set constraints all immediate;
update pg_constraint set condeferrable = false where conname like 'fk%';
SQLEND

