#!/usr/bin/env bash

set -euo pipefail

if ! command -v rg >/dev/null 2>&1; then
  echo "csp-inline-style-nonce: ripgrep (rg) is required." >&2
  exit 1
fi

required='nonce="{{ current_csp_nonce() }}"'
mapfile -t style_lines < <(
  rg --color=never --line-number --no-heading '<style\b' scheduler/templates --glob '*.html'
)

if [[ ${#style_lines[@]} -eq 0 ]]; then
  exit 0
fi

bad=()
for line in "${style_lines[@]}"; do
  file="${line%%:*}"
  rest="${line#*:}"
  lineno="${rest%%:*}"
  text="${rest#*:}"

  if [[ "${text}" != *"${required}"* ]]; then
    bad+=("${file}:${lineno}")
  fi
done

if [[ ${#bad[@]} -eq 0 ]]; then
  exit 0
fi

echo "csp-inline-style-nonce: inline <style> tags must include ${required}" >&2
echo "fix these locations:" >&2
printf '%s\n' "${bad[@]}" >&2
exit 1
