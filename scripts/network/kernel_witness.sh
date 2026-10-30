#!/bin/bash
# kernel_witness.sh -- keep the kernel's own words for the last minutes before a
# self-fence reset, on a node whose journal is volatile and whose ring buffer is
# churned by apparmor noise (pve01: ~900 audit lines per 21 minutes, so the ring
# holds only ~20 min and a driver message can be evicted within seconds of a
# stall).
#
# Every kernel line matching NIC / hang / lockup / MCE / thermal / OOM patterns is
# appended to $LOG with an fsync per line, so it is on disk before the reset that
# follows a stall by ~110 s. This is what makes "the box was alive but mute" vs
# "the kernel wedged" decidable after the fact.
#
# Unit: kernel-witness.service (Restart=always).
set -u
LOG=/root/kernel_witness.log
MAXB=1048576
PAT='e1000e|nic0|Link is|hang|reset|watchdog|softlockup|soft lockup|rcu|RCU|Call Trace|BUG:|Oops|MCE|machine check|thermal|throttl|oom|Out of memory|blocked for more than'

rotate() {
  if [ -f "$LOG" ] && [ "$(stat -c%s "$LOG" 2>/dev/null || echo 0)" -gt "$MAXB" ]; then
    mv -f "$LOG" "$LOG.1"
  fi
}
rotate
echo "kernel_witness started $(date -Is) on $(hostname) uptime=$(cut -d' ' -f1 /proc/uptime)" >> "$LOG"
sync -f "$LOG" 2>/dev/null || sync

# dmesg -w replays the existing buffer first, then follows.
dmesg -w -T 2>/dev/null | grep --line-buffered -iE "$PAT" | while IFS= read -r line; do
  printf '%s\n' "$line" >> "$LOG"
  sync -f "$LOG" 2>/dev/null || sync
  rotate
done
