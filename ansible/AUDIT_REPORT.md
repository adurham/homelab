# Ansible Infrastructure Audit Report

## 1. Executive Summary

The current Ansible infrastructure for the Proxmox Private Cloud is robust, featuring functional High Availability (HA) awareness, correct secret management, and performance tuning (pipelining). However, as the infrastructure scales, technical debt is accumulating in monolithic playbooks (specifically `manage_authentik.yml`) and security shortcuts taken during initial provisioning (SSH strict host key checking disabled) present a risk profile that should be matured.

## 2. Security Findings

### 2.1 SSH Trust Model (Critical)

* **Observation**: `StrictHostKeyChecking=no` is used in `inventory/proxmox.yml` for Tanium Clients (`tanium_clients`) and implicitly relied upon for dynamic hosts using `UserKnownHostsFile=/dev/null`.
* **Risk**: This exposes the infrastructure to Man-in-the-Middle (MITM) attacks. If an attacker spoofs an IP (e.g., `172.16.0.65`), Ansible will blindly send root credentials or secrets to it.
* **Remediation**:
    1. Ensure all provisioning templates execute `ssh-keygen -A` at boot.
    2. Use `StrictHostKeyChecking=accept-new` for a balance between usability and security (trusts on first use, alerts on change).
    3. Centralize this configuration in `group_vars/all.yml`.

### 2.2 SSL Verification (Medium)

* **Observation**: `manage_authentik.yml` explicitly disables SSL verification (`verify_certificates: false`) for internal SCIM integration.
* **Risk**: While low risk on a private VXLAN (`172.16.0.0/24`), this habit complicates moving to Zero Trust architectures.
* **Remediation**: Ensure the internal CA root is trusted by the runner (Mac Studio) and enable verification.

### 2.3 Secret Management (Pass)

* **Observation**: Secrets are correctly externalized to `ansible/credentials/` and ignored via `.gitignore`.
* **Recommendation**: Continue migration to Ansible Vault for stronger at-rest encryption of these files.

## 3. Optimization & Architecture

### 3.1 Monolithic Playbooks (High Impact)

* **Observation**: `manage_authentik.yml` exceeds 1,600 lines. It handles OAuth2 Providers, SAML Providers, SCIM mappings, User Groups, and Recovery flows in a single linear file.
* **Optimization**:
  * **Refactor to Roles**: Break this into `roles/authentik_provider`, `roles/authentik_user_group`, and `roles/authentik_flow`.
  * **Benefit**: drastically improves readability, allows for independent testing of components, and enables better `tags` usage.

### 3.2 Code Quality & Linting

* **Observation**: No `.ansible-lint` configuration exists.
* **Optimization**: Implement a configuration to enforce:
  * Fully Qualified Collection Names (FQCN) (e.g., `ansible.builtin.uri` instead of `uri`).
  * Idempotency checks.
  * File mode, owner, and group specifications.

## 4. Roadmap

### Phase 1: Hardening (Immediate)

- [ ] Implement `.ansible-lint` configuration.
* [ ] Centralize SSH configuration in `group_vars`.

### Phase 2: Refactoring (Next Sprint)

- [ ] Decompose `manage_authentik.yml` into roles.
* [ ] Implement `netaddr` filters for cleaner IP math in `proxmox_network`.

### Phase 3: CI/CD (Future)

- [ ] Implement GitHub Actions workflow using `setup_runner.sh` to run linting on PRs.
