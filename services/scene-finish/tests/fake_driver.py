"""A stand-in for render_driver.mjs's `serve` mode, for tests.

Reads one JSON job per stdin line and answers one JSON line, like the real
driver. Behaviour is chosen by the "mode" key of the shell document (ok, crash_first,
error_first, error_always, and for still jobs wrong_size and lose_night); FAKE_STATE
names a file counting jobs across processes, so "first" means the first attempt even
after a restart.
"""
import json
import os
import struct
import sys
import zlib


def png(r: int, g: int, b: int, w: int = 2, h: int = 2) -> bytes:
    def chunk(t, d):
        c = struct.pack(">I", len(d)) + t + d
        return c + struct.pack(">I", zlib.crc32(t + d))
    raw = b"".join(b"\x00" + bytes([r, g, b, 255]) * w for _ in range(h))
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


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
    if job.get("kind") == "still":
        # Night only where twins are drawn: here, whenever a furniture file came
        # with a finish (the page draws neither without a finish). "wrong_size"
        # draws a page of the wrong size; "lose_night" claims a night it never wrote.
        night = bool(job.get("finish") and job.get("furniture"))
        w, h = (job["width"], job["height"]) if mode != "wrong_size" else (64, 48)
        open(f"{job['outDir']}/still.png", "wb").write(png(230, 225, 215, w, h))
        if night and mode != "lose_night":
            open(f"{job['outDir']}/still-night.png", "wb").write(png(20, 22, 30, w, h))
        print(json.dumps({"ok": True, "glRenderer": "fake", "readyMs": 1, "totalMs": 2, "night": night,
                          "finished": bool(job.get("finish"))}), flush=True)
        continue
    for f in job["frames"]:
        for kind, rgb in (("frame", (200, 10, 10)), ("ids", (40, 0, 0)), ("mask", (0, 0, 0))):
            open(f"{job['outDir']}/{kind}_{f['id']}.png", "wb").write(png(*rgb))
    print(json.dumps({"ok": True, "glRenderer": "fake", "readyMs": 1, "runMs": 2, "perFrameMs": 1,
                      "sawFinish": bool(job.get("finish")), "sawFurniture": bool(job.get("furniture"))}), flush=True)
