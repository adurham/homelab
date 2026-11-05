# printfarm

Bambu/MakerWorld **3MF → Creality K2** print service, running in CT 119
(`print-01`) and exposed **on the tailnet only**.

```
https://printbot.chi.lab.amd-e.com   <- pretty name: internal DNS -> lb-01 vhost
https://print.tail19c543.ts.net      <- tailnet node name is "print"
```

Two front doors, both TLS:

* **printbot.chi.lab.amd-e.com** — an lb-01 vhost using the existing
  `*.chi.lab.amd-e.com` wildcard cert, internal-only ACL (LAN / private SDN /
  Tailscale, `$is_internal`), no forward-auth. nginx proxies to the CT's
  tailnet address because lb-01 cannot reach its private-SDN one. Resolves for
  anything using the lab resolver (dns-01) — including the CT itself. NOTE:
  `*.chi.lab.amd-e.com` does **not** resolve through Tailscale's split DNS
  today (MagicDNS answers NXDOMAIN while dns-01 answers correctly), so a
  tailnet-only client off-LAN needs that tailnet DNS setting fixed before this
  name is useful to it.
* **print.tail19c543.ts.net** — `tailscale serve`, tailnet-issued cert, works
  from any tailnet device anywhere, no DNS dependency beyond MagicDNS.

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
ssh root@100.120.18.93 systemctl status bambu2creality
ssh root@100.120.18.93 journalctl -u bambu2creality -n 50
ssh root@100.120.18.93 tailscale serve status
```

Ansible reaches the CT over its **tailnet** address: after the join, the
subnet-routed private leg stops answering this Mac (measured — no ping, no port
22 at 172.16.0.51) while the tailnet address answers both over a direct peer
link. The host role detects this and sets `ansible_host` accordingly, falling
back to `ip_printfarm` for a from-scratch build.

The app source lives in `~/repos/bambu2creality` on the controller
(`printfarm_src`), the same single-source pattern as `ps5forge_src`; redeploy
to publish changes.

## Multi-plate and multi-filament source files

A Bambu project can hold several plates and up to four filaments. The converter
handles both, with one deliberate simplification:

* every object's filament is clamped to the K2's single loaded filament (CFS
  slot 1) — a source file that colours parts differently still prints in one
  colour, and the source's colour list is collapsed to the chosen colour. Without
  that clamp Creality Print rejects the whole project with `Filament nozzle
  mapping is incomplete.` (rc=-51), per plate, which is the confusing part.
* `--slice 0` slices every plate, so a 3-plate file returns `plate_1..3.gcode`;
  the UI lists each plate with its own time/filament and its own print button.
  The top-level numbers are the sum across plates.

Support on/off is **not** part of the `safe` profile — it is carried from the
source project (`enable_support` + the `support_*` family + `raft_layers`), so a
Bambu file that supports an internal ledge still gets that support on the K2.
The profile only owns adhesion and speed. (Before 2026-11-05 the profile pinned
`enable_support = 0`, and the service's slice of the tissue-box middle section
had zero support where Creality Print's own GUI slice had 126 layers.)
Support material changes the job's numbers, so the summary and the per-plate
rows are re-read from whatever the slicer actually produced.

## What "safe" means (the app's reason to exist)

Filament and bed are constants here; the model and the slicer settings are the
variables. So the service must never depend on a GUI profile being sane — the
`safe` profile owns the settings that decide whether a print survives:

- **Flow ceiling**: `filament_max_volumetric_speed = 12` mm³/s. A 150–200 mm/s
  wall at 0.2 × 0.4 mm demands ~16 mm³/s; the GUI "Custom" slice of 纸巾盒 came
  out beaded and stringy from the first layer and the K2's own AI monitor
  cancelled it at 49.6%. With the cap the slicer slows down instead.
- **Speeds**: outer 90 / inner 120 / top 90 / gap fill 45 mm/s, travel 400.
- **Thermal + adhesion**: 215 °C, bed 55 (60 first layer), fan 80% after 3
  layers, 0.25 mm first layer, 8 mm outer brim, z-hop 0.8 spiral, retract 0.8@30.
- **Shells**: 3 walls, 5 top / 4 bottom, gyroid infill at the file's density.
- **Support style is ours**, not the model's: normal(auto)/grid, 0.8 mm XY gap,
  3-layer interface, 0.2 mm top gap. `enable_support` still comes from the model,
  because whether a part needs support is geometry, not profile.

Measured on the 3-plate 纸巾盒 file after the change: plate 2 = 302 layers /
46.05 mm / 53.96 g / 136 min, 87 support sections — versus 230 layers / 66 min
for the GUI slice that failed.

The UI's other profile, `stock`, is the model's own settings and is labelled
comparison-only for exactly this reason.

## Risk estimate: what this printer's history actually supports

Every convert now reports `report.risk` — the chance the job finishes, from the
machine's own record rather than a hunch:

- `build_dataset.py` (in the bambu2creality repo) joins Moonraker's job history to
  each gcode still on the printer (8 KB head + 128 KB tail, Range requests) →
  `dataset.json`.
- `risk_fit.py` classifies a stop as a **user abort** (<35% progress) or a
  **mid-print failure** (≥35%), then fits a Beta-smoothed frequency — not a
  classifier. Rebuild with those two scripts after a batch of prints; the model
  file is `risk_model.json` and the app needs no ML dependency to score.

Numbers as of the first build (105 prints with recoverable configs): 89 finished,
10 aborted by the owner, **6 mid-print failures** → 6.3% failure (95% CI
2.9–13.1%), i.e. **93.7% finish (86.9–97.1%)**. All six failures ran wall flow
≥ 16.8 mm³/s, but so did 80 prints that finished — so flow is a risk factor, not a
verdict, and a logistic model on 14 slice settings only reached CV AUC ~0.60.
That is why the app quotes the base rate, the same model's own record (Beta-shrunk,
prior strength 6) and physical ceilings as flags instead of pretending to model
the rest.
