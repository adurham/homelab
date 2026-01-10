#!/bin/bash
# setup_runner.sh
# Bootstraps a fresh machine (CI Runner or Workstation) to run this Ansible collection.

set -e

echo ">>> Installing System Dependencies..."
# Detect OS (Debian/Ubuntu assumed for runners)
if [ -f /etc/debian_version ]; then
    sudo apt-get update
    sudo apt-get install -y python3-pip git sshpass
elif [[ "$OSTYPE" == "darwin"* ]]; then
    # MacOS (Assumes Homebrew)
    echo "MacOS detected. Ensuring python3 and sshpass..."
    brew install python3 hudochenkov/sshpass/sshpass 2>/dev/null || true
fi

echo ">>> Installing Python Dependencies..."
pip3 install ansible ansible-lint netaddr passlib

echo ">>> Installing Ansible Collections..."
ansible-galaxy collection install \
    community.general \
    community.docker \
    community.crypto \
    ansible.posix \
    ansi.passthru

echo ">>> Verifying Installation..."
ansible --version
ansible-lint --version

echo ">>> SUCCESS: Runner is ready!"
