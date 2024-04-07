#!/bin/bash
set -e

# Convert png/jpeg files to webp, without re-converting existing webp files.

find "$1" -type f \( -iname "*.jpg" -o -iname "*.png" \) | while read -r file; do
    webp_file="$file.webp"
    if [ ! -f "$webp_file" ]; then
        cwebp -quiet "$file" -o "$webp_file"
    fi
done