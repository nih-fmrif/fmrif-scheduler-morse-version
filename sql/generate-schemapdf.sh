#!/bin/bash

set -e

has() {
	hash "$1" 2>/dev/null
}

fail() {
	echo "$@" 1>&2
	exit 0
}

if ! has erd; then
	fail "erd not installed, skipping generation of ER diagram. Install: https://github.com/BurntSushi/erd"
fi
if ! has dot; then
	fail "graphviz is required to format ER diagram"
fi
if ! has inkscape; then
	fail "inkscape is require to postprocess ER diagram"
fi

erd -i schema.er -f dot -e compound |
	# make edges easier to read; change style to solid, remove head and tail labels
	sed 's/style=dashed/style=solid/' |
	sed 's/headlabel=.*$//g' |
	sed 's/taillabel=[^]]*//g' |
	# inkscape can't handle underlines properly (!?)
	sed 's@<U>@<B>@g' | sed 's@</U>@</B>@g' |
	dot -Tsvg |
	# fix title
	sed 's@<title>%3</title>@<title>ER diagram</title>@' |
	# pandoc embeds text from svg as a single string joined without spaces as alt for figure
	# this is insane, so we have to reduce the text to paths
	inkscape -p --export-text-to-path -o ../docs/er-diagram.svg
