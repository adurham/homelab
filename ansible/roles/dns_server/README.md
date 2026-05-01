# roles/dns_server

Bind9 (named) authoritative DNS for `chi.lab.amd-e.com` and
`lab.amd-e.com`, plus recursive resolver for the trusted ACL (LAN +
private SDN + Tailscale). Runs on dns-01.

## What it does

- apt-installs bind9.
- Renders `named.conf.options` (resolver options + DoT listener) and
  `named.conf.local` (zone declarations).
- Templates the two zone files from `db.chi.lab.amd-e.com.j2` and
  `db.lab.amd-e.com.j2`. A-record IPs are projected from the `ip_*`
  vars in `group_vars/all/vars.yml` — never inline literals.

## Listeners

- :53 udp/tcp — standard DNS, allowed for the trusted ACL only.
- :853 tcp — DoT (DNS-over-TLS), client-facing. Cert from acme.sh.

## Hardening

- `version "none"; hostname "none";` — bind doesn't fingerprint by
  build string on `CHAOS TXT version.bind` queries.
- `allow-query { trusted; };` covers `127.0.0.0/8`, `::1`,
  `{{ net_lan_range }}`, `{{ net_private_range }}`, `100.64.0.0/10`.

## Upstream forwarders

Plaintext DNS to Cloudflare (1.1.1.1, 1.0.0.1). DoT-in-forwarders
syntax was attempted but is bind 9.19+; we're on Ubuntu 22.04's 9.18.

## Where it's invoked

`deploy_dns.yml`. Restart-on-change handler reloads named whenever any
template renders new content.
