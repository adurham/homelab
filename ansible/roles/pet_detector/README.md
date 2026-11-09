# pet_detector

Deploys the app from `../pet-accident-detector/` to the `pet-detector-01` CT
(VMID 171, pve03, 192.168.86.18). The CT is a 1-core / 512 MB Debian 12
container on `local-lvm:4`; the app runs as a system-level systemd unit and
writes its state under `/root/.local/share/pet-accident-detector/`.

## One-time CT creation

Run on pve03 (already done 2026-11-09):

```bash
pveam download local debian-12-standard_12.12-1_amd64.tar.zst
pct create 171 local:vztmpl/debian-12-standard_12.12-1_amd64.tar.zst \
  --hostname pet-detector-01 --cores 1 --memory 512 --swap 256 \
  --net0 name=eth0,bridge=vmbr0,ip=192.168.86.18/24,gw=192.168.86.1 \
  --nameserver 192.168.86.1 --searchdomain chi.lab.amd-e.com \
  --rootfs local-lvm:4 --unprivileged 1 --features nesting=1 \
  --ssh-public-keys /tmp/pet.keys          # the id_ansible public key
pct start 171
```

`.18` is outside the router's DHCP pool and was IPAM-verified free. The
container was added to the cluster-wide `pve_backup_vmids` union in
`inventory/proxmox.yml`, so the nightly vzdump covers it.

## Secrets (hand-provisioned, not in ansible vars)

The app reads `~/.config/pet-accident-detector/env`, which for root is
`/root/.config/pet-accident-detector/env`. It must be mode 600 and contain:

```
HASS_URL=http://192.168.86.2:8123
HASS_TOKEN=<long-lived token>
OLLAMA_API_KEY=<ollama.com key>
FRIGATE_MQTT_PASSWORD=<frigate broker password>
```

Provision it from the workstation (values already live in `~/.hermes/.env`
and `~/.config/pet-accident-detector/env` there), then the HA image-upload
key:

```bash
scp -i ~/.ssh/id_ansible <composed-env> root@192.168.86.18:/root/.config/pet-accident-detector/env
scp -i ~/.ssh/id_ansible ~/.config/pet-accident-detector/id_petaccident \
  root@192.168.86.18:/root/.config/pet-accident-detector/id_petaccident
ssh -i ~/.ssh/id_ansible root@192.168.86.18 \
  'chmod 600 /root/.config/pet-accident-detector/*'
```

These two secrets are not in the ansible vault: the HA token is a
workstation-held long-lived token and the Ollama key belongs to the Hermes
cloud account. Moving them to the vault is a follow-up; the role asserts the
env file exists so a from-scratch rebuild fails with instructions instead of
starting a detector that cannot notify.

## Deploy

```bash
cd ansible
ansible-playbook deploy_pet_detector.yml
```

## Verify

```bash
ssh -i ~/.ssh/id_ansible root@192.168.86.18 \
  'systemctl status pet-accident-detector --no-pager'
ssh -i ~/.ssh/id_ansible root@192.168.86.18 \
  'cd /opt/pet-accident-detector && .venv/bin/python detector.py --check foyer'
```

The service logs to the journal, not a file:
`journalctl -u pet-accident-detector -f` in the CT.
