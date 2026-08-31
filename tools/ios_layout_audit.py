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
# Which text size these frames were taken at, from the directory the capture
# script wrote them to. Two of the five bounds below are calibrated at the
# default size and are meaningless at AX5 — see SIZE_INVARIANT.
PASS = SHOTS.name
SCALE = 3.0
H = 2622

# RSScreen's constants, in points.
MARGIN = 26
# The header band starts at headerTop (8) below the safe area; where its INK
# falls depends on the glyph, so a few points of spread is typography.
HEADER = (78, 90)
CONTENT = (136, 152)
BUTTON_UP = (74, 84)   # the filled button, measured up from the bottom edge

# TWO OF THOSE BOUNDS ARE DEFAULT-SIZE ONLY, and enforcing them at AX5 reports
# every screen in the app as broken.
#
# `CONTENT` is where the first line below the header sits, and the header's own
# glyph is taller at AX5 — measured, the whole app moves together from 140-152
# to 140-156. `BUTTON_UP` is the pinned action's offset off the bottom edge, and
# what sits below it is the closing line, which is also taller — measured,
# 77-87 becomes 117-184. Both are the layout working, not failing.
#
# What IS invariant is stated in points and stays enforced at every size: the
# content margin, the top of the header band, and the button's own left edge.
SIZE_INVARIANT = PASS != "ax5"

# Screens that are deliberately not the ordinary shape. Listed by PREFIX as
# well as by id, because the catalogue enumerates states rather than screens and
# a ceremonial screen's four states are all equally ceremonial — spelling out
# `doorway-noweb-signed` alongside `doorway` invites the next state to be added
# to the catalogue and forgotten here, which reads as a real deviation.
CEREMONIAL_PREFIXES = (
    "capture",       # full-bleed AR overlay, every tracking state
    "doorway",       # the arrival, centred by design, all four corners
    "splash",        # full-bleed launch, both beats and both motion settings
)
CEREMONIAL = {
    "gotroom",       # centred, held beat
    "unsupported",   # centred, no action
}
# Reachable by nothing in the flow; measured but not enforced.
#
# `whysignin` is presented by no call site outside this gallery — the sign-in
# invitation queues in Notes rather than presenting itself — and `qr` is built
# but blocked on deep links. They are photographed so the surfaces do not rot
# unseen, and not enforced because nothing can regress them.
LEGACY = {"qr", "whysignin", "whysignin-one"}
# Screens whose content is CENTRED, where an ink margin is not a margin: the
# leftmost ink is wherever the longest line happens to end up. Profile centres
# the mark, the greeting and the intro copy on purpose; at AX5 that puts its
# leftmost ink 48pt in, which is the design and not a deviation.
CENTRED = {"profile", "profile-noid", "profile-linked"}


def kind(sid):
    if sid.startswith(CEREMONIAL_PREFIXES) or sid in CEREMONIAL:
        return "ceremonial"
    if sid in LEGACY:
        return "legacy"
    return "centred" if sid in CENTRED else "screen"


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
    # THE BACKGROUND IS SAMPLED PER ROW, not once for the whole image.
    #
    # A single median colour assumes a flat ground, and the parchment has a
    # vertical gradient. That was survivable while the excluded rows were a
    # band at the BOTTOM, which left one contiguous region whose median sat in
    # the middle of it. At AX5 the pinned button moves up the screen, so the
    # exclusion punches a hole in the middle and leaves two chunks far apart on
    # the gradient — the median then sits in neither, every row of the smaller
    # chunk differs from it at every column, and the margin reads 0 on eleven
    # unrelated screens at once. Comparing each row against its own edge sample
    # removes the assumption rather than widening a threshold.
    bg = np.median(np.concatenate([rgb[:, 14:56], rgb[:, 1150:1192]], axis=1),
                   axis=1)
    diff = np.abs(rgb - bg[:, None, :]).max(axis=2)
    drawn = (diff > 6).sum(axis=0) > 40
    cols = np.where(drawn)[0]
    return cols.min() / SCALE if len(cols) else float("nan")


# What a pinned filled action looks like, as three bounds on the whole SHAPE.
#
# EVERY ONE OF THESE IS SET BY MEASUREMENT ACROSS BOTH TEXT SIZES, because the
# thing they have to be told apart from is a full-width dark note card and the
# two overlap on any single axis. Measured over all 166 frames:
#
#   width   button 340-350 · card 347-350 · the capsule inside a card 254
#   height  button 53-60 at default, 98-177 at AX5 · card 133-154 at default,
#           up to 616 at AX5 · a hairline edge 1
#   bottom  button 77-186 up · card 554-575 up at default, 0-70 at AX5
#
# So width alone cannot separate them, and neither can height: a card at the
# default size (133-154) sits inside a button's AX5 range (98-177). Together
# they do, on every frame — no card is ever full width AND under 200pt tall AND
# within 290pt of the bottom.
#
# The 40pt floor is the one bound that is not about telling a button from a
# card: `RSActions` sits inside the safe area, so a pinned action can never
# touch the bottom edge. A full-width shape that does is content running off the
# screen, which is what notes-full does at AX5.
BUTTON_WIDTH_MIN = 300
BUTTON_HEIGHT = (30, 200)
BUTTON_BOTTOM = (40, 290)


