# Authentik Service Role

## Overview

Deploys Authentik Identity Provider using Docker Compose.

## Variables

- `lxc_password`: Root password for the container (vaulted).
- `ip_authentik`: Static IP address.

## Usage

Dependencies: `authentik_host` (Container must exist).
