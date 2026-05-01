#!/bin/bash
# setup_runner.sh
# Bootstraps a fresh Linux machine (self-hosted CI runner, or dev VM) to run
# this Ansible repo. macOS users want `scripts/install_dev_tools.sh` instead.
#
# Idempotent: safe to re-run.

set -euo pipefail

if [[ "$OSTYPE" == "darwin"* ]]; then
    echo "macOS detected. Use scripts/install_dev_tools.sh instead — this script is Linux-only." >&2
    exit 1
fi

if [ ! -f /etc/debian_version ]; then
    cat <<EOF >&2
This installer assumes Debian/Ubuntu. On other distros install the
equivalents with your package manager and then run:

  pip3 install --user ansible-core ansible-lint
  ansible-galaxy collection install -r ansible/requirements.yml

EOF
    exit 1
fi

echo ">>> Installing system dependencies..."
sudo apt-get update
sudo apt-get install -y python3-pip python3-venv git sshpass

echo ">>> Installing Python tooling (ansible-core + ansible-lint)..."
pip3 install --user ansible-core ansible-lint

# requirements.yml is the single source of truth for collections; using it
# here keeps this script in sync with CI (see .github/workflows/lint.yml).
echo ">>> Installing Ansible collections from requirements.yml..."
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ansible-galaxy collection install -r "$script_dir/requirements.yml"

echo ">>> Verifying installation..."
ansible --version
ansible-lint --version
