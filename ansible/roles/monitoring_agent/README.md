# Monitoring Agent Role

## Overview

Installs `prometheus-node-exporter` to provide hardware and OS metrics (CPU, RAM, Disk, Network).

## Variables

None

## Usage

Include in any playbook targeting Linux hosts:

```yaml
- hosts: all
  roles:
    - monitoring_agent
```
