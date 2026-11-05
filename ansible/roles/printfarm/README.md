# printfarm

Bambu/MakerWorld **3MF → Creality K2** print service, running in CT 119
(`print-01`) and exposed **on the tailnet only**.

```
http://print-01.tail19c543.ts.net:8765
```

## What problem it solves

A model downloaded from MakerWorld / exported from Bambu Studio carries the
*author's* printer profile: `Bambu Lab P1S`, `Bambu PLA Basic`, a 256 mm bed,
Marlin start gcode. Creality Print then either refuses the file (it is from a
"newer version") or slices it with settings the K2 cannot honour. Doing the
conversion by hand — reassign machine/filament/process, fix bed type, add the
brim Creality's `auto_brim` skips, slow the walls down for thin geometry,
re-space the copies — is the whole job this service does in one drop.

## How it works

Creality Print itself is the slicing engine, driven headlessly through its own
CLI (`CrealityPrint --cli --slice`), i.e. exactly what the desktop GUI does.
The AppImage is **extracted** (not FUSE-mounted) into
`/opt/creality-print/squashfs-root`, and it ships the complete Creality preset
tree at `resources/profiles/Creality/` — including `Creality K2 0.4 nozzle`,
`0.20mm Standard @Creality K2 0.4 nozzle` and `Hyper PLA @Creality K2 0.4
nozzle` — so no first-run GUI unpack is needed.

1. slice a 10 mm cube with the stock K2 presets, keep the resulting
   `CONFIG_BLOCK` → a fully resolved 639-key K2 config (cached per Creality
   version);
2. graft it into the incoming 3MF (geometry/plates untouched; Bambu-only keys
   that fail Creality's range validation dropped);
3. re-slice headlessly (`--allow-newer-file` handles the Bambu version gate);
4. hand the gcode to the printer over Moonraker (`192.168.86.43:7125`, no auth
   on the LAN) when the user taps *Print on the K2*.

The `safe` profile exists because the stock K2 "Standard" preset runs two
perimeters at 200–300 mm/s, which shakes a long thin walled part loose — a
230 mm U-channel with 2.5 mm walls failed twice on this printer before the
perimeter count, brim, wall speed and bed temperature were changed.

## Why Ubuntu 24.04 and that long dependency list

The 7.3 AppImage links noble-era sonames (`libtiff.so.6`, `libx264-164`,
`libasound2t64`, `libdeflate0`); on 22.04 the CLI aborts before it starts.
`printfarm_deps` is the exact set that satisfies `ldd bin/CrealityPrint` —
the binary links WebKit2GTK/GTK3/GStreamer directly, so `libwebkit2gtk-4.1-0`
and friends are mandatory, not optional. The role's smoke test runs
`--cli --help` so a missing lib fails the deploy, not the user's first slice.

## Networking

- `eth0` — private SDN `172.16.0.51/24`, **no gateway** (a static default on
  eth0 outscores eth1's DHCP default and breaks Tailscale's portmapper).
- `eth1` — `vmbr0` DHCP: default route, LAN reachability to the printer, and
  Tailscale hole-punching (same reasoning as `adblock_proxy_host`).
- The web UI binds **`tailscale0`**, not `0.0.0.0`: the CT has a LAN NIC, and
  the UI must not be reachable from the LAN.
- `--accept-routes=false` is required: `tailscale-gw` advertises
  `172.16.0.0/24` and this CT *lives* on it.

Ansible reaches the CT over the LAN leg on first deploy (the private path
goes asymmetric once a CT peers directly — see the comment in
`printfarm_host`), then re-points at MagicDNS.

## Tailnet authorization

`tailscale up` needs the node approved once in the tailnet. The role fails
with the exact command to run if it is not authed. The vaulted
`vault_tailscale_api_token` currently returns `401 API token invalid`, so the
join cannot be minted automatically — if that token is refreshed, an auth key
could be created here instead and the manual step removed.

## Operating it

```bash
ansible-playbook deploy_printfarm.yml            # idempotent
ansible-playbook deploy_printfarm.yml --tags=... # n/a: single role, no tags
ssh root@<print-01> systemctl status bambu2creality
ssh root@<print-01> journalctl -u bambu2creality -n 50
```

The app source lives in `~/repos/bambu2creality` on the controller
(`printfarm_src`), the same single-source pattern as `ps5forge_src`; redeploy
to publish changes.
