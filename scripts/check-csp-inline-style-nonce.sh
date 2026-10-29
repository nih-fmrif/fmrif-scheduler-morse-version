#!/usr/bin/env bash

set -euo pipefail

if ! command -v rg >/dev/null 2>&1; then
  echo "csp-inline-style-nonce: ripgrep (rg) is required." >&2
  exit 1
fi

mapfile -t inline_style_lines < <(
  rg --color=never --line-number --no-heading \
    -e '<style\b' \
    -e '\sstyle\s*=' \
    scheduler/templates --glob '*.html'
)

if [[ ${#inline_style_lines[@]} -eq 0 ]]; then
  exit 0
fi

echo "csp-inline-style-nonce: tracked templates must not include inline <style> tags or style= attributes." >&2
echo "fix these locations:" >&2
printf '%s\n' "${inline_style_lines[@]}" >&2
exit 1
