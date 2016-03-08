#!/bin/bash

DEBUG=${DEBUG:-false}

if [[ $(basename $PWD) != 'var' ]]; then
  echo This script should be run inside the var directory.
  exit 1
fi

find -maxdepth 1 -mtime +5 -name '*.log' -o -name '*.ofx'|while read -r f; do
  d=$f
  d=${d%.ofx}  # remove suffixes
  d=${d%.log}
  d=${d##*-}   # strip hyphen prefixes
  d=${d:0:6}   # get month
  if [[ "$d" =~ ^[0-9]{6}$ ]]; then
    $DEBUG && echo "Moving $f to $d"
    mkdir -p $d && mv "$f" $d
  fi
done
