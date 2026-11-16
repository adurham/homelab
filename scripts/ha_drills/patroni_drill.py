"""Patroni unplanned-failover drill: stop patroni on the current leader, time the promotion of the other node, bring the old leader back, and
verify it rejoins as a sync standby WITHOUT manual repair. Polls authentik's readiness (needs the DB) and both Grafana health endpoints throughout."""
import re, ssl, subprocess, threading, time, urllib.request, urllib.error
import os
ANS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "ansible")
ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE   # throwaway health poll of our own endpoint
def ans(host, cmd, t=90):
    r = subprocess.run(["ansible", host, "-i", "inventory/proxmox.yml", "-b", "-m", "shell", "-a", cmd], cwd=ANS, capture_output=True, text=True, timeout=t)
    return (r.stdout + r.stderr).replace("\\n", "\n")
def plist():
    o = ans("pg-01", "patronictl -c /etc/patroni/config.yml list")
    rows = re.findall(r"\|\s*(pg-0\d)\s*\|\s*[\d.]+\s*\|\s*(Leader|Replica|Sync Standby)\s*\|\s*(\w[\w ]*?)\s*\|\s*(\d+)\s*\|", o)
    return {n: (role, st, int(tl)) for n, role, st, tl in rows}
stop = False; log = []
def poll():
    while not stop:
        t0 = time.time()
        try: c = urllib.request.urlopen("https://auth.chi.lab.amd-e.com/-/health/ready/", timeout=3, context=ctx).status
        except urllib.error.HTTPError as e: c = e.code
        except Exception as e: c = type(e).__name__
        log.append((t0, c)); time.sleep(max(0, 0.5 - (time.time() - t0)))
st = plist(); print("before:", st)
leader = [n for n, v in st.items() if v[0] == "Leader"]; assert len(leader) == 1 and len(st) == 2, st
old = leader[0]; new = "pg-01" if old == "pg-02" else "pg-02"
th = threading.Thread(target=poll, daemon=True); th.start(); t_all = time.time()
try:
    time.sleep(2)
    t0 = time.time(); ans(old, "systemctl stop patroni"); print(f"stopped patroni on {old} (command took {time.time()-t0:.1f}s)")
    prom = None
    for _ in range(80):
        time.sleep(2)
        s = plist()
        if s.get(new, ("",))[0] == "Leader": prom = time.time() - t0; break
    print(f"{new} became Leader after {prom:.0f}s" if prom else "NO PROMOTION within 160 s")
    time.sleep(15)
    t1 = time.time(); ans(old, "systemctl start patroni"); print(f"started patroni on {old}")
    back = None
    for _ in range(90):
        time.sleep(3)
        s = plist()
        if s.get(old, ("", ""))[0] in ("Sync Standby", "Replica") and s[old][1] == "running": back = time.time() - t1; break
    print(f"{old} back as {plist().get(old)} after {back:.0f}s" if back else f"{old} DID NOT REJOIN within 270 s: {plist()}")
    time.sleep(5)
finally:
    stop = True; th.join(timeout=5)
bad = [(round(t - t_all, 1), c) for t, c in log if c != 200]
print(f"authentik readiness polls: {len(log)} total, {len(bad)} not-200; first/last failure t={bad[0][0] if bad else '-'}s/{bad[-1][0] if bad else '-'}s")
print("after:", plist())
j = ans(old, "journalctl -u patroni --no-pager --since '-6min' | grep -iE 'rewind|reinit|re-?clon|diverged|basebackup|removing data' | tail -4 | cut -c1-160")
print("repair actions Patroni took on the old leader:", [l for l in j.splitlines() if re.search(r"rewind|reinit|clon|diverged|basebackup|removing", l, re.I)][:4] or "none logged")
for g in ("graf-01", "graf-02"):
    o = ans(g, "curl -s -m 5 http://127.0.0.1:3000/api/health | tr -d '\\n '")
    print(g, "database:", re.search(r'"database":"(\w+)"', o).group(1) if re.search(r'"database":"(\w+)"', o) else o[-60:])
