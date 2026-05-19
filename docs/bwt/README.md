# BWT Lab — bandwidth-throttle reproduction environment

A self-contained 5-server + 8-client Tanium lab for reproducing platform
bandwidth-throttle behavior. Used to investigate NEC case 00271560 (sites
127/128 showing post-CDN-disable peer-protocol exceedance) and any future
throttle-enforcement cases.

## What this is for

The repro lab exists to answer a class of question:

> Customer reports site X bandwidth throttle isn't being enforced.
> Console shows the curve crossing the red limit line. Is it a real
> enforcement bug or a counter accounting artifact?

Adam's prior is: peer-protocol throttle has been stable for years; almost
every "throttle broken" report is CDN counter inflation or
config-mismatch. The lab is what distinguishes those hypotheses from a
real enforcement bug, by giving us three independent measurement
channels: the TS-embedded VictoriaMetrics counter, the wire-level
iptables byte counter on each ZS, and per-client received-bytes from
the perf-test harness.

See `tanium-bandwidth-throttle` skill for the full investigation
workflow this lab supports.

## Architecture

```
                   Mac (ansible controller)
                       │
                       │ ProxyJump=root@192.168.86.11
                       ▼
                  pve01 (192.168.86.11)
                       │
                       │ holds 10.99.0.1 + SNAT to vmbr0
                       ▼
            ┌──────────────────────────────┐
            │  bwt SDN VNet (VXLAN tag 200)│
            │  10.99.0.0/24                │
            └──────────────────────────────┘
                       │
       ┌───────────────┼───────────────┐
       │               │               │
   bwt-dhcp        bwt-ts          bwt-zs-01..04
   (CT 114)       (VM 220)         (VMs 221-224)
   10.99.0.2      10.99.0.10       10.99.0.11-14
   dnsmasq        TS 7.8.5.1308    TZS 7.8.5.1308
                                      │
                                      │
                       bwt-tc-01..08 (CTs 320-327)
                       10.99.0.50-250 (DHCP)
                       Tanium client 7.8.5.1308
```

Network isolation: BWT subnet is intentionally walled off from the
homelab `private` subnet (172.16.0.0/24). BWT VMs use public DNS
(1.1.1.1, 8.8.8.8) pushed by `bwt-dhcp`. Outbound goes via SNAT through
pve01's vmbr0. Ansible reaches BWT VMs via ProxyJump through pve01.

## Documents in this directory

- [build-network.md](build-network.md) — phase 1: SDN VNet, gateway, DHCP CT
- [build-tanos.md](build-tanos.md) — phase 2: TanOS template baking + per-clone reconfig (QMP keystroke automation)
- [build-tanium.md](build-tanium.md) — phase 3: TS/TZS install, throttle config via API, client install
- [skill-candidates.md](skill-candidates.md) — patterns from this build that should be extracted as reusable skills

## End-to-end automation (current state)

After a one-time TanOS template bake (~10 min, fully automated via QMP
keystrokes), the full lab rebuilds with:

```
cd ~/repos/homelab/ansible
ansible-playbook setup_sdn.yml           # bwt VNet
ansible-playbook setup_bwt_gateway.yml   # pve01 holds 10.99.0.1 + SNAT
ansible-playbook deploy_bwt_dhcp.yml     # dnsmasq CT
ansible-playbook deploy_bwt_servers.yml  # 5 TanOS VMs (clone + IP/FQDN)
# Manual: SFTP RPMs to tancopy@<host>:/incoming + ssh tanadmin@<host> "install ts/tzs"
ansible-playbook configure_bwt_throttle.yml  # site + globals via /api/v2
ansible-playbook deploy_bwt_clients.yml      # 8 LXC clients with Tanium
```

The TS/TZS install isn't yet in a play — it's captured in
[build-tanium.md](build-tanium.md). The throttle config and client
provisioning are.
