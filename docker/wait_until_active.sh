#!/bin/bash

URL="http://localhost:8000"
TIMEOUT=50
INTERVAL=1
ELAPSED=0

while true; do
    if curl --output /dev/null --silent --head --fail -H 'Host: www.emfcamp.org' "$URL"; then
        exit 0
    fi

    if [[ $ELAPSED -ge $TIMEOUT ]]; then
        exit 1
    fi

    sleep $INTERVAL
    ELAPSED=$((ELAPSED + INTERVAL))
done
