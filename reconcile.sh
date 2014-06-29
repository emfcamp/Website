#!/bin/bash

dt=$(date '+%Y%m%d')
cd /var/www/www.emfcamp.org
cp ~russ/data.ofx var/data-$dt.ofx
cp ~russ/data-eur.ofx var/data-eur-$dt.ofx
ln -sf data-$dt.ofx var/data.ofx
ln -sf data-eur-$dt.ofx var/data-eur.ofx
make loadofx >>var/loadofx-$dt.log 2>&1
make reallyreconcile >>var/reconcile-$dt.log 2>&1
