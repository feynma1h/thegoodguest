#!/usr/bin/env python3
"""Measure every edge of every iOS screen and report what does not conform.

    python3 tools/ios_screenshot_gallery.py /tmp/shots     # photograph them
    python3 tools/ios_layout_audit.py /tmp/shots/default   # measure them

Exits non-zero when an enforced screen deviates, so it can gate.

Written because spotting misalignments by eye, one at a time, was not
converging. This reads the screenshots and states the numbers, so a claim that
the layout is consistent can be checked rather than asserted.

For each screen it finds, in device points:
  left / right   the content margins (ink extremes, ignoring full-bleed art)
  header         the top of the first ink band below the status bar
  content        the top of the second ink band
  bottom         the last ink row, measured up from the bottom edge

and compares them against the shared constants in RSScreen.
"""
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

SHOTS = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/rs-all/default")
SCALE = 3.0
H = 2622

# RSScreen's constants, in points.
MARGIN = 26
# The header band starts at headerTop (8) below the safe area; where its INK
# falls depends on the glyph, so a few points of spread is typography.
HEADER = (78, 90)
CONTENT = (136, 152)
BUTTON_UP = (74, 84)   # the filled button, measured up from the bottom edge

# Screens that are deliberately not the ordinary shape.
CEREMONIAL = {
    "capture", "capture-dark",   # full-bleed AR overlay
    "gotroom",                   # centred, held beat
    "doorway",                   # the arrival, centred by design
    "splash",                    # full-bleed launch
    "unsupported",               # centred, no action
}
# Unreachable from the flow; measured but not enforced.
LEGACY = {"wait-sending", "wait-analyzing", "wait-long", "wait-trouble",
          "wait-paused", "wait-limited", "qr",
          # Unreachable since the redesign: these became notes, and the sign-in
          # invitation queues in Notes rather than presenting itself.
          "fail-terminal", "fail-upload", "whysignin"}


def ink_mask(path):
    """True where a pixel is DRAWN content — not a shadow, not system chrome.

    Two things fooled the first version of this and made it report every screen
    as broken, which is how it was caught. The primary button carries a 20pt
    shadow, which at a low threshold reads as ink 20pt beyond the button on each
    side — so every screen WITH a filled button reported the same wrong margin
    and every screen without one reported the right margin. And the home
    indicator is a hard dark pill 8pt off the bottom edge, which read as the
    last content row on every screen at once.

    A uniform deviation across unrelated screens is the signature of measuring
    the instrument rather than the thing.
    """
    rgb = np.asarray(Image.open(path).convert("RGB")).astype(int)
    grey = rgb.sum(axis=2) / 3
    # The background is sampled from OUTSIDE the content margin, never from the
    # row itself. A row median is the background only while the row is mostly
    # background — cross a full-width dark card and the median becomes the
    # card, at which point the light margins either side read as ink and the
    # measured margin collapses to the window edge.
    med = np.median(np.concatenate([grey[:, 14:56], grey[:, 1150:1192]], axis=1),
                    axis=1, keepdims=True)
    m = np.zeros(grey.shape, bool)
    # 40, not 20: a drop shadow at its strongest is well under this, and every
    # real glyph and fill is well over it.
    # 60: the rust shadow at its strongest is ~35 grey levels off the
    # parchment, real ink is 90 (a fill) to 180 (text). At 40 the shadow
    # still outvoted the text rows on sparse screens and set the margin.
    m[:, 40:1166] = np.abs(grey[:, 40:1166] - med) > 60
    m[-110:, :] = False      # the home indicator
    return m


def measure(path):
    """Header, first content, left margin, and the filled button if there is one.

    LEFT MARGIN IS A MODE, not a minimum. The primary button's drop shadow puts
    faint pixels ~20pt outside the content margin on the thirty-odd rows it
    covers; taking the leftmost ink anywhere on the screen therefore reported
    the shadow's edge, identically, on every screen that has a filled button —
    which is exactly the uniform-wrong-answer signature. The most common
    per-row left edge is the margin the content actually uses.

    RIGHT MARGIN AND A GENERIC BOTTOM ARE NOT MEASURED. Neither is well defined
    on a screen whose last line is a short sentence: the rightmost ink is where
    that sentence happens to end, not a margin, and the lowest ink is where the
    content happens to stop. What IS comparable is the filled button, so that is
    measured directly and only where one exists.
    """
    m = ink_mask(path)
    m[:200] = False
    on = m.sum(axis=1) > 3
    ys = np.where(on)[0]
    if not len(ys):
        return None

    bands, y = [], 0
    while y < len(on):
        if on[y]:
            s0 = y
            gap = 0
            while y < len(on) and gap < 26:
                y += 1
                gap = 0 if (y < len(on) and on[y]) else gap + 1
            bands.append((s0, y - gap))
        else:
            y += 1

    left = drawn_margin(path, filled_button(path))

    return {
        "left": left,
        "header": bands[0][0] / SCALE,
        "content": bands[1][0] / SCALE if len(bands) > 1 else None,
        "button": filled_button(path),
    }


