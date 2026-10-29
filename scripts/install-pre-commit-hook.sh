#!/usr/bin/env bash
set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
hook_path="${repo_root}/.git/hooks/pre-commit"

mkdir -p "$(dirname "${hook_path}")"

cat >"${hook_path}" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
repo_root="$(git -C "${here}/../.." rev-parse --show-toplevel)"

cd "${repo_root}"
exec pixi run -e dev pre-commit hook-impl --config=.pre-commit-config.yaml --hook-type=pre-commit --hook-dir "${here}" -- "$@"
EOF

chmod 0755 "${hook_path}"
printf 'Installed pre-commit hook at %s\n' "${hook_path}"
