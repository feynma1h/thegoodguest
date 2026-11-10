#!/usr/bin/env python3
"""Measure every edge of every iOS screen and report what does not conform.

    python3 tools/ios_screenshot_gallery.py /tmp/shots     # photograph them
    python3 tools/ios_layout_audit.py /tmp/shots/default   # measure them
    python3 tools/ios_layout_audit.py /tmp/shots/ax5

Exits non-zero when an enforced screen deviates, when a frame was not
photographed settled, or when a state in the catalogue has no frame, so it can
gate.

Written because spotting misalignments by eye, one at a time, was not
converging (0257). This reads the screenshots and states the numbers, so a
claim that the layout is consistent can be checked rather than asserted.

RECALIBRATED FOR THE 2026-11-10 REDESIGN. The grid it used to check — RSScreen's
26pt margin, its 44pt header band and RSActions' fixed action block — went with
the screens it measured (0365): every screen now sits under the system
navigation bar and lays out its own pinned bar. So each bound below is what the
redesigned screens measure, with the frames that set it, read against the
approved canvas (`34s5yipxMgr3bZUBCPiwM1`, drawn at 390x844), which is where
the intent comes from when the screens disagree.

NOTHING IS TIED TO ONE PHONE. The frame size and scale are read from each
image. The navigation bar is found in the frames rather than assumed at a
height, and every vertical bound below it is stated from the bar's centre,
which sits the same distance above everything under it on every iPhone; the
previous version assumed an 874pt phone and crashed on an 844pt one. The pinned
action is measured up from the bottom edge, which is the 34pt home-indicator
inset on every iPhone without a home button.

For each screen it finds, in points:
  bar     the centre of the navigation bar's row of items (back, close,
          account, the mark, an inline title), or `none`
  title   the top of the first ink under the bar — the screen's title —
          measured down from the pass's bar centre
  t-left  that title's left edge
  margin  the content's outermost column: a container's edge (a card,
          picture, plan or list), or the text where there is none
  button  the pinned filled pill: how far its bottom sits off the bottom edge
          and what sits under it (`-` nothing, `q` a quiet action, `c` a
          caption), its left edge, and its right edge's inset
"""
import sys
from pathlib import Path

import numpy as np
from PIL import Image

# ---------------------------------------------------------------------------
# The bounds. Each is stated once, with where it comes from.
# ---------------------------------------------------------------------------

# Two edges, by design: a container (card, picture, plan, list) sits 16pt in,
# and text and titles sit on the text column 4pt inside that, at 20. The canvas
# draws every title on 20 and every container on 16, the room screen and
# guidance excepted. Measured on an 874pt phone: home's cards, the room's steps
# card, review's plan, account's lists and home's example room all at 16.0;
# deletion, which has no container, at 20.7; titles on review, account and
# deletion at 20.0-21.3, and 22.0 at AX5.
#
# So the content's outermost column is one or the other: 16 where a screen has
# a container, the text column where it has none. Which one a column is cannot
# be told reliably from its pixels — a glyph's outermost column is
# antialiased, so it reads as faint as a card's fill — and nothing is lost by
# not trying: the title's left edge below is the exact check on the text column.
# A container edge is exact to the pixel. Text is measured from ink, and a
# capital's ink starts inside its box by a side bearing that grows with the
# face: measured 0.3pt for an Albert Sans "T" at 16pt, 1.2 for a Newsreader
# "D" at 30, 2.0 for its "S" at 42 (AX5).
CONTAINER_EDGE = (15, 17)
TEXT_COLUMN = (19.5, 22.5)

# The navigation bar's row. Every screen on one phone puts its bar items at one
# height; the few points of spread are the glyphs (a 15pt mark, a 22pt person
# icon, a chevron, a 17pt title), measured 84.0-84.3 on an 874pt phone at both
# sizes. Missing on an ordinary screen is a deviation in itself: the canvas
# gives every screen a header, and a bar that drops out moves everything under
# it up by the bar's height.
BAR_SPREAD = 3

