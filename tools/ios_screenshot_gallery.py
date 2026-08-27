#!/usr/bin/env python3
"""Photograph every screen in ScreenGallery, at one or more Dynamic Type sizes.

Pairs with tools/ios_layout_audit.py, which measures what this captures. The
UDID below is the operator's booted simulator; change it or boot that device.

The catalogue is parsed out of ScreenGallery.swift rather than duplicated here,
so a screen added there is photographed without editing this file.
"""
import re
import subprocess
import sys
import time
from pathlib import Path

UDID = "84D7059A-C756-4DE6-B3BD-4C88A38D16DB"
BUNDLE = "com.roomstudio.RoomStudioCapture"
GALLERY = Path("ios/RoomStudioCapture/RoomStudioCapture/Support/ScreenGallery.swift")
OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/rs-shots")

ENTRY = re.compile(
    r'\.init\(id:\s*"([^"]+)",\s*title:\s*"([^"]+)",\s*\n?\s*note:\s*"([^"]+)"(,\s*settles:\s*true)?',
    re.MULTILINE,
)


def catalogue():
    src = GALLERY.read_text()
    out = []
    for m in ENTRY.finditer(src):
        out.append({
            "id": m.group(1),
            "title": m.group(2),
            "note": m.group(3),
            "settles": bool(m.group(4)),
        })
    return out


def sh(*args, check=True):
    return subprocess.run(args, check=check, capture_output=True, text=True)


def set_type_size(size):
    sh("xcrun", "simctl", "ui", UDID, "content_size", size)


def shoot(screen_id, dest, settles=False):
    sh("xcrun", "simctl", "terminate", UDID, BUNDLE, check=False)
    time.sleep(0.35)
    sh("xcrun", "simctl", "launch", UDID, BUNDLE, "-rs.gallery.screen", screen_id)
    time.sleep(2.6 if settles else 1.5)
    sh("xcrun", "simctl", "io", UDID, "screenshot", "--type=png", str(dest))
    return dest.exists() and dest.stat().st_size > 0


def main():
    screens = catalogue()
    if not screens:
        sys.exit("no screens parsed from ScreenGallery.swift")
    print(f"{len(screens)} screens in catalogue")

    passes = [("default", "large"), ("ax5", "accessibility-extra-extra-extra-large")]
    # AX5 is the pass that has actually caught this app's layout defects, but a
    # full second set doubles the page weight for little gain — photograph the
    # screens where the pinned-action rule and glyph alignment are under real
    # pressure, which is where 0224 and 0238 both landed.
    # Everything the redesign built or rebuilt. None of it has been through an
    # accessibility shot, and the last pass over unshot screens found three
    # defects — all of them invisible to a green suite.
    ax5_only = {
        "home-first", "home-quiet", "home-flight", "home-arrival",
        "home-needsyou", "home-trouble",
        "contents-quiet", "contents-eventful", "contents-nocount",
        "notes-full", "notes-news", "notes-quiet",
        "desk-sending", "desk-working", "desk-paused", "desk-limited",
        "desk-retry", "desk-clear",
        "rooms-list", "rooms-stale", "rooms-empty", "rooms-unreachable",
        "fail-incomplete", "profile",
    }

    made = []
    for label, size in passes:
        set_type_size(size)
        time.sleep(0.6)
        for s in screens:
            if label == "ax5" and s["id"] not in ax5_only:
                continue
            d = OUT / label
            d.mkdir(parents=True, exist_ok=True)
            dest = d / f"{s['id']}.png"
            ok = shoot(s["id"], dest, s["settles"])
            print(f"  [{label}] {s['id']:<18} {'ok' if ok else 'FAILED'}")
            if ok:
                made.append({**s, "pass": label, "path": str(dest)})

    set_type_size("large")
    sh("xcrun", "simctl", "terminate", UDID, BUNDLE, check=False)

    import json
    (OUT / "index.json").write_text(json.dumps(made, indent=1))
    print(f"\n{len(made)} shots -> {OUT}")


if __name__ == "__main__":
    main()