def drawn_margin(path, button=None):
    """The outermost column the screen actually draws to.

    Measured at a LOW threshold and by column rather than by row, which is what
    the ink mask cannot do. Several containers in this app are 5–14% fills — the
    ID card, the arrival card, the guidance icon tiles — and an ink threshold
    high enough to ignore the primary button's drop shadow cannot see them. The
    result was three screens reporting the left edge of the TEXT inside a card
    instead of the card itself, which reads as a margin defect and is not one.

    Columns rather than rows because a faint fill is faint everywhere: it never
    clears a per-row test, but it is present on hundreds of rows in the same
    column, and that is unmistakable.
    """
    rgb = np.asarray(Image.open(path).convert("RGB")).astype(int)
    keep = np.ones(rgb.shape[0], bool)
    # The device's corner mask reaches ~55pt (165px) in; 200 clears it.
    keep[:200] = False
    keep[H - 200:] = False
    # And the primary button's own rows, plus the reach of its 20pt shadow.
    # This threshold is low enough to see a 5%-opacity card, which means it is
    # also low enough to see that shadow — and the shadow extends past the
    # content margin, so leaving it in reports a margin of zero on every screen
    # that has a filled button.
    if button:
        # Both ends in PIXELS, and generously: a 20pt-radius shadow reaches ~48pt
        # beyond the button, not the 30 first allowed. `top` and `bottom_up` are
        # points and H is pixels, which is the other half of why this window
        # was in the wrong place.
        # pixels — multiplying one and not the other put the exclusion window
        # in the wrong place and left the shadow in.
        lo = int(button["top"] * SCALE) - 200
        hi = H - int(button["bottom_up"] * SCALE) + 200
        keep[max(0, lo):min(H, hi)] = False
    rgb = rgb[keep]
    if not len(rgb):
        return float("nan")
    bg = np.median(np.concatenate([rgb[:, 14:56], rgb[:, 1150:1192]], axis=1)
                   .reshape(-1, 3), axis=0)
    diff = np.abs(rgb - bg).max(axis=2)
    drawn = (diff > 6).sum(axis=0) > 40
    cols = np.where(drawn)[0]
    return cols.min() / SCALE if len(cols) else float("nan")


def filled_button(path):
    """A solid, near-full-width fill: the screen's one prominent button.

    Found by uniformity rather than by colour, so it catches the rust primary,
    the gold CTA, the cream button on the dark failure surfaces and the ink
    button on the sign-in screens without a list of hues to keep in step with
    the palette.
    """
    rgb = np.asarray(Image.open(path).convert("RGB")).astype(int)
    band = rgb[:, 90:1116]
    bg = np.median(rgb[300:340, 40:120].reshape(-1, 3), axis=0)
    rowmean = band.mean(axis=1)
    uniform = (np.abs(band - rowmean[:, None, :]).max(axis=2) < 26).mean(axis=1) > 0.9
    differs = np.abs(rowmean - bg).max(axis=1) > 34
    solid = np.where(uniform & differs)[0]
    solid = solid[solid > 200]
    if len(solid) < 30:
        return None
    # the lowest contiguous run, which is the pinned action
    runs, start = [], solid[0]
    for a, b in zip(solid, solid[1:]):
        if b - a > 4:
            runs.append((start, a)); start = b
    runs.append((start, solid[-1]))
    top, bot = max(runs, key=lambda r: r[1])
    if bot - top < 30:
        return None
    row = rgb[(top + bot) // 2, :]
    same = np.abs(row - row[603]).max(axis=1) < 26
    cols = np.where(same)[0]
    return {"top": top / SCALE, "bottom_up": (H - bot) / SCALE,
            "left": cols.min() / SCALE, "width": (cols.max() - cols.min()) / SCALE}


def main():
    shots = sorted(SHOTS.glob("*.png"))
    rows, bad = [], 0
    for p in shots:
        sid = p.stem
        r = measure(p)
        if not r:
            continue
        kind = ("ceremonial" if sid in CEREMONIAL
                else "legacy" if sid in LEGACY else "screen")
        flags = []
        if kind == "screen":
            # 6pt, not 2: this is measured from INK, and a glyph's left side
            # bearing legitimately varies by a few points between a serif
            # capital, a mono digit and a drawn mark. The button's own left
            # edge below is the exact check.
            if abs(r["left"] - MARGIN) > 6:
                flags.append(f"margin {r['left']:.0f}≠{MARGIN}")
            if not (HEADER[0] <= r["header"] <= HEADER[1]):
                flags.append(f"header {r['header']:.0f}")
            if r["content"] and not (CONTENT[0] <= r["content"] <= CONTENT[1]):
                flags.append(f"content {r['content']:.0f}")
            b = r["button"]
            if b:
                if not (BUTTON_UP[0] <= b["bottom_up"] <= BUTTON_UP[1]):
                    flags.append(f"button {b['bottom_up']:.0f} off bottom")
                if abs(b["left"] - MARGIN) > 2:
                    flags.append(f"button left {b['left']:.0f}")
        if flags:
            bad += 1
        rows.append((sid, kind, r, flags))

    w = max(len(r[0]) for r in rows) + 1
    print(f"{'screen':{w}} {'kind':11} {'margin':>7} {'hdr':>5} {'cont':>5} {'btn↑':>6} {'btn L':>6} {'btn W':>6}  deviations")
    print("-" * (w + 74))
    for sid, kind, r, flags in rows:
        c = f"{r['content']:.0f}" if r["content"] else "—"
        b = r["button"]
        bu = f"{b['bottom_up']:.0f}" if b else "—"
        bl = f"{b['left']:.0f}" if b else "—"
        bw = f"{b['width']:.0f}" if b else "—"
        print(f"{sid:{w}} {kind:11} {r['left']:>7.0f} {r['header']:>5.0f} {c:>5} "
              f"{bu:>6} {bl:>6} {bw:>6}  {', '.join(flags) if flags else ''}")
    print(f"\n{bad} of {sum(1 for r in rows if r[1]=='screen')} enforced screens deviate")
    return bad


if __name__ == "__main__":
    sys.exit(0 if main() == 0 else 1)
