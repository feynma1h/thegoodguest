#!/usr/bin/env python3
"""Photograph every state in ScreenGallery, at both Dynamic Type sizes.

    python3 tools/ios_screenshot_gallery.py /tmp/shots      # photograph
    python3 tools/ios_layout_audit.py /tmp/shots/default    # measure

The catalogue is parsed out of ScreenGallery.swift rather than duplicated here,
so a state added there is photographed without editing this file. The UDID below
is the operator's booted simulator; change it or boot that device.

THREE THINGS THIS HAS TO GET RIGHT, each of which produced a wrong contact
sheet before it was handled:

  A MOMENT, NOT A SETTLE. Several screens play a timeline, and the frame worth
  having is at a particular point in it — the splash has two beats, and home's
  menu peek is out from about 2 s and gone by 5.2 s. A single fixed wait
  photographed the peek mid-reveal on every home shot, which is a transient and
  not a screen. Each entry names its own `delay`.

  REDUCE MOTION IS A DEVICE SETTING, not a view modifier.
  `\\.accessibilityReduceMotion` is read-only in EnvironmentValues, so it cannot
  be injected per screen. It is written to `com.apple.Accessibility` and read at
  launch, which means the passes have to be ORDERED by it rather than
  interleaved — hence the four passes below rather than two.

  THE SIMULATOR WEDGES on back-to-back launches. An explicit terminate and a
  settle between shots is what keeps a long pass from dying partway; the same
  pacing fixed `test-without-building` runs crashing with signal kill.
"""
import json
import re
import subprocess
import sys
import time
from pathlib import Path

UDID = "84D7059A-C756-4DE6-B3BD-4C88A38D16DB"
BUNDLE = "com.thegoodguest.TheGoodGuestCapture"
GALLERY = Path("ios/TheGoodGuestCapture/TheGoodGuestCapture/Support/ScreenGallery.swift")
OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/rs-shots")

SIZES = [("default", "large"),
         ("ax5", "accessibility-extra-extra-extra-large")]

# One field, one regex, applied INSIDE a balanced `.init(...)` block rather than
# to the file. A single regex over the whole declaration was fine at four fields
# and became unreadable at six — and, worse, silently skipped any entry whose
# fields wrapped differently, which reads as a screen that does not exist.
FIELDS = {
    "id":     re.compile(r'\bid:\s*"((?:[^"\\]|\\.)*)"'),
    "group":  re.compile(r'\bgroup:\s*"((?:[^"\\]|\\.)*)"'),
    "title":  re.compile(r'\btitle:\s*"((?:[^"\\]|\\.)*)"'),
    "note":   re.compile(r'\bnote:\s*"((?:[^"\\]|\\.)*)"'),
    "delay":  re.compile(r'\bdelay:\s*([0-9.]+)'),
    "reduceMotion": re.compile(r'\breduceMotion:\s*(true|false)'),
}


def blocks(src):
    """Every `.init( ... )` body in the catalogue, by paren balance.

    Balance rather than a non-greedy match: the notes contain parentheses, and
    `.init(id: "review-thin", ... "(dormant)")` truncated at the wrong one.
    """
    start = src.index("static let screens:")
    end = src.index("\n}", start)
    region = src[start:end]
    out, i = [], 0
    while True:
        j = region.find(".init(", i)
        if j < 0:
            return out
        k, depth, in_str, esc = j + 5, 0, False, False
        while k < len(region):
            c = region[k]
            if in_str:
                if esc:
                    esc = False
                elif c == "\\":
                    esc = True
                elif c == '"':
                    in_str = False
            elif c == '"':
                in_str = True
            elif c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
                if depth == 0:
                    break
            k += 1
        out.append(region[j:k + 1])
        i = k + 1


def catalogue():
    src = GALLERY.read_text()
    entries = []
    for b in blocks(src):
        e = {}
        for name, rx in FIELDS.items():
            m = rx.search(b)
            e[name] = m.group(1) if m else None
        if not e["id"]:
            continue
        # Swift string escapes, in the two forms the notes actually use.
        for k in ("title", "note", "group"):
            if e[k]:
                e[k] = e[k].replace('\\"', '"').replace("\\\\", "\\")
        e["delay"] = float(e["delay"]) if e["delay"] else 2.0
        e["reduceMotion"] = e["reduceMotion"] == "true"
        entries.append(e)
    return entries


def sh(*args, check=True):
    return subprocess.run(args, check=check, capture_output=True, text=True)


def set_type_size(size):
    sh("xcrun", "simctl", "ui", UDID, "content_size", size)


def set_reduce_motion(on):
    sh("xcrun", "simctl", "spawn", UDID, "defaults", "write",
       "com.apple.Accessibility", "ReduceMotionEnabled", "-bool",
       "true" if on else "false")


def shoot(screen_id, dest, delay):
    sh("xcrun", "simctl", "terminate", UDID, BUNDLE, check=False)
    time.sleep(0.45)
    sh("xcrun", "simctl", "launch", UDID, BUNDLE, "-rs.gallery.screen", screen_id)
    time.sleep(delay)
    sh("xcrun", "simctl", "io", UDID, "screenshot", "--type=png", str(dest))
    return dest.exists() and dest.stat().st_size > 0


def main():
    screens = catalogue()
    if not screens:
        sys.exit("no screens parsed from ScreenGallery.swift")
    ids = [s["id"] for s in screens]
    if len(set(ids)) != len(ids):
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        sys.exit(f"duplicate ids in the catalogue: {dupes}")
    still = [s for s in screens if not s["reduceMotion"]]
    reduced = [s for s in screens if s["reduceMotion"]]
    print(f"{len(screens)} states ({len(reduced)} under reduce motion) "
          f"x {len(SIZES)} type sizes = {len(screens) * len(SIZES)} shots")

    made, failed = [], []
    for label, size in SIZES:
        set_type_size(size)
        time.sleep(0.6)
        # Ordered by the device setting, not interleaved: writing it costs a
        # spawn and it applies to whatever launches next.
        for rm, group in ((False, still), (True, reduced)):
            if not group:
                continue
            set_reduce_motion(rm)
            d = OUT / label
            d.mkdir(parents=True, exist_ok=True)
            for s in group:
                dest = d / f"{s['id']}.png"
                ok = shoot(s["id"], dest, s["delay"])
                print(f"  [{label}{'/rm' if rm else ''}] {s['id']:<28} "
                      f"{s['delay']:>4.1f}s  {'ok' if ok else 'FAILED'}")
                (made if ok else failed).append({**s, "pass": label, "path": str(dest)})

    set_type_size("large")
    set_reduce_motion(False)
    sh("xcrun", "simctl", "terminate", UDID, BUNDLE, check=False)

    (OUT / "index.json").write_text(json.dumps(made, indent=1))
    print(f"\n{len(made)} shots -> {OUT}")
    if failed:
        print(f"{len(failed)} FAILED: {[f['id'] for f in failed]}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