# From the bar's centre down to the top of the title's ink. DEFAULT SIZE ONLY:
# the large title grows upward from a fixed baseline (measured 44.3 -> 35.7 at
# AX5), and a title in a larger face may start its ink lower.
#
# A title in the content sits right under an inline bar: measured 36.3 on the
# room screen, review and guidance, which set 4pt above it, and 40.0 on
# account and deletion, which set 8. Those two are the account sheet's, so the
# 4pt never meets itself on one screen; it is in the band rather than flagged.
TITLE = (35, 42)
# Home's title is a navigation-bar large title, set by UIKit under the bar
# rather than in the content. Measured 44.3.
LARGE_TITLE = (42, 46)

# The pinned pill's bottom, up from the bottom edge. DEFAULT SIZE ONLY: what
# sits under the pill grows at AX5 and lifts it, which is the layout working
# (0252).
#
# There is no longer one number, because there is no longer one action block:
# the canvas's block (`.actions`: 34 under the last item, 2 between items)
# puts a lone pill at 34, one over a 50pt quiet action at 86 and one over a
# caption at 62. The build adds 4 under the last item, so, measured:
#   nothing under it      38.0 — the room screen, guidance
#   a quiet action        90.0 — the room screen, review
#   a caption             65.7 — home's first run
# Each is a filled shape measured to the pixel, so the tolerance is not
# typography: 2pt absorbs deletion's 4pt gap where the others use 2 (92.0),
# which nobody sees; a whole step of the bar's padding (4) is out. (The first
# two measured the same at AX5 — the quiet action's 50pt holds — and only a
# caption grew; the rule is kept whole, as 0252 has it.)
BUTTON_UP = {"-": (36, 40), "q": (88, 92), "c": (64, 68)}
# The pill's sides: every pinned bar is padded 20 on both sides (the canvas's
# `.actions` too). Exact, at every size.
BUTTON_SIDE = (19, 21)

# ---------------------------------------------------------------------------
# Which screens are held to the grid.
# ---------------------------------------------------------------------------

# Screens that are deliberately not the ordinary shape. Listed by PREFIX, because
# the catalogue enumerates states rather than screens and a ceremonial screen's
# states are all equally ceremonial — spelling out each one invites the next
# state to be added to the catalogue and forgotten here, which reads as a real
# deviation.
CEREMONIAL_PREFIXES = (
    "capture",   # the camera, full bleed under the scanning HUD, every state
    "splash",    # full-bleed launch, both beats and both motion settings
    "ready",     # the arrival: the room by lamplight on dusk, picture first
)
# A system alert over a screen. The alert is the state's subject and is
# UIKit's, laid out by UIKit — at AX5 it covers the sheet and its own title is
# the first ink under the bar. The sheet beneath it is `account-guest`,
# measured there.
SYSTEM_ALERT = {"account-conflict"}
# Home's title is the navigation bar's large title; every other screen's is
# the first line of its content.
LARGE_TITLE_PREFIX = "home"
# Home's first run has no title in its bar — the welcome's headline sits under
# the example room — so the first thing under the bar is a picture, and there
# is no title band to measure. Everything else on it is held to the grid.
NO_TITLE = {"home-first"}


def kind(sid):
    if sid.startswith(CEREMONIAL_PREFIXES):
        return "ceremonial"
    return "alert" if sid in SYSTEM_ALERT else "screen"


# ---------------------------------------------------------------------------
# Reading a frame.
# ---------------------------------------------------------------------------

# Ink is a drawn glyph or a solid fill: at least this far off the row's ground,
# in grey levels. A card's shadow is at most 8 off and a 5%-opacity fill 9-17;
# text is 160 (the second ink) to 230.
INK = 60
# The bottom of every iPhone without a home button: the home indicator's zone.
HOME_INDICATOR = 34


