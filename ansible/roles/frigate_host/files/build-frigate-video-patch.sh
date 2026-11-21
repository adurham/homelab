#!/bin/bash
# Builds /opt/frigate/patches/video.py: stock Frigate 0.17.2 video.py with the
# unbounded-memory ffmpeg drain removed. docker-compose bind-mounts the result over
# /opt/frigate/frigate/video.py.
#
# ROOT CAUSE (2026-11-17): CameraWatchdog.reset_capture_thread() defaults to
# drain_output=True, i.e. ffmpeg_detect_process.communicate(timeout=30). communicate()
# buffers EVERYTHING the child writes to stdout in the capturing Python process. stdout is
# the rawvideo pipe (3.1 MB per 1080p frame). When a Nest/go2rtc stream stalls for 20 s and
# then resumes with a timestamp jump, ffmpeg's fps filter back-fills the gap with duplicate
# frames at memory speed (reproduced: ~640 MB/s). With no consumer backpressure the capture
# process swallows ~10 GB in the 30 s window and the memcg OOM-kills it. The "exceeded fps
# limit" path upstream already uses drain_output=False (wait()), which leaves the pipe
# backpressure intact: the same flood then sits at ~14 MB RSS.
#
# The patch flips that default and the same communicate() in stop_ffmpeg() to wait().
# Re-validate when the image changes (the script aborts if the expected lines moved).
set -euo pipefail

IMAGE="${1:-ghcr.io/blakeblackshear/frigate:stable}"
OUT=/opt/frigate/patches
mkdir -p "$OUT"
docker run --rm --entrypoint cat "$IMAGE" /opt/frigate/frigate/video.py > "$OUT/video.py.orig"

python3 - "$OUT/video.py.orig" "$OUT/video.py" <<'PY'
import re
import sys

src, dst = sys.argv[1:3]
text = open(src, encoding="utf-8").read()
for pattern, repl in (
    (r"drain_output: bool = True", "drain_output: bool = False"),
    (r"(?m)^(\s+)ffmpeg_process\.communicate\(timeout=30\)$", r"\1ffmpeg_process.wait(timeout=30)"),
    (r"(?m)^(\s+)ffmpeg_process\.communicate\(\)$", r"\1ffmpeg_process.wait()"),
):
    text, n = re.subn(pattern, repl, text)
    if n != 1:
        sys.exit(f"patch aborted: {pattern!r} matched {n} times (expected 1) - video.py changed upstream")
compile(text, dst, "exec")
open(dst, "w", encoding="utf-8").write(text)
PY

diff "$OUT/video.py.orig" "$OUT/video.py" || true
