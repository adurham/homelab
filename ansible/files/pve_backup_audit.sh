#!/bin/sh
echo "--- users + tfa ---"
pveum user list --output-format json 2>/dev/null | python3 -c '
import json,sys
for u in json.load(sys.stdin):
    print(u["userid"], "enabled=", u.get("enable"), "tfa=", (u.get("tfa") or []), "expire=", u.get("expire"))
'
echo "--- root@pam tfa detail ---"
pveum user tfa list root@pam 2>/dev/null | head -5
echo "--- backup storage + newest dumps ---"
pvesh get /cluster/backup --output-format json 2>/dev/null | python3 -c '
import json,sys
for j in json.load(sys.stdin):
    print("job", j.get("id"), "node", j.get("node"), "storage", j.get("storage"), "sched", j.get("schedule"), "enabled", j.get("enabled"), "vmid", j.get("vmid"))
'
for st in $(pvesm status -content backup 2>/dev/null | awk 'NR>1{print $1}'); do
  path=$(pvesm path "$st:backup" 2>/dev/null | sed 's|/[^/]*$||')
  [ -d "$path" ] || continue
  echo "storage $st -> $path"
  ls -lt "$path"/dump 2>/dev/null | head -4
  find "$path"/dump -name 'vzdump*' -newermt '-48 hours' 2>/dev/null | wc -l | sed 's/^/dumps_48h=/'
done
