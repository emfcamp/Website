#!/bin/bash

URL="http://localhost:2342"
TIMEOUT=5
INTERVAL=1
ELAPSED=0

while true; do
    if curl --output /dev/null --silent --head --fail "$URL"; then
        exit 0
    fi

    if [[ $ELAPSED -ge $TIMEOUT ]]; then
        exit 1
    fi

    sleep $INTERVAL
    ELAPSED=$((ELAPSED + INTERVAL))
done
