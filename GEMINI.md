# Homelab Infrastructure Repository - GEMINI.md

This document provides a comprehensive overview of the "homelab" repository, detailing its architecture, key components, and operational procedures. It is the primary "map" for AI agents to understand the current state of the infrastructure.

## 🚀 Project Overview

This repository manages a **Hyper-Converged Private Cloud** built on **Proxmox VE**. It treats the entire lab as a software-defined datacenter, using Ansible for end-to-end automation of infrastructure, networking, and services.

**Core Architecture:**
1.  **Orchestrator**: Ansible (Roles & Playbooks).
2.  **Hypervisor**: Proxmox VE (3-Node Cluster: `pve01`, `pve02`, `pve03`).
3.  **Networking**:
    *   **Physical**: LAN (`vmbr0` - `192.168.86.0/24`).
    *   **SDN**: VXLAN-based Private Network (`private` - `172.16.0.0/24`) for isolated service communication.
    *   **Ingress**: Tailscale Gateway (`172.16.0.101`) for secure remote access and NAT.
4.  **Identity**: Authentik (`auth.chi.lab.amd-e.com`) with OIDC integration for Proxmox SSO.
5.  **Storage**: ZFS (NVMe) with automated Replication for High Availability.

## 📂 Directory Structure

### `ansible/` (Automated Provisioning)
The heart of the operation. Manages the lifecycle of LXC containers, VMs, and cluster configurations.

*   **Inventory**: `ansible/inventory/proxmox.yml` - Defines nodes and static IPs for core services.
*   **Playbooks**:
    *   `deploy_dns.yml`: Provisions Bind9 DNS (`dns-01`).
    *   `deploy_authentik.yml`: Provisions Authentik IDP (`authentik`).
    *   `deploy_loadbalancer.yml`: Provisions Nginx LB (`lb-01`).
    *   `deploy_tailscale_gw.yml`: Provisions Tailscale Gateway (`tailscale-gw`).
    *   `configure_sso.yml`: Configures Proxmox OIDC Realm & Permissions.
    *   `manage_ha.yml`: Configures ZFS Replication & HA Resources.
    *   `manage_authentik.yml`: Declarative config for Authentik (Providers, Apps, Groups).

### `terraform/` (Legacy/Reference)
Contains configuration for older VMware vSphere infrastructure. *Status: Deprecated/Maintenance.*

## 🏗️ Core Services & Addressing

| Service | Hostname | IP (Private) | Public/LAN | Description |
| :--- | :--- | :--- | :--- | :--- |
| **Gateway** | `proxmox` (VNet) | `172.16.0.1` | - | SDN Gateway for Private Network |
| **DNS** | `dns-01` | `172.16.0.10` | - | Internal Bind9 Authority (`chi.lab.amd-e.com`) |
| **Identity** | `authentik` | `172.16.0.20` | `100.x.y.z` (TS) | SSO Provider. Access via LB. |
| **Load Balancer** | `lb-01` | `172.16.0.30` | - | Nginx Layer 7 Proxy for Cluster & Services |
| **Tailscale GW** | `tailscale-gw` | `172.16.0.101` | `100.x.y.z` | Ingress/NAT Gateway for Mac/PCs |

**External Access URL**: `https://proxmox.chi.lab.amd-e.com` (Points to `lb-01`)

## 🛡️ High Availability (HA)

The core infrastructure is designed to survive a single node failure (`N-1` redundancy).

*   **Mechanism**: Proxmox HA Manager (Watchdog) + ZFS Replication.
*   **Replication Rate**: Every 15 minutes.
*   **Target Nodes**: All peers (`pve02`, `pve03`).
*   **Protected Resources**:
    *   `ct:100` (Authentik)
    *   `ct:101` (Tailscale GW)
    *   `ct:102` (DNS)
    *   `ct:103` (Load Balancer)

## 🔐 Credentials & Secrets

*   **Ansible Vault**: Used for tokens/passwords (if active).
*   **Local Credentials**: `ansible/credentials/` (Git-ignored).
    *   `desec_token_proxmox`: API Token for deSEC DNS (used for Let's Encrypt DNS-01 challenges).
    *   `authentik_api_token`: API Token for Authentik Configuration.

## 📝 Operational Procedures

### Deploying Changes
1.  **Update Code**: Modify Roles or Playbooks.
2.  **Run Playbook**:
    ```bash
    ansible-playbook -i ansible/inventory/proxmox.yml ansible/<playbook_name>.yml
    ```
3.  **Verify**: Check services via `https://proxmox.chi.lab.amd-e.com` or SSH.

### Handling Failover
If a node fails, Proxmox HA will automatically restart protected containers on a healthy node. No manual intervention required for recovery.
*   **To check status**: `ha-manager status` on any node.
