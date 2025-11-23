# Homelab Infrastructure Repository - GEMINI.md

This document provides an overview of the "homelab" repository, detailing its purpose, structure, and key operational procedures, intended for AI agents to quickly understand and interact with the codebase.

## 🚀 Project Overview

This repository hosts a comprehensive homelab setup, integrating infrastructure automation, smart home automation, system management, and various development tools. It is designed to manage a personal IT environment efficiently and reliably, leveraging Infrastructure as Code (Terraform), Configuration Management (Ansible), and Smart Home Automation (Home Assistant).

**Key Components:**
-   **Infrastructure as Code (`terraform/`):** Manages VMware vSphere infrastructure, including Active Directory, Tanium, Consul, Vault, Keycloak, NSX, and vCenter.
-   **Configuration Management (`ansible/`):** Automates system configurations, particularly for Tanium client deployments across various operating systems and VMware Tools management.
-   **Smart Home Automation (`homeassistant/`):** Controls intelligent home features, such as a water heater circulator pump system based on occupancy and various lighting automations.
-   **Utility Scripts (`misc scripts/`):** Contains a collection of scripts for system bootstrapping, AI development assistance (using `continue.dev`), system management, and Tanium platform management.

## 🛠️ Building and Running

This project involves various components, each with its own setup and execution procedures.

### System Bootstrap

To set up a fresh terminal/shell environment, use the comprehensive bootstrap script:

```bash
./misc\ scripts/bootstrap.sh
```

This script handles OS detection, package manager installation (Homebrew on macOS, apt/dnf/pacman on Linux), essential tools (zsh, git, curl, etc.), Oh My Zsh, Starship prompt, and custom `.zshrc` and `.zprofile` configurations.

### Infrastructure Deployment (Terraform)

The `terraform/` directory contains configurations for deploying and managing the homelab infrastructure on VMware vSphere.

**Key Files:**
-   `terraform/providers.tf`: Defines the required Terraform providers (e.g., `vmware/vsphere`, `vmware/nsxt`, `hashicorp/null`) and their base configurations.
-   `terraform/variables.tf`: Declares input variables for the Terraform configurations, including sensitive information like passwords and various service endpoints.
-   Other `.tf` files (e.g., `active-directory.tf`, `tanium.tf`, `vcenter.tf`): Define the specific infrastructure resources.

**Deployment Steps:**

1.  Navigate to the `terraform` directory:
    ```bash
    cd terraform
    ```
2.  Initialize Terraform:
    ```bash
    terraform init
    ```
3.  Review the planned changes:
    ```bash
    terraform plan
    ```
4.  Apply the changes to deploy the infrastructure:
    ```bash
    terraform apply
    ```
    (Note: Ensure `terraform.tfvars` is configured with your environment details.)

### Configuration Management (Ansible)

The `ansible/` directory holds playbooks and roles for configuring systems, primarily for Tanium client deployments and VMware Tools.

**Key Files:**
-   `ansible/ansible.cfg`: Main Ansible configuration file, defining the inventory source (`./inventory/vsphere_inventory.vmware.yml`) and execution strategy.
-   `ansible/inventory/vsphere_inventory.vmware.yml`: The vSphere dynamic inventory script/configuration.
-   `ansible/roles/`: Contains various Ansible roles (e.g., `tanium_client_314`, `homeassistant_deploy`) for specific configuration tasks.

**General Execution:**
To run an Ansible playbook, navigate to the `ansible` directory and execute the desired playbook:

```bash
cd ansible
ansible-playbook <playbook_name>.yml
```

### Smart Home Automation (Home Assistant)

The `homeassistant/` directory contains configurations and scripts for the Home Assistant instance.

**Virtual Environment Setup:**
Before deploying or working with Home Assistant configurations, set up its Python virtual environment:

```bash
cd homeassistant
./setup_venv.sh
```
This script creates a `venv` directory, activates it, upgrades `pip`, and installs dependencies from `requirements.txt`.

**Deployment:**
The `README.md` indicates a deployment script:
```bash
./homeassistant/deploy_homeassistant.sh # (Further investigation needed for exact script location and content)
```
*Self-correction: The `README.md` mentions `deploy_homeassistant.sh` in the "Maintenance" section but doesn't show its path. It is likely within the `homeassistant` directory or a script that is executed from there. For now, we assume it's in `homeassistant/`.*

### Utility Scripts

The `misc scripts/` directory contains various standalone scripts. Refer to the `README.md` in the root and in `misc scripts/continue-dev/README.md` and `misc scripts/tanium/` for specific usage instructions for these scripts.

## 📝 Development Conventions

Based on the examined files, the following conventions are observed:

-   **Shell Scripting Best Practices:** Bash scripts (e.g., `bootstrap.sh`, `setup_venv.sh`) often use `set -euo pipefail` for robust error handling.
-   **Python Virtual Environments:** Python projects (like Home Assistant) utilize virtual environments (`venv`) for dependency isolation.
-   **Configuration as Code:** Heavy reliance on declarative configuration files for infrastructure (Terraform `.tf` files), configuration management (Ansible YAML), and home automation (Home Assistant YAML).
-   **Cross-Platform Compatibility:** The bootstrap script explicitly supports macOS and various Linux distributions.
-   **Secrets Management:** Terraform variables indicate the use of sensitive variables, implying a secure method for handling credentials (e.g., environment variables, `terraform.tfvars`, or a secrets manager like Vault).
-   **Documentation:** `README.md` files are used extensively to document different sections of the homelab.