class Frame:
    """One screenshot, with its ground sampled per row.

    THE GROUND IS SAMPLED PER ROW, from strips just inside both edges. A single
    colour for the whole image assumes a flat ground; the dusk screens, the
    capture HUD and the old parchment gradient all break that, and a row's own
    median is no better — across a full-width dark shape it becomes the shape.
    """

    def __init__(self, path):
        self.path = Path(path)
        self.rgb = np.asarray(Image.open(path).convert("RGB")).astype(int)
        self.H, self.W = self.rgb.shape[:2]
        # Every iPhone this app runs on is 375-440pt wide: 1125-1320px at 3x,
        # 750-880px at 2x. Nothing else about the phone is assumed.
        self.S = 3.0 if self.W > 1000 else 2.0
        a, b = self.px(2), self.px(8)
        strips = np.concatenate([self.rgb[:, a:b], self.rgb[:, self.W - b:self.W - a]], axis=1)
        self.ground = np.median(strips, axis=1)                      # (H, 3)
        grey = self.rgb.mean(axis=2)
        self.ink = np.abs(grey - self.ground.mean(axis=1)[:, None]) > INK
        self.ink[:, :self.px(4)] = False
        self.ink[:, self.W - self.px(4):] = False
        self.bands = self._bands()

    def px(self, pt):
        return int(round(pt * self.S))

    def pt(self, px):
        return px / self.S

    def _bands(self):
        """Runs of inked rows, merged across gaps under 4pt (a line's own leading)."""
        on = self.ink.sum(axis=1) > 3
        on[:3] = False
        on[self.H - self.px(HOME_INDICATOR):] = False
        rows = np.where(on)[0]
        if not len(rows):
            return []
        out, start, last = [], rows[0], rows[0]
        for y in rows[1:]:
            if y - last > self.px(4):
                out.append((start, last + 1))
                start = y
            last = y
        out.append((start, last + 1))
        return out


def status_bar(f):
    """The status bar's band: the first one, if it starts in the top 7% of the frame."""
    if f.bands and f.bands[0][0] < 0.07 * f.H:
        return f.bands[0]
    return None


# A row of ink is the bar's only if each group of ink in it sits where bar items
# go: within 70pt of either edge (a 44pt glass button 16pt in, or home's mark)
# or centred on the screen (an inline title). That is what separates the bar
# from a title that has moved up into the bar's place — which is exactly what
# happens when a screen loses its bar, and is measured to land within 3pt of
# where the bar's items sit.
BAR_SLOT = 70
BAR_GROUP_GAP = 10       # wider than any word space in a bar title
BAR_MAX_HEIGHT = 40      # the items' ink is 17-27pt even at AX5


def bar_row(f, after):
    """Centre of the navigation bar's row of items, in px, or None."""
    for top, bot in f.bands:
        if top < after:
            continue
        if f.pt(bot - top) > BAR_MAX_HEIGHT:
            return None
        cols = np.where(f.ink[top:bot].any(axis=0))[0]
        groups = np.split(cols, np.where(np.diff(cols) > f.px(BAR_GROUP_GAP))[0] + 1)
        for g in groups:
            left = g.max() <= f.px(BAR_SLOT)
            right = g.min() >= f.W - f.px(BAR_SLOT)
            centred = (abs((g.min() + g.max()) / 2 - f.W / 2) <= f.px(6)
                       and g.max() - g.min() <= f.W / 2)
            if not (left or right or centred):
                return None
        return (top + bot) / 2, bot
    return None


# ---------------------------------------------------------------------------
# The content margin.
# ---------------------------------------------------------------------------

def drawn(f, rows):
    """Where a pixel is DRAWN — a glyph or a fill, not a shadow.

    SIGNED, because the shadow and the card it belongs to are the same size of
    difference in opposite directions: a card's white is 6-10 levels LIGHTER
    than the ground and its shadow up to 8 DARKER, for ~14pt around it.
    Counting either direction at one threshold reports the shadow's reach as
    the margin. So lighter counts from 5 levels in every channel (a white card
    is 6-9), darker from 12 in any one (the inset grey is 16 off in red and
    only 10 in blue; a shadow is 8 at most in all three).
    """
    d = f.rgb[rows] - f.ground[rows][:, None, :]
    return (d.min(axis=2) > 4) | (d.min(axis=2) < -12) | f.ink[rows]


def margin(f, top, bottom):
    """The outermost column the content draws to.

    BY COLUMN, at a low threshold, which the ink mask cannot do: a white card
    on the daylight ground never clears a per-row ink test, but it is present
    on hundreds of rows in the same column, and that is unmistakable. A column
    counts once it is drawn on 12pt of rows, which a glyph's stem or a card's
    edge reaches and a stray antialiased pixel does not.
    """
    rows = np.arange(top, bottom)
    if len(rows) < 2:
        return None
    m = drawn(f, rows)
    m[:, :f.px(4)] = False
    m[:, f.W - f.px(4):] = False
    cols = np.where(m.sum(axis=0) >= f.px(12))[0]
    return f.pt(cols.min()) if len(cols) else None


