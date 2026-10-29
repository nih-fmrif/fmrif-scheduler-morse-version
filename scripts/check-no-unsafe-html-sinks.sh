#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

failed=0

print_blocked() {
  local title="$1"
  local body="$2"
  echo "ERROR: ${title}" >&2
  echo "${body}" >&2
  echo >&2
}

search_templates_safe() {
  if command -v rg >/dev/null 2>&1; then
    rg -n '\|\s*safe\b' scheduler/templates --glob '*.html' || true
    return
  fi
  grep -RInE --include='*.html' '\|\s*safe\b' scheduler/templates || true
}

search_unsafe_js_sinks() {
  if command -v rg >/dev/null 2>&1; then
    rg -n 'innerHTML\s*=|outerHTML\s*=|insertAdjacentHTML\s*\(|document\.write\s*\(' \
      scheduler/static --glob '*.js' --glob '*.ts' --glob '*.tsx' || true
    return
  fi
  grep -RInE --include='*.js' --include='*.ts' --include='*.tsx' \
    'innerHTML[[:space:]]*=|outerHTML[[:space:]]*=|insertAdjacentHTML[[:space:]]*\(|document\.write[[:space:]]*\(' \
    scheduler/static || true
}

search_markup_uses() {
  if command -v rg >/dev/null 2>&1; then
    rg -n '\bMarkup\(' scheduler --glob '*.py' || true
    return
  fi
  grep -RInE --include='*.py' '\bMarkup\(' scheduler || true
}

is_allowed_js_sink() {
  # No JavaScript DOM HTML sink uses are currently allowlisted.
  return 1
}

is_allowed_markup_use() {
  local file="$1"
  local text="$2"

  if [[ "$file" != "scheduler/app.py" ]]; then
    return 1
  fi

  case "$text" in
    *"return Markup(escape(text))"*) return 0 ;;
    *"<sr-only>"*"</sr-only>"*) return 0 ;;
  esac

  return 1
}

safe_filter_hits="$(search_templates_safe)"
if [[ -n "$safe_filter_hits" ]]; then
  failed=1
  print_blocked \
    "Jinja '|safe' filter is blocked in templates." \
    "${safe_filter_hits}

Use auto-escaping by default. If a trusted HTML wrapper is required, implement it in Python with explicit escaping and tight allowlisting."
fi

unsafe_js_hits="$(search_unsafe_js_sinks)"
if [[ -n "$unsafe_js_hits" ]]; then
  disallowed_js=""
  while IFS= read -r hit; do
    [[ -z "$hit" ]] && continue
    file="${hit%%:*}"
    rest="${hit#*:}"
    _line_no="${rest%%:*}"
    text="${rest#*:}"
    if is_allowed_js_sink "$file" "$text"; then
      continue
    fi
    disallowed_js+="${hit}"$'\n'
  done <<< "$unsafe_js_hits"

  if [[ -n "$disallowed_js" ]]; then
    failed=1
    print_blocked \
      "Unsafe HTML DOM sink detected (not allowlisted)." \
      "${disallowed_js}

Use textContent/innerText for plain text. If HTML rendering is required, pre-escape untrusted values and document the trusted source."
  fi
fi

markup_hits="$(search_markup_uses)"
if [[ -n "$markup_hits" ]]; then
  disallowed_markup=""
  while IFS= read -r hit; do
    [[ -z "$hit" ]] && continue
    file="${hit%%:*}"
    rest="${hit#*:}"
    _line_no="${rest%%:*}"
    text="${rest#*:}"
    if is_allowed_markup_use "$file" "$text"; then
      continue
    fi
    disallowed_markup+="${hit}"$'\n'
  done <<< "$markup_hits"

  if [[ -n "$disallowed_markup" ]]; then
    failed=1
    print_blocked \
      "New markupsafe.Markup(...) usage detected (not allowlisted)." \
      "${disallowed_markup}

Prefer normal template auto-escaping. If Markup is necessary, escape all user-controlled segments and update this allowlist with review notes."
  fi
fi

if [[ "$failed" -ne 0 ]]; then
  exit 1
fi
