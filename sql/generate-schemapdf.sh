#!/bin/bash

set -e

if ! hash erd 2>/dev/null; then
	echo >&2 "erd not installed, skipping generation of schema.pdf. Install: https://github.com/BurntSushi/erd"
else
	erd -i schema.er -o ../docs/schema-er-diagram.pdf -e compound
fi