# ---------------------------------------------------------------------------
# The pinned action.
# ---------------------------------------------------------------------------

def pinned_action(f):
    """The pinned filled pill — the screen's primary action — if it has one.

    Found by uniformity rather than by colour, so it catches the ink pill, the
    light pill on dusk and a pill dimmed while busy without a list of hues.

    A ROW OF FILL IS NOT THE PILL. Its label splits the fill, so the run found is
    only the band above or below the label; the shape it belongs to is grown
    from it, row by row, for as long as at least half of the run's width is
    still the pill's colour — which every row of a capsule is, label rows
    included, since its top and bottom edges are flat. Its sides are then read
    where the capsule's round ends reach furthest, at mid-height.

    THE PILL IS THE LOWEST full-width fill in the bottom 40% of the screen.
    Account's sign-in buttons are filled and full-width too, but they live in
    the content, never lower than ~380pt off the bottom even at AX5.
    """
    rgb, W, H = f.rgb, f.W, f.H
    x0, x1 = int(W * 0.15), int(W * 0.85)
    span = rgb[:, x0:x1]
    med = np.median(span, axis=1)                                     # (H, 3)
    uniform = (np.abs(span - med[:, None, :]).max(axis=2) < 30).mean(axis=1) > 0.85
    differs = np.abs(med - f.ground).max(axis=1) > 60
    solid = np.where(uniform & differs)[0]
    solid = solid[(solid > H * 0.6) & (solid < H - f.px(HOME_INDICATOR))]
    if not len(solid):
        return None
    runs = np.split(solid, np.where(np.diff(solid) > 2)[0] + 1)
    for run in sorted(runs, key=lambda r: -r[-1]):
        if len(run) < f.px(3):
            continue
        colour = np.median(med[run], axis=0)
        match = np.abs(rgb - colour).max(axis=2) < 40
        inside = np.where(match[run].mean(axis=0) > 0.5)[0]
        left, right = inside.min(), inside.max()
        density = match[:, left:right + 1].mean(axis=1)
        top, bot = run[0], run[-1]
        while top > 0 and density[top - 1] >= 0.5:
            top -= 1
        while bot < H - 1 and density[bot + 1] >= 0.5:
            bot += 1
        shape = match[top:bot + 1]
        xs = np.where(shape.any(axis=0))[0]
        if not len(xs) or f.pt(xs.max() - xs.min()) < 0.75 * f.pt(W):
            continue
        return {"top": f.pt(top), "bottom_up": f.pt(H - 1 - bot),
                "left": f.pt(xs.min()), "right_in": f.pt(W - 1 - xs.max()),
                "height": f.pt(bot - top + 1), "under": under(f, bot)}
    return None


def under(f, bottom):
    """What sits under the pill: nothing, a quiet action, or a caption.

    Told apart by how dark the first line is, which is the one thing the design
    keeps distinct between them: a quiet action is set in full ink, a caption in
    the second ink (on dusk, the light and the second light). Its size would
    do too, at the default size only.
    """
    # From 2pt under the pill: its own bottom edge, where it falls between two
    # pixel rows, is an antialiased row of half-ink. The nearest line under a
    # pill in this app starts 15pt down.
    start, lo = bottom + 1 + f.px(2), f.H - f.px(HOME_INDICATOR)
    rows = np.where(f.ink[start:lo].sum(axis=1) > 3)[0]
    if not len(rows):
        return "-"
    first = rows[rows <= rows[0] + f.px(24)] + start
    grey = f.rgb[first].mean(axis=2)
    contrast = np.abs(grey - f.ground[first].mean(axis=1)[:, None]).max()
    return "q" if contrast > 195 else "c"


# ---------------------------------------------------------------------------
# A frame that was not photographed settled.
# ---------------------------------------------------------------------------

