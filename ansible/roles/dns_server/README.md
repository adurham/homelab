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

bind forwards to AdGuard Home on the homeassistant host
(`{{ ip_homeassistant }}`), which handles the encrypted DoT upstreams
(tls://1.1.1.1, tls://1.0.0.1, tls://9.9.9.9, `parallel` mode) and
applies the ad-block lists. `forward only;` ensures we never bypass
AdGuard and recurse to public roots ourselves on an AdGuard outage —
DNS fails closed instead of silently degrading to plaintext.

**DNSSEC: validated at AdGuard, deliberately NOT re-validated here
(`dnssec-validation no;`).** AdGuard enforces DNSSEC itself
(`dnssec_enabled=true`; verified it SERVFAILs dnssec-failed.org), but it
also deliberately synthesizes UNSIGNED responses for (a) every AAAA
query while `disable_ipv6=true` (synthetic NODATA with an unsigned
`fake-for-negative-caching.adguard.com` SOA) and (b) blocked domains.
A validating resolver rejects both, which caused real, measured damage
on 2026-10-03: 9/30 popular domains SERVFAILed on AAAA via this
resolver while AdGuard answered them NOERROR, and the SERVFAIL churn
knocked the healthchecks.io dead-man's-switch pings out for ~15 min.
`dig +cd` returned NOERROR against the same resolver, isolating the
validator as the rejector. A strict validating resolver cannot sit
behind an actively-filtering/synthesizing upstream — don't re-enable.

Tried stubby briefly as a self-contained DoT proxy on dns-01 itself
before discovering AdGuard already provided this — purging stubby
was simpler than running a duplicate.

## Where it's invoked

`deploy_dns.yml`. Restart-on-change handler reloads named whenever any
template renders new content.
