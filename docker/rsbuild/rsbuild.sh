#!/bin/sh

npm install --no-audit

exec npx rsbuild --mode dev