def unsettled(f, status):
    """Why this frame is not a photograph of the screen, or None.

    A slow simulator — a fresh one analysing its photo library, or a build
    running beside it — photographs either the bare launch ground or a screen
    still fading in from its push, and both measure as a confident wrong answer
    rather than as nothing. The previous version skipped a blank frame without
    a word, so the screen it stood for went unchecked and the count still read
    as complete.
    """
    after = status[1] if status else 0
    if not any(top >= after for top, _ in f.bands):
        return "blank: only the status bar was drawn"
    body = slice(after, f.H - f.px(HOME_INDICATOR))
    d = np.abs(f.rgb[body] - f.ground[body][:, None, :]).max(axis=2)
    contrast = np.percentile(d, 99.9)
    # In the channel that differs most: ink on the ground is ~230 off, the light
    # on dusk ~225, the splash's terracotta mark 186, a screen behind an alert's
    # dimming ~200. A push caught mid-fade measured 91. In grey the mark alone
    # is 136, which is why this is not grey.
    if contrast < 150:
        return f"faded: content contrast {contrast:.0f}, still transitioning"
    return None


# ---------------------------------------------------------------------------
# Measuring and judging.
# ---------------------------------------------------------------------------

def measure(path):
    f = Frame(path)
    status = status_bar(f)
    r = {"frame": f, "status": status, "unsettled": unsettled(f, status)}
    if r["unsettled"]:
        return r
    after = status[1] if status else 0
    bar = bar_row(f, after)
    r["bar_px"] = bar[0] if bar else None
    below = bar[1] if bar else after
    nxt = [(t, b) for t, b in f.bands if t >= below]
    r["title_px"], r["title_left"] = None, None
    if nxt:
        t, b = nxt[0]
        r["title_px"] = t
        r["title_left"] = f.pt(np.where(f.ink[t:b].any(axis=0))[0].min())
    r["button"] = pinned_action(f)
    return r


def judge(sid, r, bar_px, size_invariant):
    """The deviations of one enforced screen, as short strings."""
    f, out = r["frame"], []
    if r["bar_px"] is None:
        out.append("no bar")
    elif abs(f.pt(r["bar_px"] - bar_px)) > BAR_SPREAD:
        out.append(f"bar {f.pt(r['bar_px'] - bar_px):+.0f}")

    title = f.pt(r["title_px"] - bar_px) if r["title_px"] is not None else None
    if sid not in NO_TITLE and title is not None:
        large = sid.startswith(LARGE_TITLE_PREFIX)
        lo, hi = LARGE_TITLE if large else TITLE
        if size_invariant and not lo <= title <= hi:
            out.append(f"title {title:.0f}")
        if not TEXT_COLUMN[0] <= r["title_left"] <= TEXT_COLUMN[1]:
            out.append(f"title left {r['title_left']:.0f}")

    x = r["margin"]
    if x is not None and not (CONTAINER_EDGE[0] <= x <= CONTAINER_EDGE[1]
                              or TEXT_COLUMN[0] <= x <= TEXT_COLUMN[1]):
        out.append(f"margin {x:.0f}")

    b = r["button"]
    if b:
        if size_invariant:
            lo, hi = BUTTON_UP[b["under"]]
            if not lo <= b["bottom_up"] <= hi:
                out.append(f"button {b['bottom_up']:.0f}{b['under']} off bottom")
        if not BUTTON_SIDE[0] <= b["left"] <= BUTTON_SIDE[1]:
            out.append(f"button left {b['left']:.0f}")
        if not BUTTON_SIDE[0] <= b["right_in"] <= BUTTON_SIDE[1]:
            out.append(f"button right {b['right_in']:.0f}")
    return out


def catalogue_ids():
    """Every state the gallery can photograph, when run from the repo root."""
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import ios_screenshot_gallery as gallery
        return [e["id"] for e in gallery.catalogue()]
    except (OSError, ValueError, ImportError):
        return None


