#!/usr/bin/env bash
# Install dev/lint tooling for this repo.
#
# Installs:
#   - pre-commit (drives all the .pre-commit-config.yaml hooks)
#   - ansible + ansible-lint (used by the system hook in .pre-commit-config.yaml)
#   - ansible collections from ansible/requirements.yml
#
# Other linters (shellcheck, yamllint, ruff) are auto-installed by pre-commit
# in isolated environments on first run; no system install needed for them.
#
# Idempotent: safe to re-run. Targets macOS via Homebrew; non-macOS runs print
# guidance and exit.
set -euo pipefail

if [[ "$(uname -s)" != "Darwin" ]]; then
    cat <<EOF
This installer targets macOS. On Linux, install the equivalents with your
package manager and then run:

  pre-commit install
  ansible-galaxy collection install -r ansible/requirements.yml

Required: pre-commit, ansible-core, ansible-lint
EOF
    exit 1
fi

if ! command -v brew >/dev/null 2>&1; then
    echo "Homebrew is required. See https://brew.sh" >&2
    exit 1
fi

echo "==> Installing tools via Homebrew..."
brew install pre-commit ansible ansible-lint

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"

echo "==> Installing pre-commit git hooks..."
pre-commit install

echo "==> Installing ansible collections..."
ansible-galaxy collection install -r ansible/requirements.yml

cat <<EOF

Done. To lint everything now:
  pre-commit run --all-files

Hooks will also run automatically on \`git commit\`. Skip on a single commit
with \`git commit --no-verify\` if needed (CI still gates on the same rules).
EOF
