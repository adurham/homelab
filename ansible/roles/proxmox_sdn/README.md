# Proxmox SDN Role

## Overview

Configures Software Defined Networking (VXLAN) on the Proxmox cluster to create the `private` (172.16.0.0/24) network.

## Key variables (`defaults/main.yml`)

- `proxmox_cluster_peers` — comma-separated list of cluster node IPs,
  passed to the VXLAN zone as `--peers`. Set in
  `group_vars/all/vars.yml` (`192.168.86.11,192.168.86.12,192.168.86.13`).
- `net_bwt_bridge` / `net_bwt_vlan_tag` / `net_bwt_range` / `net_bwt_gw`
  — define the second VNet (`bwt`, tag 200, 10.99.0.0/24, gw 10.99.0.1),
  the isolated Bandwidth-Throttle repro lab. Also in
  `group_vars/all/vars.yml`.

## What it creates

- Zone `homelab` (type `vxlan`, IPAM `pve`, MTU 1450).
- VNet `private` (zone `homelab`, tag 100, alias "Private Network") —
  the default service subnet 172.16.0.0/24.
- VNet `bwt` (zone `homelab`, tag 200, alias "BWT Repro Lab") + a
  subnet (`10.99.0.0/24`, gateway `10.99.0.1`, SNAT enabled).

## Usage

Run once on any node in the cluster (most tasks use `run_once: true`).
Invoked by `setup_sdn.yml`.
