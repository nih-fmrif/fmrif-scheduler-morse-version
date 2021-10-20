#!/bin/bash

set -e

if ! hash erd 2>/dev/null; then
	echo >&2 "erd not installed, skipping generation of schema.pdf. Install: https://github.com/BurntSushi/erd"
else
	erd -i schema.er -f dot -e compound |
		# make edges easier to read; change style to solid, remove head and tail labels
		sed 's/style=dashed/style=solid/' |
		sed 's/headlabel=.*$//g' |
		sed 's/taillabel=[^]]*//g' |
		dot -Tpdf -o ../docs/schema-er-diagram.pdf
fi
