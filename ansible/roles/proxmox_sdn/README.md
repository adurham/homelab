# Proxmox SDN Role

## Overview

Configures Software Defined Networking (VXLAN) on the Proxmox cluster to create the `private` (172.16.0.0/24) network.

## Variables

- `proxmox_cluster_peers`: Comma-separated list of cluster node IPs.

## Usage

Run once on any node in the cluster (uses `run_once: true`).
