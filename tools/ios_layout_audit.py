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

NOTHING IS TIED TO ONE DEVICE. The frame size and scale are read from each
image. The navigation bar is found in the frames rather than assumed at a
height, and every vertical bound below it is stated from the bar's centre,
which sits the same distance above everything under it on every iPhone; the
previous version assumed an 874pt phone and crashed on an 844pt one. The pinned
action is measured up from the safe area's bottom edge, read from the frame's
shape, and the column from the frame's width.

For each screen it finds, in points:
  bar     the centre of the navigation bar's row of items (back, close,
          account, the mark, an inline title), or `none`
  title   the top of the first ink under the bar — the screen's title —
          measured down from the pass's bar centre
  t-left  that title's left edge
  margin  the content's outermost column: a container's edge (a card,
          picture, plan or list), or the text where there is none
  button  the pinned filled pill: how far its bottom sits above the safe area
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

# ONE COLUMN (`RSLayout`). Every screen's content starts on one left edge — its
# title, its lines, its cards and pictures, and the pinned pill — 16pt in on a
# phone. That is the website's phone gutter (`px-4`: the "Your house" title,
# the line under it and the room cards all start there) and UIKit's own margin
# on most phones. On a window wider than the readable width plus both margins,
# an iPad, the column centres at that width: 520, the website's paragraph
# measure, after 640 let an iPad's lines run to 94 characters. Both mirror
# `RSLayout`.
#
# Before the column, the redesign's screens put titles on three edges — 16 on
# home and a room, 20 on review, account and deletion, 22 on guidance — because
# the canvas they were drawn from set text 4pt inside the cards' edge and each
# screen chose where to apply the 4.
MARGIN = 16
READABLE_WIDTH = 520
# A container's edge is exact to the pixel, give or take antialiasing. Text is
# measured from ink, and a capital's ink starts inside its box by a side
# bearing that grows with the face: 0.3pt for an Albert Sans "T" at 16pt, 1.2
# for a Newsreader "D" at 30, 2.0 for its "S" at 42 (AX5).
EDGE = 1
BEARING = 2.5


def column(f):
    """Where this frame's column starts, in points from the left edge."""
    w = f.pt(f.W)
    return MARGIN if w - 2 * MARGIN <= READABLE_WIDTH else (w - READABLE_WIDTH) / 2

# The navigation bar's row. Every screen on one phone puts its bar items at one
# height; the few points of spread are the glyphs (a 15pt mark, a 22pt person
# icon, a chevron, a 17pt title), measured 84.0-84.3 on an 874pt phone at both
# sizes. Missing on an ordinary screen is a deviation in itself: the canvas
# gives every screen a header, and a bar that drops out moves everything under
# it up by the bar's height.
BAR_SPREAD = 3

# From the bar's centre down to the top of the title's ink. DEFAULT SIZE ONLY:
# a title in a larger face starts its ink lower (0252).
#
# Every screen's title is the first line of its content, home's included
# (`RSScreenTitle`, `RSLayout.titleTop` under the bar). Home's used to be the
# navigation bar's large title, set by UIKit on its own margin — the column on
# some phones and not on others, and never on an iPad.
TITLE = (34, 39)

