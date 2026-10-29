#!/bin/bash
set -euo pipefail

sample_file=".env.sample.local"
secret_placeholder="__GENERATE_AUTH_TEST_SECRET__"

if [ ! -f "$sample_file" ]; then
  echo "ERROR: $sample_file was not found. Create it or copy from the template." >&2
  exit 1
fi

cp "$sample_file" .env

generate_secret() {
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -hex 32
    return
  fi

  python - <<'PY'
import secrets
print(secrets.token_hex(32))
PY
}

auth_test_secret="$(generate_secret)"
tmp_env="$(mktemp)"
awk -v secret="$auth_test_secret" -v placeholder="$secret_placeholder" '
  {
    if ($0 ~ /^AUTH_TEST__SHARED_SECRET=/ && index($0, placeholder) > 0) {
      print "AUTH_TEST__SHARED_SECRET=" secret
      next
    }
    print
  }
' .env > "$tmp_env"
mv "$tmp_env" .env

echo "Copied $sample_file to .env"
echo "Generated random AUTH_TEST__SHARED_SECRET"
