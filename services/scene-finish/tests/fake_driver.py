"""A stand-in for render_driver.mjs's `serve` mode, for tests.

Reads one JSON job per stdin line and answers one JSON line, like the real
driver. Behaviour is chosen by the "mode" key of the shell document (ok, crash_first,
error_first, error_always); FAKE_STATE names a file counting jobs across
processes, so "first" means the first attempt even after a restart.
"""
import json
import os
import struct
import sys
import zlib


def png(r: int, g: int, b: int) -> bytes:
    def chunk(t, d):
        c = struct.pack(">I", len(d)) + t + d
        return c + struct.pack(">I", zlib.crc32(t + d))
    raw = b"".join(b"\x00" + bytes([r, g, b, 255]) * 2 for _ in range(2))
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 2, 2, 8, 6, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


def attempt() -> int:
    """Jobs seen so far across driver processes (a retry is a new process)."""
    path = os.environ["FAKE_STATE"]
    n = int(open(path).read()) + 1 if os.path.exists(path) else 1
    open(path, "w").write(str(n))
    return n


for line in sys.stdin:
    job = json.loads(line)
    calls = attempt()
    mode = json.load(open(job["shell"]))["mode"]
    if mode == "crash_first" and calls == 1:
        sys.exit(3)
    if mode == "error_always" or (mode == "error_first" and calls == 1):
        print(json.dumps({"ok": False, "error": "viewer never settled"}), flush=True)
        continue
    os.makedirs(job["outDir"], exist_ok=True)
    for f in job["frames"]:
        for kind, rgb in (("frame", (200, 10, 10)), ("ids", (40, 0, 0)), ("mask", (0, 0, 0))):
            open(f"{job['outDir']}/{kind}_{f['id']}.png", "wb").write(png(*rgb))
    print(json.dumps({"ok": True, "glRenderer": "fake", "readyMs": 1, "runMs": 2, "perFrameMs": 1,
                      "sawFinish": bool(job.get("finish")), "sawFurniture": bool(job.get("furniture"))}), flush=True)
