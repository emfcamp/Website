#!/bin/sh

npm install --no-audit

exec npx gulp watch