def main(argv):
    shots = Path(argv[1] if len(argv) > 1 else "/tmp/rs-all/default")
    # Which text size these frames were taken at, from the directory the
    # capture script wrote them to. Two bounds are default-size only — the
    # title's top and the pill's offset — because what is above the one and
    # under the other grows at AX5 (0252). The bar, the margins and the pill's
    # sides are stated in points and hold at every size.
    size_invariant = shots.name != "ax5"
    paths = sorted(shots.glob("*.png"))
    if not paths:
        sys.exit(f"no frames in {shots}")

    measured = {p.stem: measure(p) for p in paths}
    settled = {s: r for s, r in measured.items() if not r["unsettled"]}

    # The pass's bar, from the frames that have one: the phone decides its
    # height, so it is read rather than assumed.
    bars = [r["bar_px"] for r in settled.values() if r["bar_px"] is not None]
    bar_px = float(np.median(bars)) if bars else None

    for sid, r in settled.items():
        f = r["frame"]
        # The content starts under the bar's glass buttons, which reach 22pt
        # either side of its centre with ~8pt of shadow beyond; on a frame with
        # no bar, under the status bar. It ends where the pinned bar starts,
        # 12pt above its pill — the bar is opaque, so nothing shows through.
        if r["bar_px"] is not None:
            top = r["bar_px"] + f.px(30)
        else:
            top = (r["status"][1] if r["status"] else 0) + f.px(4)
        b = r["button"]
        bottom = f.px(b["top"] - 14) if b else f.H - f.px(HOME_INDICATOR)
        r["margin"] = margin(f, int(top), int(bottom))

    rows, bad, unsettled_ids = [], 0, []
    for sid, r in measured.items():
        if r["unsettled"]:
            unsettled_ids.append(sid)
            rows.append((sid, kind(sid), None, [r["unsettled"]]))
            continue
        k = kind(sid)
        flags = []
        if k == "screen":
            # With no bar anywhere in the pass there is nothing to measure the
            # titles from, and that is itself every screen deviating — never a
            # pass that checked nothing.
            flags = judge(sid, r, bar_px, size_invariant) if bar_px is not None else ["no bar"]
        bad += bool(flags)
        rows.append((sid, k, r, flags))

    w = max(len(s) for s, *_ in rows) + 1
    print(f"{'screen':{w}} {'kind':10} {'bar':>5} {'title':>5} {'t-left':>6} "
          f"{'margin':>7} {'btn↑':>6} {'btn L':>5} {'btn R':>5}  deviations")
    print("-" * (w + 66))
    for sid, k, r, flags in rows:
        if r is None:
            print(f"{sid:{w}} {k:10} {'':>46}  UNSETTLED {flags[0]}")
            continue
        f = r["frame"]
        bar = f"{f.pt(r['bar_px']):.0f}" if r["bar_px"] is not None else "none"
        title = (f"{f.pt(r['title_px'] - bar_px):.0f}"
                 if r["title_px"] is not None and bar_px else "—")
        tl = f"{r['title_left']:.0f}" if r["title_left"] is not None else "—"
        mg = f"{r['margin']:.0f}" if r["margin"] is not None else "—"
        b = r["button"]
        bu = f"{b['bottom_up']:.0f}{b['under']}" if b else "—"
        bl = f"{b['left']:.0f}" if b else "—"
        br = f"{b['right_in']:.0f}" if b else "—"
        print(f"{sid:{w}} {k:10} {bar:>5} {title:>5} {tl:>6} {mg:>7} {bu:>6} "
              f"{bl:>5} {br:>5}  {', '.join(flags)}")

    f0 = next(iter(settled.values()))["frame"] if settled else None
    n = sum(1 for _, k, r, _ in rows if k == "screen" and r is not None)
    scope = ("bar, title, margins and the pinned pill" if size_invariant
             else "bar, margins and the pill's sides (the title's top and the "
                  "pill's offset are default-size bounds and not enforced here)")
    print()
    if f0:
        print(f"frames {f0.W}x{f0.H} at {f0.S:.0f}x ({f0.pt(f0.W):.0f}x{f0.pt(f0.H):.0f}pt); "
              f"the bar's centre {f0.pt(bar_px):.0f}pt down" if bar_px else "no bar found in any frame")
    print(f"{bad} of {n} enforced screens deviate on {scope}")
    failed = bad
    if unsettled_ids:
        print(f"{len(unsettled_ids)} frames UNSETTLED — re-shoot with --only: "
              f"{','.join(unsettled_ids)}")
        failed += len(unsettled_ids)
    ids = catalogue_ids()
    if ids is not None:
        missing = [i for i in ids if i not in measured]
        if missing:
            print(f"{len(missing)} states in the catalogue have no frame: {','.join(missing)}")
            failed += len(missing)
        else:
            print(f"every one of the catalogue's {len(ids)} states has a frame")
    return failed


if __name__ == "__main__":
    sys.exit(0 if main(sys.argv) == 0 else 1)
