"""LB failover drill: poll the public auth endpoint every 0.25 s; stop keepalived on lb-01 (VIP -> lb-02), hold, start it again (VIP back).
Prints timings and any failed requests. Always restarts keepalived on lb-01 at the end (finally block)."""
import ssl, subprocess, threading, time, urllib.request, urllib.error
import os
ANS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "ansible")
URL = "https://auth.chi.lab.amd-e.com/-/health/ready/"
ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
log = []; stop = False
def poll():
    while not stop:
        t0 = time.time()
        try: code = urllib.request.urlopen(URL, timeout=2, context=ctx).status
        except urllib.error.HTTPError as e: code = e.code
        except Exception as e: code = type(e).__name__
        log.append((t0, code)); time.sleep(max(0, 0.25 - (time.time() - t0)))
def ans(host, cmd): return subprocess.run(["ansible", host, "-i", "inventory/proxmox.yml", "-b", "-m", "shell", "-a", cmd], cwd=ANS, capture_output=True, text=True, timeout=90).stdout.replace("\\n", "\n")
def holder():
    out = {h: ans(h, "ip -4 -o addr show eth0 | grep -c ' 172.16.0.30/'") for h in ("lb-01", "lb-02")}
    return [h for h, o in out.items() if o.strip().splitlines()[-1].strip() == "1"]
th = threading.Thread(target=poll, daemon=True); th.start()
try:
    time.sleep(2); print("before: VIP holder =", holder())
    t_stop = time.time(); ans("lb-01", "systemctl stop keepalived"); print(f"keepalived stopped on lb-01 (+{time.time()-t_stop:.1f}s for the command)")
    for i in range(20):
        time.sleep(1)
        h = ans("lb-02", "ip -4 -o addr show eth0 | grep -c ' 172.16.0.30/'").strip().splitlines()[-1].strip()
        if h == "1": print(f"lb-02 holds the VIP {time.time()-t_stop:.1f}s after the stop"); break
    time.sleep(10)
    print("while lb-01 is down: VIP holder =", holder())
    t_start = time.time(); ans("lb-01", "systemctl start keepalived")
    for i in range(30):
        time.sleep(1)
        if holder() == ["lb-01"]: print(f"lb-01 holds the VIP again {time.time()-t_start:.1f}s after the start (preempt)"); break
    time.sleep(3)
finally:
    stop = True; th.join(timeout=5)
    print("keepalived on lb-01 at end:", ans("lb-01", "systemctl is-active keepalived").strip().splitlines()[-1])
bad = [(round(t - log[0][0], 2), c) for t, c in log if c not in (200,)]
print(f"requests: {len(log)} total, {len(bad)} not-200", "| failures (t, result):", bad[:12])
if bad: print(f"failure window ~ {bad[-1][0]-bad[0][0]:.2f}s long, first at t={bad[0][0]}s")