def filled_button(path):
    """A solid, near-full-width fill of button height: the screen's pinned action.

    Found by uniformity rather than by colour, so it catches the rust primary,
    the gold CTA, the cream button on the dark failure surfaces and the ink
    button on the sign-in screens without a list of hues to keep in step with
    the palette.

    A CANDIDATE RUN IS NOT THE BUTTON, and assuming it was is how this reported
    six Notes screens as broken. The label splits a button's fill into two runs,
    so on home the run this finds is 27pt tall against a 56pt button — a height
    bound on the run would therefore have rejected every real button in the app.
    Meanwhile the gaps between lines of text inside a dark note card are runs of
    exactly the same shape: full content width, uniform, differing from the
    page. Nothing about a single run separates the two.

    What separates them is the SHAPE the run belongs to. So each candidate is
    grown vertically along a column just inside its own left edge — clear of any
    label, which is inset by the padding — until the fill ends, and the result
    is accepted only at a real button's height. A button grows to ~56pt; a note
    card grows to its whole 250pt; review's sketch plate grows to its 230.

    Returns the SHAPE's bottom, not the run's, which is the same number for a
    real button and the reason the `BUTTON_UP` bounds are unchanged.
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
    runs, start = [], solid[0]
    for a, b in zip(solid, solid[1:]):
        if b - a > 4:
            runs.append((start, a)); start = b
    runs.append((start, solid[-1]))

    # Lowest first: the pinned action is the bottom-most thing of its kind.
    for top, bot in sorted(runs, key=lambda r: -r[1]):
        shape = grow(rgb, top, bot)
        if not shape:
            continue
        s_top, s_bot, left, right = shape
        height = (s_bot - s_top) / SCALE
        bottom_up = (H - s_bot) / SCALE
        if not (BUTTON_HEIGHT[0] <= height <= BUTTON_HEIGHT[1]):
            continue
        if not (BUTTON_BOTTOM[0] <= bottom_up <= BUTTON_BOTTOM[1]):
            continue
        if (right - left) / SCALE < BUTTON_WIDTH_MIN:
            continue
        return {"top": s_top / SCALE, "bottom_up": bottom_up,
                "left": left / SCALE, "width": (right - left) / SCALE,
                "height": height}
    return None


def grow(rgb, top, bot):
    """The full extent of the filled shape a candidate run sits in.

    Walked along a column 12px inside the shape's own left edge rather than down
    the middle: the middle is where a button's label is, and a label is exactly
    what breaks the run in the first place.
    """
    mid = (top + bot) // 2
    row = rgb[mid, :]
    same = np.abs(row - row[603]).max(axis=1) < 26
    cols = np.where(same)[0]
    if len(cols) < 2:
        return None
    left, right = int(cols.min()), int(cols.max())
    x = min(left + 12, right)
    fill = rgb[mid, x]
    y0, y1 = top, bot
    while y0 > 0 and np.abs(rgb[y0 - 1, x] - fill).max() < 26:
        y0 -= 1
    while y1 < H - 1 and np.abs(rgb[y1 + 1, x] - fill).max() < 26:
        y1 += 1
    return y0, y1, left, right


def main():
    shots = sorted(SHOTS.glob("*.png"))
    rows, bad = [], 0
    for p in shots:
        sid = p.stem
        r = measure(p)
        if not r:
            continue
        k = kind(sid)
        flags = []
        if k == "screen":
            # 16pt, and it is a LOOSE check by nature: this is measured from
            # ink, and on a sparse screen the only ink at the left edge is a
            # chevron's single vertex and an italic serif capital, both of
            # which sit several points inside their own box. Measured, that is
            # 40pt on notes-quiet and 32 on desk-clear — correct layouts,
            # flagged at any tolerance tight enough to be interesting.
            #
            # So this catches the defect it is actually for — a screen that
            # forgot RSScreen.horizontal, which is off by a whole 26 — and the
            # button's own left edge below, measured from a container rather
            # than a glyph, is the exact check.
            if abs(r["left"] - MARGIN) > 16:
                flags.append(f"margin {r['left']:.0f}≠{MARGIN}")
            if not (HEADER[0] <= r["header"] <= HEADER[1]):
                flags.append(f"header {r['header']:.0f}")
            if (SIZE_INVARIANT and r["content"]
                    and not (CONTENT[0] <= r["content"] <= CONTENT[1])):
                flags.append(f"content {r['content']:.0f}")
            b = r["button"]
            if b:
                if (SIZE_INVARIANT
                        and not (BUTTON_UP[0] <= b["bottom_up"] <= BUTTON_UP[1])):
                    flags.append(f"button {b['bottom_up']:.0f} off bottom")
                if abs(b["left"] - MARGIN) > 2:
                    flags.append(f"button left {b['left']:.0f}")
        if flags:
            bad += 1
        rows.append((sid, k, r, flags))

    w = max(len(r[0]) for r in rows) + 1
    print(f"{'screen':{w}} {'kind':11} {'margin':>7} {'hdr':>5} {'cont':>5} {'btn↑':>6} {'btn L':>6} {'btn W':>6}  deviations")
    print("-" * (w + 74))
    for sid, k, r, flags in rows:
        c = f"{r['content']:.0f}" if r["content"] else "—"
        b = r["button"]
        bu = f"{b['bottom_up']:.0f}" if b else "—"
        bl = f"{b['left']:.0f}" if b else "—"
        bw = f"{b['width']:.0f}" if b else "—"
        print(f"{sid:{w}} {k:11} {r['left']:>7.0f} {r['header']:>5.0f} {c:>5} "
              f"{bu:>6} {bl:>6} {bw:>6}  {', '.join(flags) if flags else ''}")
    n = sum(1 for r in rows if r[1] == "screen")
    scope = ("margin, header, first content line and the button"
             if SIZE_INVARIANT
             else "margin, header and the button's left edge "
                  "(the two default-size bounds are not enforced here)")
    print(f"\n{bad} of {n} enforced screens deviate on {scope}")
    return bad


if __name__ == "__main__":
    sys.exit(0 if main() == 0 else 1)