# The pinned pill's bottom, up from the safe area's bottom edge (`Frame`). One
# bar for every screen (`RSPinnedBar`), so one number for each thing that can
# sit under the pill: nothing, the bar's own 4; a quiet action, its 50 and the
# 2 between; a caption, its line and the 10 above it; a caption over a quiet
# action, both (deletion with no account ID says why its pill is grey, then
# offers "Not now"). DEFAULT SIZE ONLY: what
# sits under the pill grows at AX5 and lifts it, which is the layout working
# (0252). The pill is a filled shape measured to the pixel, so the 2pt either
# way is rounding, not typography.
#
# Before the bar, each screen padded its own: a lone pill sat at 4 on the room
# screen and guidance and 8 on home; deletion's caption, held at a control's
# height, put its pill 14pt above where home's first-run caption put one.
BUTTON_UP = {"-": (2, 6), "q": (54, 58), "c": (28, 34), "cq": (80, 86)}

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
        # The scale, from the width in pixels, which does not overlap between
        # devices: an iPhone is 375-440pt wide, 750-880px at 2x and 1125-1320
        # at 3x; an iPad is 744-1032pt at 2x, 1488-2064px.
        self.S = 3.0 if 1000 < self.W < 1400 else 2.0
        # The safe area's bottom, from the frame's shape: an iPhone without a
        # home button is ~19.5:9 and keeps 34pt for the home indicator, one
        # with a button is 16:9 and keeps none, and an iPad keeps 20.
        w, h = self.W / self.S, self.H / self.S
        self.bottom_inset = 20 if w >= 600 else (34 if h / w >= 2 else 0)
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
        on[self.H - self.px(self.bottom_inset):] = False
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
    # Searched inside the column, which on an iPad is a band in the middle.
    col = f.px(column(f))
    width = W - 2 * col
    x0, x1 = col + int(width * 0.15), col + int(width * 0.85)
    span = rgb[:, x0:x1]
    med = np.median(span, axis=1)                                     # (H, 3)
    uniform = (np.abs(span - med[:, None, :]).max(axis=2) < 30).mean(axis=1) > 0.85
    differs = np.abs(med - f.ground).max(axis=1) > 60
    solid = np.where(uniform & differs)[0]
    solid = solid[(solid > H * 0.6) & (solid < H - f.px(f.bottom_inset))]
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
        if not len(xs) or xs.max() - xs.min() < 0.75 * width:
            continue
        return {"top": f.pt(top), "bottom_up": f.pt(H - 1 - bot),
                "left": f.pt(xs.min()), "right_in": f.pt(W - 1 - xs.max()),
                "height": f.pt(bot - top + 1),
                "under": under(f, bot, xs.min(), xs.max())}
    return None


def under(f, bottom, left, right):
    """What sits under the pill: nothing, a quiet action, a caption, or a
    caption over a quiet action.

    Looked for only across the pill's own width. On an iPad the window's
    resize grip sits in the bottom corner, beside the bar, and read as a
    caption under every lone pill in the app.

    Told apart by how dark the first line is, which is the one thing the design
    keeps distinct between them: a quiet action is set in full ink, a caption in
    the second ink (on dusk, the light and the second light). Its size would
    do too, at the default size only.
    """
    # From 2pt under the pill: its own bottom edge, where it falls between two
    # pixel rows, is an antialiased row of half-ink. The nearest line under a
    # pill in this app starts 15pt down.
    start, lo = bottom + 1 + f.px(2), f.H - f.px(f.bottom_inset)
    rows = np.where(f.ink[start:lo, left:right + 1].sum(axis=1) > 3)[0]
    if not len(rows):
        return "-"
    def full_ink(lines):
        grey = f.rgb[lines, left:right + 1].mean(axis=2)
        return np.abs(grey - f.ground[lines].mean(axis=1)[:, None]).max() > 195

    first = rows[rows <= rows[0] + f.px(24)] + start
    if full_ink(first):
        return "q"
    rest = rows[rows > rows[0] + f.px(24)] + start
    return "cq" if len(rest) and full_ink(rest) else "c"


# ---------------------------------------------------------------------------
# A frame that was not photographed settled.
# ---------------------------------------------------------------------------

# The app's two grounds, daylight and dusk. An ordinary screen sits on one of
# them out to the frame's edges.
GROUNDS = np.array([(245, 246, 248), (13, 20, 28)])


def unsettled(f, status, ordinary=False):
    """Why this frame is not a photograph of the screen, or None.

    A slow simulator — a fresh one analysing its photo library, or a build
    running beside it — photographs either the bare launch ground or a screen
    still fading in from its push, and both measure as a confident wrong answer
    rather than as nothing. The previous version skipped a blank frame without
    a word, so the screen it stood for went unchecked and the count still read
    as complete.

    And on the first launch after an install the app can still be coming up
    when the shot is taken, which photographs the HOME SCREEN: icons on a
    wallpaper, measured as if they were the app. An ordinary screen's edges are
    daylight or dusk, and a frame whose edges are mostly neither is not it.
    """
    if ordinary:
        edges = f.ground[f.px(80):f.H - f.px(80)]
        near = (np.abs(edges[:, None, :] - GROUNDS[None]).max(axis=2) < 12).any(axis=1)
        if near.mean() < 0.6:
            return "not the app: the frame's edges are not its ground (the home screen, mid-launch?)"
    after = status[1] if status else 0
    if not any(top >= after for top, _ in f.bands):
        return "blank: only the status bar was drawn"
    body = slice(after, f.H - f.px(f.bottom_inset))
    d = np.abs(f.rgb[body] - f.ground[body][:, None, :]).max(axis=2)
    # In the channel that differs most: ink on the ground is ~230 off, the light
    # on dusk ~225, the splash's terracotta mark 186, a screen behind an alert's
    # dimming ~200. A push caught mid-fade measured 91 at its strongest. In
    # grey the mark alone is 136, which is why this is not grey.
    #
    # COUNTED, not a percentile: the splash's thin mark is under 0.1% of an
    # iPad's frame, so a 99.9th percentile read the ground and called a settled
    # splash faded. A frame mid-fade has no pixel that strong at all.
    strong = int((d > 150).sum())
    if strong < f.px(6) ** 2:
        return f"faded: {strong} pixels at full contrast, still transitioning"
    return None


