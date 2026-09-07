#!/usr/bin/env python3
"""
op shim for hermes-gw-01. Drop-in replacement for the `op` CLI that
forwards every call over a Unix socket (reverse-tunneled from the
`hlxc` SSH session on the Mac) to the real `op` running locally on the
Mac, where 1Password Desktop is Touch-ID unlocked. No vault password,
service-account token, or decrypted secret is ever written to this
host's disk -- the socket only exists while an hlxc session is
actively forwarding it, and every read requires physical approval
(Touch ID / security key) on the Mac at the moment of the call.

Which socket: OP_BROKER_SOCK, exported into the tmux session by hlxc.
Multiple concurrent hlxc windows each forward their own remote path
(/run/hermes-op-broker/<tmux-session-name>.sock) back to the one broker
on the Mac, so every window has independent 1Password access.

If the socket isn't present (no hlxc session forwarding it right now),
fails clearly instead of hanging.
"""
import json
import os
import socket
import sys

# Each hlxc window forwards its own socket, at
# /run/hermes-op-broker/<tmux-session-name>.sock, and injects that path
# here via OP_BROKER_SOCK in the tmux session environment. The fallback
# below is the LEGACY pre-2026-09-07 single-session path; since that
# scheme was retired nothing binds it anymore, so falling back to it now
# means "OP_BROKER_SOCK was not set in this environment" -- which the
# error message must say out loud, because the two failure modes look
# identical otherwise and have completely different fixes.
_ENV_SOCK = os.environ.get("OP_BROKER_SOCK")
_LEGACY_SOCK = "/run/hermes-op-broker.sock"
SOCK_PATH = _ENV_SOCK or _LEGACY_SOCK


def main():
    if not os.path.exists(SOCK_PATH):
        if _ENV_SOCK:
            sys.stderr.write(
                f"op: broker socket {SOCK_PATH} not found (from OP_BROKER_SOCK) "
                "-- the hlxc SSH connection forwarding this tmux session's "
                "1Password access is not up right now. Reconnect with hlxc.\n"
            )
        else:
            sys.stderr.write(
                "op: OP_BROKER_SOCK is not set in this environment, and the "
                f"legacy fallback {SOCK_PATH} does not exist. Each hlxc window "
                "exports OP_BROKER_SOCK=/run/hermes-op-broker/<tmux-session>.sock "
                "into its tmux session; a shell that did not inherit it (a pane "
                "predating the per-session bridge, or a plain `su - hermes` "
                "login) has no 1Password access. Start/attach via hlxc.\n"
            )
        sys.exit(1)

    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(90)  # generous: Touch ID / dialog approval takes real time
        s.connect(SOCK_PATH)
    except OSError as e:
        sys.stderr.write(f"op: could not reach broker at {SOCK_PATH}: {e}\n")
        sys.exit(1)

    req = json.dumps({"args": sys.argv[1:]}) + "\n"
    s.sendall(req.encode("utf-8"))

    chunks = []
    try:
        while True:
            chunk = s.recv(65536)
            if not chunk:
                break
            chunks.append(chunk)
            if chunk.endswith(b"\n"):
                break
    except socket.timeout:
        sys.stderr.write("op: broker request timed out (no approval on the Mac?)\n")
        sys.exit(1)

    data = b"".join(chunks).decode("utf-8")
    try:
        resp = json.loads(data)
    except json.JSONDecodeError:
        sys.stderr.write(f"op: malformed broker response: {data!r}\n")
        sys.exit(1)

    sys.stdout.write(resp.get("stdout", ""))
    sys.stderr.write(resp.get("stderr", ""))
    sys.exit(resp.get("returncode", 1))


if __name__ == "__main__":
    main()
