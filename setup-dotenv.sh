#!/bin/bash
set -euo pipefail

sample_file=".env.sample.local"

if [ ! -f "$sample_file" ]; then
  echo "ERROR: $sample_file was not found. Create it or copy from the template." >&2
  exit 1
fi

cp "$sample_file" .env
echo "Copied $sample_file to .env"