# ---------------------------------------------------------------------------
# Measuring and judging.
# ---------------------------------------------------------------------------

def measure(path):
    f = Frame(path)
    status = status_bar(f)
    ordinary = kind(Path(path).stem) == "screen"
    r = {"frame": f, "status": status, "unsettled": unsettled(f, status, ordinary)}
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


def judge(sid, r, bar_px, default_size):
    """The deviations of one enforced screen, as short strings."""
    f, out = r["frame"], []
    col = column(f)
    if r["bar_px"] is None:
        out.append("no bar")
    elif abs(f.pt(r["bar_px"] - bar_px)) > BAR_SPREAD:
        out.append(f"bar {f.pt(r['bar_px'] - bar_px):+.0f}")

    title = f.pt(r["title_px"] - bar_px) if r["title_px"] is not None else None
    if sid not in NO_TITLE and title is not None:
        if default_size and not TITLE[0] <= title <= TITLE[1]:
            out.append(f"title {title:.0f}")
        if not col - EDGE <= r["title_left"] <= col + BEARING:
            out.append(f"title left {r['title_left']:.0f}")

    x = r["margin"]
    if x is not None and not col - EDGE <= x <= col + BEARING:
        out.append(f"margin {x:.0f}")

    b = r["button"]
    if b:
        up = b["bottom_up"] - f.bottom_inset
        if default_size:
            lo, hi = BUTTON_UP[b["under"]]
            if not lo <= up <= hi:
                out.append(f"button {up:.0f}{b['under']} above the safe area")
        if abs(b["left"] - col) > EDGE:
            out.append(f"button left {b['left']:.0f}")
        if abs(b["right_in"] - col) > EDGE:
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
    # capture script wrote them to (`default`, `ax5`, `xs`, `default-dark`...).
    # Two bounds are default-size only — the title's top and the pill's offset
    # — because what is above the one and under the other moves with the type
    # (0252). The bar, the column and the pill's sides hold at every size.
    default_size = shots.name.split("-")[0] == "default"
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
        bottom = f.px(b["top"] - 14) if b else f.H - f.px(f.bottom_inset)
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
            flags = judge(sid, r, bar_px, default_size) if bar_px is not None else ["no bar"]
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
        bu = f"{b['bottom_up'] - f.bottom_inset:.0f}{b['under']}" if b else "—"
        bl = f"{b['left']:.0f}" if b else "—"
        br = f"{b['right_in']:.0f}" if b else "—"
        print(f"{sid:{w}} {k:10} {bar:>5} {title:>5} {tl:>6} {mg:>7} {bu:>6} "
              f"{bl:>5} {br:>5}  {', '.join(flags)}")

    f0 = next(iter(settled.values()))["frame"] if settled else None
    n = sum(1 for _, k, r, _ in rows if k == "screen" and r is not None)
    scope = ("bar, title, column and the pinned pill" if default_size
             else "bar, column and the pill's sides (the title's top and the "
                  "pill's offset are default-size bounds and not enforced here)")
    print()
    if f0:
        print(f"frames {f0.W}x{f0.H} at {f0.S:.0f}x ({f0.pt(f0.W):.0f}x{f0.pt(f0.H):.0f}pt); "
              f"the column {column(f0):.0f}pt in; the safe area's bottom {f0.bottom_inset}pt; "
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
