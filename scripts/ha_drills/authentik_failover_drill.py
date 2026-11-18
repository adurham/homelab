"""authentik node-loss drill. For each authentik guest in turn: stop its server container (the other node must carry everything), keep polling the PUBLIC login flow
and the SSO gate through the load-balancer VIP, start it again and wait for health. Reports polls that were not the expected answer.

Expected answers: login flow page 200; gate (no cookie) 302 to /outpost.goauthentik.io/start (never 200: a 200 means the gate silently stopped gating).
Run from the workstation (needs ansible inventory + the fleet key). Always restarts the container it stopped (finally)."""
import os, subprocess, sys, threading, time, urllib.request, urllib.error

ANS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "ansible")
FLOW = "https://auth.chi.lab.amd-e.com/if/flow/default-authentication-flow/"
GATE = "https://gallery.chi.lab.amd-e.com/gallery/manifest.json"
# (ct, pve host the guest lives on is looked up at run time)

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None
opener = urllib.request.build_opener(NoRedirect)   # default TLS verification stays ON: the LB serves a valid wildcard certificate

def probe(url, want):
    t0 = time.time()
    try:
        code = opener.open(url, timeout=4).status
    except urllib.error.HTTPError as e:
        code = e.code
    except Exception as e:
        code = type(e).__name__
    return t0, code, code == want

def ans(host, cmd, timeout=120):
    r = subprocess.run(["ansible", host, "-i", "inventory/proxmox.yml", "-b", "-m", "shell", "-a", cmd], cwd=ANS, capture_output=True, text=True, timeout=timeout)
    return (r.stdout + r.stderr).replace("\\n", "\n")

def node_of(ct):
    for n in ("pve01", "pve02", "pve03"):
        if f"CT {ct} here" in ans(n, f"test -f /etc/pve/lxc/{ct}.conf && pct status {ct} | grep -q running && echo CT {ct} here"):
            return n
    sys.exit(f"CT {ct} not found running")

NODE_IP = {100: "172.16.0.20", 150: "172.16.0.60"}

def wait_healthy(node, ct, secs=420):   # authentik takes 3-6 min to report ready after a start
    # Ask the node itself (the backend uses its own self-signed certificate, hence curl -k for this internal readiness URL only).
    for _ in range(secs // 5):
        r = subprocess.run(["curl", "-sk", "-m", "4", "-o", "/dev/null", "-w", "%{http_code}", f"https://{NODE_IP[ct]}:9443/-/health/ready/"], capture_output=True, text=True)
        if r.stdout.strip() == "200":
            return True
        time.sleep(5)
    return False

log = []
stop_flag = False
def poller():
    while not stop_flag:
        for url, want in ((FLOW, 200), (GATE, 302)):
            t, c, ok = probe(url, want)
            log.append((t, "flow" if url == FLOW else "gate", c, ok))
        time.sleep(0.25)

th = threading.Thread(target=poller, daemon=True); th.start()
results = []
try:
    time.sleep(3)
    base = [x for x in log if not x[3]]
    print("baseline: %d polls, %d unexpected" % (len(log), len(base)))
    for ct in (150, 100):
        node = node_of(ct)
        i0 = len(log)
        t_stop = time.time()
        ans(node, f"pct exec {ct} -- docker stop authentik-server-1")
        print(f"CT {ct} ({node}): server stopped (command {time.time()-t_stop:.1f}s)")
        time.sleep(25)
        mid = log[i0:]
        bad = [(round(t - t_stop, 1), k, c) for t, k, c, ok in mid if not ok]
        print(f"  while down: {len(mid)} polls, {len(bad)} unexpected {bad[:6]}")
        ans(node, f"pct exec {ct} -- docker start authentik-server-1")
        healthy = wait_healthy(node, ct)
        print(f"  restarted, healthy again: {healthy}")
        time.sleep(10)
        results.append((ct, len(mid), len(bad), healthy))
finally:
    stop_flag = True; th.join(timeout=8)
    for ct in (150, 100):
        n = node_of(ct)
        ans(n, f"pct exec {ct} -- docker start authentik-server-1")
total_bad = [(round(t - log[0][0], 1), k, c) for t, k, c, ok in log if not ok]
print(f"TOTAL: {len(log)} polls, {len(total_bad)} unexpected; first few: {total_bad[:8]}")
print("VERDICT:", "single-node loss is invisible to users" if not total_bad else "some requests failed during node loss - see times above")
