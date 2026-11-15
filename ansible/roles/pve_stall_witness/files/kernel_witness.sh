#!/bin/bash
# kernel_witness.sh -- keep the kernel's own words on disk, fsynced line by line,
# on a node whose journal is volatile (Storage=volatile, set to spare the boot HDD)
# and whose network can die for ~60 s before the HA watchdog resets it.
#
# Why EVERY line and not a grep (changed 2026-11-15): the e1000e "Detected Hardware
# Unit Hang" report is ONE printk with embedded newlines -- TDH/TDT, next_to_use,
# next_to_clean, time_stamp, MAC/PHY status are the lines AFTER the first one. The
# old pattern filter kept only the first line and threw the register state away on
# the two real hangs (2026-11-09, 2026-11-15). Only audit/apparmor noise is
# dropped now (pve01 emits ~900 such lines per 21 minutes and they would rotate the
# interesting part out within hours).
#
# On the first "Detected Hardware Unit Hang" of an episode this also starts
# nic_hang_capture.sh, which snapshots the registers, ring state, interrupts and a
# few frames every couple of seconds until the reset.
#
# Unit: kernel-witness.service (Restart=always).
set -u
LOG=/root/kernel_witness.log
MAXB=4194304
NOISE='audit: type=|apparmor="'
CAPTURE=/usr/local/sbin/nic_hang_capture.sh
COOLDOWN="${COOLDOWN:-600}"
STAMP=/run/nic-hang-capture.stamp

rotate() {
  if [ -f "$LOG" ] && [ "$(stat -c%s "$LOG" 2>/dev/null || echo 0)" -gt "$MAXB" ]; then
    mv -f "$LOG" "$LOG.1"
  fi
}

start_capture() {
  local now last
  now=$(date +%s)
  last=$(cat "$STAMP" 2>/dev/null || echo 0)
  if [ $((now - last)) -ge "$COOLDOWN" ] && [ -x "$CAPTURE" ]; then
    echo "$now" > "$STAMP"
    setsid nohup "$CAPTURE" >/dev/null 2>&1 &
  fi
}

rotate
echo "kernel_witness started $(date -Is) on $(hostname) uptime=$(cut -d' ' -f1 /proc/uptime)" >> "$LOG"
sync -f "$LOG" 2>/dev/null || sync

# dmesg -w replays the existing buffer first, then follows.
dmesg -w -T 2>/dev/null | grep --line-buffered -vE "$NOISE" | while IFS= read -r line; do
  printf '%s\n' "$line" >> "$LOG"
  sync -f "$LOG" 2>/dev/null || sync
  rotate
  case "$line" in
    *"Detected Hardware Unit Hang"*) start_capture ;;
  esac
done
