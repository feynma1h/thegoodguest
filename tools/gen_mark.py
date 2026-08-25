#!/usr/bin/env python3
"""The product mark — the ONE source it is drawn from, for every surface.

The mark is two interlocking elliptical rings, tilted back at 35 degrees. It is
the "oo" of "the good guest", compacted: the same two loops the wordmark draws
in the middle of "good", pulled together and set at the angle the script leans.
That is why the mark and the name are never shown side by side — putting them
together would print the same two letters twice.

It appears on seven generated surfaces that used to be five hand-maintained
copies:

    ios/.../Assets.xcassets/AppIcon.appiconset/icon-{light,dark,tinted}-1024.png
    web/src/app/favicon.ico                     (16/32/48, legacy tab icon)
    web/src/app/icon.svg                        (theme-aware tab icon)
    web/src/components/markGeometry.ts          (consumed by Wordmark.tsx)
    ios/.../DesignSystem/MarkGeometry.swift     (consumed by Wordmark.swift)

Regenerate all of them from the repo root with:

    .venv/bin/python tools/gen_mark.py

A change to the mark is a change to this file and nothing else. `tools/
test_gen_mark.py` fails if a generated file on disk stops matching.

THE CONSTRUCTION.

One ring is an ellipse of semi-axes (a, b) swept into a band of width `band`:
the outer edge is (a + band/2, b + band/2) and the inner edge is (a - band/2,
b - band/2). Two of them sit on the horizontal centre line, their centres `dx`
either side of it, and the whole pair has exact 180-degree rotational symmetry
— so its geometric centre and its optical centre are the same point, and there
is no fudge factor to remember when placing it.

Note what the band is NOT: it is not a stroke, and it is not a true constant-
width offset of the centreline ellipse (the offset of an ellipse is not an
ellipse). It is the region between two concentric ellipses — a shape with four
numbers and no renderer-dependent stroke width to re-pick per size. The ring
does read slightly heavier at the ends of the major axis than at the ends of
the minor, by about the axis ratio; that is the same modulation a broad nib
gives, and it is why the mark does not look mechanical.

Each ring is ONE even-odd path holding both ellipses, so the interior is a real
hole. Painting the interior in the ground colour instead would erase the other
ring's arc where it crosses, and the interlock — the only thing that makes this
two rings rather than two circles — would break. Putting all four ellipses into
a single even-odd path fails for the mirror reason: the two bands cross at four
points, and even-odd would punch holes exactly there.

THE FOUR MASTERS, and why a favicon cannot use the logo.

Every master shares the axis ratio (1.4047) and the tilt (-35 degrees). What
changes is scale, how heavy the band is relative to the mark's ink height H,
and how far apart the rings sit:

    logo     band 0.077 H   sep 0.538 a   the mark as drawn
    icon     band 0.077 H   sep 0.538 a   the same drawing at 64.4%, in a tile
    tabReg   band 0.095 H   sep 0.538 a   32 and 48 px: a heavier band survives
    tab16    band 0.180 H   sep 0.620 a   16 px: heavier still, and opened up

At the logo's own proportions the band rasterises to 0.72 px in a 16 px tab
icon — a grey smear rather than a line. tab16 carries 1.62 px and reads as two
rings; it also opens the separation from 0.538 to 0.620 of a, because at that
size two counters 0.538 apart merge into one dark lozenge. Side by side at the
same size the two masters are visibly different drawings. That is deliberate,
and it is the only way this mark holds at tab scale.

THE COLOURS are absolute on every surface. They never inherit `currentColor` or
the surrounding text colour. That is what makes this one logo rather than a
shape that happens to be elliptical: the mark carries its own terracotta onto
any background, so a person meets the same object on the phone icon, the
browser tab and the site header. Light and dark are the SAME drawing in the
same ink — only the reversed case, on terracotta, flips to cream.

Tinted is iOS 18's third appearance and is NOT a multiply of the others; the
system re-maps luminance on its own. The two authored greys sit 83.7 luminance
points apart (1.0% and 84.7%), where anything inside about 10 points welds once
the system has compressed the range.
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw

REPO = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------- geometry ---

CANVAS = 1024.0

#: Both rings lean back by this much. Shared by every master.
TILT_DEG = -35.0

#: Circle-to-cubic constant: the control-point offset that makes four cubic
#: segments approximate an ellipse. Standard 4*(sqrt(2)-1)/3.
KAPPA = 4.0 * (math.sqrt(2.0) - 1.0) / 3.0

Pt = tuple[float, float]


def half_extents(a: float, b: float) -> Pt:
    """Half-width and half-height of an ellipse (a, b) tilted by TILT_DEG."""
    t = math.radians(TILT_DEG)
    return (
        math.hypot(a * math.cos(t), b * math.sin(t)),
        math.hypot(a * math.sin(t), b * math.cos(t)),
    )


@dataclass(frozen=True)
class Master:
    """One drawing of the mark. All four share the axis ratio and the tilt.

    `a`/`b` are the CENTRELINE semi-axes -- the band straddles them, so the
    outer ellipse is (a + band/2, b + band/2) and the inner is the same pair
    less half the band. `dx` is half the distance between the ring centres.
    """

    name: str
    a: float
    b: float
    band: float
    dx: float

    @property
    def axis_ratio(self) -> float:
        return self.a / self.b

    @property
    def outer(self) -> Pt:
        return (self.a + self.band / 2.0, self.b + self.band / 2.0)

    @property
    def inner(self) -> Pt:
        return (self.a - self.band / 2.0, self.b - self.band / 2.0)

    @property
    def ink_height(self) -> float:
        """The mark's own ink height H -- what band and clear-space ratios use."""
        return 2.0 * half_extents(*self.outer)[1]

    @property
    def ink_width(self) -> float:
        return 2.0 * (self.dx + half_extents(*self.outer)[0])

    @property
    def centres(self) -> tuple[Pt, Pt]:
        """The two ring centres, in canvas coordinates."""
        mid = CANVAS / 2.0
        return ((mid - self.dx, mid), (mid + self.dx, mid))


#: The mark as drawn: the logo, and what the wordmark's "oo" compacts into.
LOGO = Master("logo", 302.40, 215.28, 41.23, 162.71)
#: The same drawing at 64.4%, sized to sit in a 1024 app-icon tile.
ICON = Master("icon", 194.63, 138.56, 26.53, 104.73)
#: 32 and 48 px tab icons: a heavier band, so it still rasterises to a line.
TAB_REG = Master("tabReg", 322.44, 229.55, 55.30, 173.50)
#: 16 px: heavier still, and the rings opened up so both counters stay open.
TAB_16 = Master("tab16", 289.59, 206.17, 103.74, 179.55)

MASTERS = (LOGO, ICON, TAB_REG, TAB_16)


def ellipse_cubics(centre: Pt, a: float, b: float) -> tuple[Pt, list[tuple[Pt, Pt, Pt]]]:
    """An ellipse as a start point and four cubic segments.

    Anchored at the ends of the axes and travelling +major, +minor, -major,
    -minor, which is the same phase and direction the supplied artwork uses --
    so a path generated here is comparable with it term by term.
    """
    t = math.radians(TILT_DEG)
    ux, uy = math.cos(t), math.sin(t)  # unit vector along the major axis
    vx, vy = -math.sin(t), math.cos(t)  # unit vector along the minor axis
    cx, cy = centre

    def at(sa: float, sb: float) -> Pt:
        return (cx + sa * a * ux + sb * b * vx, cy + sa * a * uy + sb * b * vy)

    def delta(da: float, db: float) -> Pt:
        return (da * a * ux + db * b * vx, da * a * uy + db * b * vy)

    # The tangent at the head of a quarter points along the NEXT axis, and the
    # tangent at its tail points along the one it started from -- so both
    # control offsets are KAPPA times an axis vector, and both are additive.
    quarters = ((1, 0, 0, 1), (0, 1, -1, 0), (-1, 0, 0, -1), (0, -1, 1, 0))
    start = at(1, 0)
    segs: list[tuple[Pt, Pt, Pt]] = []
    for sa, sb, na, nb in quarters:
        head, tail = at(sa, sb), at(na, nb)
        d_head, d_tail = delta(na, nb), delta(sa, sb)
        segs.append(
            (
                (head[0] + KAPPA * d_head[0], head[1] + KAPPA * d_head[1]),
                (tail[0] + KAPPA * d_tail[0], tail[1] + KAPPA * d_tail[1]),
                tail,
            )
        )
    return start, segs


def _fmt(v: float) -> str:
    return f"{v:.2f}".rstrip("0").rstrip(".")


def ellipse_path(centre: Pt, a: float, b: float) -> str:
    """One ellipse as SVG path data."""
    start, segs = ellipse_cubics(centre, a, b)
    body = "".join(
        f"C{_fmt(c1[0])} {_fmt(c1[1])} {_fmt(c2[0])} {_fmt(c2[1])} "
        f"{_fmt(e[0])} {_fmt(e[1])}"
        for c1, c2, e in segs
    )
    return f"M{_fmt(start[0])} {_fmt(start[1])}{body}Z"


def ring_paths(master: Master) -> tuple[str, str]:
    """The two rings, each ONE even-odd path holding its outer and inner edge."""
    return tuple(  # type: ignore[return-value]
        ellipse_path(centre, *master.outer) + ellipse_path(centre, *master.inner)
        for centre in master.centres
    )


# ---------------------------------------------------------------- palettes ---


@dataclass(frozen=True)
class Appearance:
    """One rendering of the mark: which master, in what ink, on what ground."""

    name: str
    master: Master
    ink: str
    field: str | None  # None => transparent (the mark sits on the page)


#: Absolute, and shared with the web's design tokens: --accent, --paper, --ink.
BRAND_INK = "#c04d3e"
LIGHT_GROUND = "#f9f2ec"
DARK_GROUND = "#282723"
#: The mark when it sits ON terracotta, and the tab icon in a dark UA.
REVERSE_INK = "#fbf5f2"

#: The three iOS 18 app-icon appearances, each on its own tile field.
ICON_LIGHT = Appearance("light", ICON, BRAND_INK, LIGHT_GROUND)
ICON_DARK = Appearance("dark", ICON, BRAND_INK, DARK_GROUND)
#: Authored greyscale; the system re-maps it. NOT a multiply of the above.
ICON_TINTED = Appearance("tinted", ICON, "#ededed", "#1a1a1a")

#: The tab icon, whose two masters answer the two size bands it is drawn at.
TAB_LIGHT = Appearance("tab-light", TAB_16, BRAND_INK, None)
TAB_DARK = Appearance("tab-dark", TAB_16, REVERSE_INK, None)

# --------------------------------------------------------------- rendering ---


def _hex_rgb(h: str) -> tuple[int, int, int]:
    return tuple(int(h[i : i + 2], 16) for i in (1, 3, 5))  # type: ignore[return-value]


def _flatten(centre: Pt, a: float, b: float, scale: float, steps: int = 96) -> list[Pt]:
    """An ellipse as a dense polygon, from the SAME cubics the SVG carries --
    so the raster and the vector are provably one drawing rather than two."""
    start, segs = ellipse_cubics(centre, a, b)
    pts: list[Pt] = [start]
    cur = start
    for c1, c2, end in segs:
        for k in range(1, steps + 1):
            t = k / steps
            u = 1.0 - t
            pts.append(
                (
                    u**3 * cur[0] + 3 * u * u * t * c1[0] + 3 * u * t * t * c2[0] + t**3 * end[0],
                    u**3 * cur[1] + 3 * u * u * t * c1[1] + 3 * u * t * t * c2[1] + t**3 * end[1],
                )
            )
        cur = end
    return [(x * scale, y * scale) for x, y in pts]


def mark_mask(master: Master, n: int) -> Image.Image:
    """A 1-bit mask of the mark at n x n pixels: each ring outer-XOR-inner, the
    two rings joined.

    XOR is what makes the ring interior a real hole; OR across the two rings is
    what makes them interlock rather than cancel where the bands cross.

    `n` is the mask's ACTUAL resolution -- callers that want antialiasing pass
    a supersampled n and downsample the result themselves.
    """
    scale = n / CANVAS
    mask = Image.new("1", (n, n), 0)
    for centre in master.centres:
        ring = Image.new("1", (n, n), 0)
        for axes in (master.outer, master.inner):
            layer = Image.new("1", (n, n), 0)
            ImageDraw.Draw(layer).polygon(_flatten(centre, *axes, scale), fill=1)
            ring = ImageChops.logical_xor(ring, layer)
        mask = ImageChops.logical_or(mask, ring)
    return mask


def render(appearance: Appearance, size: int, supersample: int = 8) -> Image.Image:
    """Rasterise one appearance to a square RGBA image of the given size."""
    n = size * supersample
    field = (*_hex_rgb(appearance.field), 255) if appearance.field else (0, 0, 0, 0)
    img = Image.new("RGBA", (n, n), field)
    ink = Image.new("RGBA", (n, n), (*_hex_rgb(appearance.ink), 255))
    img.paste(ink, mask=mark_mask(appearance.master, n).convert("L"))
    return img.resize((size, size), Image.LANCZOS)


def svg(appearance: Appearance, *, field: bool = False) -> str:
    """The mark as SVG elements: a ground rect if asked, then the two rings."""
    parts = []
    if field and appearance.field:
        parts.append(f'<rect width="1024" height="1024" fill="{appearance.field}"/>')
    parts += [
        f'<path fill-rule="evenodd" d="{d}" fill="{appearance.ink}"/>'
        for d in ring_paths(appearance.master)
    ]
    return "".join(parts)


def write_ico(path: Path) -> None:
    """An ICO of the mark on a transparent field, one PNG entry per size.

    The 16 comes from the 16 px master and the 32 and 48 from the regular one
    -- a .ico cannot answer a media query, so each entry has to be the drawing
    that survives at its own size. The theme-aware answer ships alongside it as
    icon.svg.
    """
    entries = []
    for size, master in ((16, TAB_16), (32, TAB_REG), (48, TAB_REG)):
        buf = BytesIO()
        render(Appearance("ico", master, BRAND_INK, None), size).save(buf, format="PNG")
        entries.append((size, buf.getvalue()))

    offset = 6 + 16 * len(entries)
    header = struct.pack("<HHH", 0, 1, len(entries))
    directory, blobs = b"", b""
    for size, blob in entries:
        directory += struct.pack(
            "<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(blob), offset
        )
        blobs += blob
        offset += len(blob)
    path.write_bytes(header + directory + blobs)


# ----------------------------------------------------------------- targets ---

BANNER = "// Generated by tools/gen_mark.py. Do not edit; edit the generator."


def emit_ts() -> str:
    rings = ",\n  ".join(f'"{d}"' for d in ring_paths(LOGO))
    x0 = CANVAS / 2.0 - LOGO.ink_width / 2.0
    y0 = CANVAS / 2.0 - LOGO.ink_height / 2.0
    return f"""{BANNER}
//
// The product mark's geometry. Consumed by components/Wordmark.tsx. See
// tools/gen_mark.py for the construction, for why the mark is a pair of filled
// rings rather than a stroke, and for why it is never set beside the wordmark.

/** The two rings. Each is ONE path and MUST be filled even-odd, or its
 * interior stops being a hole and the interlock is lost. */
export const MARK_RINGS = [
  {rings},
] as const;

/** The mark's own ink bounds inside the 1024 design space the paths above are
 * authored in. A caller sizes the DRAWING with these rather than a square
 * canvas that is 48% empty. A canvas painter needs the numbers; SVG needs the
 * viewBox below. */
export const MARK_INK_BOX = {{
  x: {x0:.2f},
  y: {y0:.2f},
  w: {LOGO.ink_width:.2f},
  h: {LOGO.ink_height:.2f},
}} as const;

/** `MARK_INK_BOX` as an SVG viewBox, cropping the design space to the ink. */
export const MARK_VIEWBOX =
  `${{MARK_INK_BOX.x}} ${{MARK_INK_BOX.y}} ${{MARK_INK_BOX.w}} ${{MARK_INK_BOX.h}}`;

/** Ink width ÷ ink height. Size the mark by HEIGHT and derive width from this
 * — the design file's minimum sizes are all stated in terms of height. */
export const MARK_ASPECT = {LOGO.ink_width / LOGO.ink_height:.4f};

/** Absolute mark colours. These never inherit from surrounding text. */
export const MARK_INK = "{BRAND_INK}";
/** The mark when it sits ON terracotta rather than beside it. */
export const MARK_REVERSE = "{REVERSE_INK}";
"""


def emit_swift() -> str:
    def ellipse(centre: Pt, axes: Pt) -> str:
        return (
            f"MarkEllipse(cx: {centre[0]:.2f}, cy: {centre[1]:.2f}, "
            f"a: {axes[0]:.2f}, b: {axes[1]:.2f})"
        )

    rings = ",\n        ".join(
        f"MarkRing(outer: {ellipse(c, LOGO.outer)}, inner: {ellipse(c, LOGO.inner)})"
        for c in LOGO.centres
    )
    return f"""{BANNER}
//
// The product mark's geometry, in a 1024x1024 design space. Consumed by
// DesignSystem/Wordmark.swift. See tools/gen_mark.py for the construction and
// for why the mark is never set beside the wordmark.
//
// Emitted as ellipse PARAMETERS rather than as path data, because the splash
// screen animates the wordmark's "oo" into this mark by interpolating these
// five numbers. Path data would have to be re-derived to do that.

import CoreGraphics

/// One ellipse of the mark, in the generated design space.
struct MarkEllipse {{
    let cx: CGFloat
    let cy: CGFloat
    let a: CGFloat
    let b: CGFloat
}}

/// One ring: the band between two concentric ellipses. Fill it EVEN-ODD.
struct MarkRing {{
    let outer: MarkEllipse
    let inner: MarkEllipse
}}

enum MarkGeometry {{
    /// The design space the values below are expressed in.
    static let canvas: CGFloat = {CANVAS:.0f}

    /// How far both rings lean back, in degrees.
    static let tiltDegrees: CGFloat = {TILT_DEG}

    /// The two interlocking rings, left then right.
    static let rings: [MarkRing] = [
        {rings},
    ]

    /// The mark's own ink bounds in the design space -- what clear space
    /// (0.5 H on every side) and the minimum sizes are measured from.
    static let inkWidth: CGFloat = {LOGO.ink_width:.2f}
    static let inkHeight: CGFloat = {LOGO.ink_height:.2f}
}}
"""


# ---------------------------------------------------------------- wordmark ---
#
# The wordmark is traced artwork, not a construction -- see tools/brand/
# wordmark-traced.json. What IS constructed is its "oo", which is replaced here
# by the mark's own rings so the two are one shape rather than two that
# resemble each other. That is what lets the iOS splash carry the name into the
# mark as a plain scale-and-translate instead of a shape interpolation, and it
# is why the mark may never be set beside the name: they would be the same
# drawing, printed twice.
#
# The substitution is very nearly a no-op on the lettering. Measured against
# the traced source, the "oo" it replaces is 138.93 x 80.46 where the mark's
# own aspect gives 138.22 x 80.46 -- 0.5% narrower -- and a mark at that height
# carries a band of 6.20 against the script's own 6.2 stroke. The mark IS the
# oo at its natural size; nothing needed rescaling to fit.

TRACED = REPO / "tools/brand/wordmark-traced.json"

#: Which of contour 1's cubics draw the two rings rather than the lettering.
#: Contour 1 is the connected outline of "good": it runs right-to-left along
#: the top edge and back left-to-right along the bottom, so the ring pair
#: occupies two runs rather than one. The segments either side of them (12 and
#: 71) are the CONNECTOR edges where the g and the d meet the rings, and they
#: are kept -- cutting those too would leave the letters with nothing to join.
RING_TOP = range(13, 30)
RING_BOTTOM = range(72, 89)


def _parse_path(d: str) -> list[tuple[Pt, list[tuple[Pt, Pt, Pt]]]]:
    """The traced path as contours of cubics. It uses only M, C and Z."""
    contours: list[tuple[Pt, list[tuple[Pt, Pt, Pt]]]] = []
    for chunk in d.split("M")[1:]:
        nums = [float(v) for v in chunk.replace("C", " ").replace("Z", " ").split()]
        start = (nums[0], nums[1])
        rest = nums[2:]
        segs = [
            ((rest[i], rest[i + 1]), (rest[i + 2], rest[i + 3]), (rest[i + 4], rest[i + 5]))
            for i in range(0, len(rest) - 5, 6)
        ]
        contours.append((start, segs))
    return contours


def _cubic(p0: Pt, c1: Pt, c2: Pt, p1: Pt, t: float) -> Pt:
    u = 1.0 - t
    return (
        u**3 * p0[0] + 3 * u * u * t * c1[0] + 3 * u * t * t * c2[0] + t**3 * p1[0],
        u**3 * p0[1] + 3 * u * u * t * c1[1] + 3 * u * t * t * c2[1] + t**3 * p1[1],
    )


@dataclass(frozen=True)
class Wordmark:
    """The lettering with its "oo" replaced by the mark.

    `script` is every contour EXCEPT the two rings and their three counters,
    filled even-odd. `oo_centre` and `oo_scale` place the mark inside it.
    """

    script: list[tuple[Pt, list[tuple[Pt, Pt, Pt]]]]
    oo_centre: Pt
    oo_scale: float
    width: float
    height: float
    baseline: float
    x_height: float


def load_wordmark() -> Wordmark:
    import json

    src = json.loads(TRACED.read_text())
    contours = _parse_path(src["d"])
    start, segs = contours[1]
    anchors = [start] + [s[2] for s in segs]

    # Where the ring pair sits, measured off the traced artwork itself rather
    # than assumed, so replacing the source re-measures rather than mis-places.
    pts: list[Pt] = []
    cur = start
    for i, (c1, c2, end) in enumerate(segs):
        if i in RING_TOP or i in RING_BOTTOM:
            pts += [_cubic(cur, c1, c2, end, k / 50) for k in range(51)]
        cur = end
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    centre = ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2)
    scale = (max(ys) - min(ys)) / LOGO.ink_height

    # A loud guard on the cut. If the traced source is ever re-supplied, these
    # segment indices will not survive it, and a silent mis-cut would leave the
    # lettering mangled in a way only a human eye would catch.
    aspect = (max(xs) - min(xs)) / (max(ys) - min(ys))
    if not 1.70 < aspect < 1.76:
        raise SystemExit(
            f"the cut does not look like the ring pair (aspect {aspect:.4f}); "
            "RING_TOP/RING_BOTTOM no longer match tools/brand/wordmark-traced.json"
        )

    # "good" minus its rings: the g side, then the d side, each closed across
    # the stroke where its ring used to begin.
    def run(indices: list[int]) -> tuple[Pt, list[tuple[Pt, Pt, Pt]]]:
        return (anchors[indices[0]], [segs[i] for i in indices])

    g_side = run(list(range(30, 72)))
    d_side = run(list(range(89, len(segs))) + list(range(0, 13)))

    script = [c for i, c in enumerate(contours) if i not in (1, 5, 6, 7)]
    script += [g_side, d_side]
    return Wordmark(
        script=script,
        oo_centre=centre,
        oo_scale=scale,
        width=src["width"],
        height=src["height"],
        baseline=src["baseline"],
        x_height=src["xHeight"],
    )


def wordmark_script_path(wm: Wordmark) -> str:
    """The lettering minus its "oo", as ONE even-odd path."""
    out = []
    for start, segs in wm.script:
        body = "".join(
            f"C{_fmt(c1[0])} {_fmt(c1[1])} {_fmt(c2[0])} {_fmt(c2[1])} "
            f"{_fmt(e[0])} {_fmt(e[1])}"
            for c1, c2, e in segs
        )
        out.append(f"M{_fmt(start[0])} {_fmt(start[1])}{body}Z")
    return "".join(out)


def wordmark_ring_paths(wm: Wordmark) -> tuple[str, str]:
    """The mark's two rings, placed where the lettering wants its "oo"."""
    paths = []
    for cx, _ in LOGO.centres:
        centre = (
            wm.oo_centre[0] + (cx - CANVAS / 2) * wm.oo_scale,
            wm.oo_centre[1],
        )
        outer = tuple(v * wm.oo_scale for v in LOGO.outer)
        inner = tuple(v * wm.oo_scale for v in LOGO.inner)
        paths.append(ellipse_path(centre, *outer) + ellipse_path(centre, *inner))
    return tuple(paths)  # type: ignore[return-value]


ICON_DIR = REPO / "ios/RoomStudioCapture/RoomStudioCapture/Assets.xcassets/AppIcon.appiconset"
WEB_APP = REPO / "web/src/app"


def icon_svg() -> str:
    """The tab icon: one file, both schemes, absolute fills on every path.

    The 16 px master, because a browser draws this at tab size whatever its
    intrinsic viewBox says.
    """
    light = "".join(
        f'<path class="ink" fill-rule="evenodd" d="{d}"/>' for d in ring_paths(TAB_16)
    )
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 1024">'
        "<style>"
        f".ink{{fill:{BRAND_INK}}}"
        f"@media(prefers-color-scheme:dark){{.ink{{fill:{REVERSE_INK}}}}}"
        "</style>"
        f"{light}"
        "</svg>"
    )


def emit_wordmark_ts(wm: Wordmark) -> str:
    rings = ",\n  ".join(f'"{d}"' for d in wordmark_ring_paths(wm))
    return f"""{BANNER}
//
// The wordmark: the lettering, and the mark sitting in it as the "oo" of
// "good". Traced artwork -- tools/brand/wordmark-traced.json is its source and
// it cannot be regenerated from numbers, unlike the mark.
//
// It ships as THREE paths rather than one because the rings must be filled
// even-odd to keep their interiors open, and folding them into the script's
// own even-odd path would punch holes where the two bands cross. Paint all
// three in the same ink; their union is the wordmark.

/** The lettering, minus its "oo". Fill EVEN-ODD -- it carries its counters. */
export const WORDMARK_SCRIPT = "{wordmark_script_path(wm)}";

/** The "oo": the mark's own rings, at the size and place the lettering wants
 * them. Each is ONE path and MUST be filled even-odd. */
export const WORDMARK_RINGS = [
  {rings},
] as const;

/** The wordmark's own box, which the paths above are authored in. A canvas
 * painter needs the numbers; SVG needs the viewBox. */
export const WORDMARK_BOX = {{ w: {wm.width:.2f}, h: {wm.height:.2f} }} as const;

export const WORDMARK_VIEWBOX = `0 0 ${{WORDMARK_BOX.w}} ${{WORDMARK_BOX.h}}`;

/** Width ÷ height, for sizing by height. */
export const WORDMARK_ASPECT = {wm.width / wm.height:.4f};

/** The script's own baseline and x-height, for setting it against other type.
 * Note how little of the box the x-height is: the long loops mean a legible
 * wordmark needs roughly 6x the height you would guess from the x-height. */
export const WORDMARK_BASELINE = {wm.baseline:.2f};
export const WORDMARK_X_HEIGHT = {wm.x_height:.2f};
"""


def emit_wordmark_swift(wm: Wordmark) -> str:
    def contour(start: Pt, segs: list[tuple[Pt, Pt, Pt]]) -> str:
        flat = [f"{start[0]:.2f}", f"{start[1]:.2f}"]
        for c1, c2, e in segs:
            flat += [f"{v:.2f}" for v in (c1[0], c1[1], c2[0], c2[1], e[0], e[1])]
        return "[" + ", ".join(flat) + "]"

    contours = ",\n        ".join(contour(s, g) for s, g in wm.script)
    rings = ",\n        ".join(
        "MarkRing(outer: MarkEllipse(cx: {:.2f}, cy: {:.2f}, a: {:.2f}, b: {:.2f}), "
        "inner: MarkEllipse(cx: {:.2f}, cy: {:.2f}, a: {:.2f}, b: {:.2f}))".format(
            wm.oo_centre[0] + (cx - CANVAS / 2) * wm.oo_scale,
            wm.oo_centre[1],
            LOGO.outer[0] * wm.oo_scale,
            LOGO.outer[1] * wm.oo_scale,
            wm.oo_centre[0] + (cx - CANVAS / 2) * wm.oo_scale,
            wm.oo_centre[1],
            LOGO.inner[0] * wm.oo_scale,
            LOGO.inner[1] * wm.oo_scale,
        )
        for cx, _ in LOGO.centres
    )
    return f"""{BANNER}
//
// The wordmark: the lettering, and the mark sitting in it as the "oo" of
// "good". Traced artwork -- tools/brand/wordmark-traced.json is its source and
// it cannot be regenerated from numbers, unlike the mark.
//
// The lettering arrives as flat cubic data rather than as generated drawing
// calls: 634 curves would be 634 lines of `addCurve`, which is slow to
// type-check and no clearer. Each contour is [startX, startY, then c1x c1y c2x
// c2y endX endY per curve].
//
// `rings` is the SAME MarkRing type the app icon is drawn from, which is the
// point: SplashView carries these to MarkGeometry.rings, and because both are
// the same shape that carry is a scale and a translate rather than a shape
// interpolation.

import CoreGraphics

enum WordmarkGeometry {{
    /// The design space the values below are expressed in.
    static let width: CGFloat = {wm.width:.2f}
    static let height: CGFloat = {wm.height:.2f}

    /// The script's own baseline and x-height within that box.
    static let baseline: CGFloat = {wm.baseline:.2f}
    static let xHeight: CGFloat = {wm.x_height:.2f}

    /// The lettering, minus its "oo". Fill EVEN-ODD; it carries its counters.
    static let scriptContours: [[CGFloat]] = [
        {contours},
    ]

    /// The "oo", as the mark's own rings at the size the lettering wants.
    static let rings: [MarkRing] = [
        {rings},
    ]
}}
"""


def main() -> None:
    for appearance in (ICON_LIGHT, ICON_DARK, ICON_TINTED):
        out = ICON_DIR / f"icon-{appearance.name}-1024.png"
        render(appearance, 1024).convert("RGB").save(out)
        print(f"  {out.relative_to(REPO)}")

    write_ico(WEB_APP / "favicon.ico")
    print(f"  {(WEB_APP / 'favicon.ico').relative_to(REPO)}")

    (WEB_APP / "icon.svg").write_text(icon_svg() + "\n")
    print(f"  {(WEB_APP / 'icon.svg').relative_to(REPO)}")

    ts = REPO / "web/src/components/markGeometry.ts"
    ts.write_text(emit_ts())
    print(f"  {ts.relative_to(REPO)}")

    sw = REPO / "ios/RoomStudioCapture/RoomStudioCapture/DesignSystem/MarkGeometry.swift"
    sw.write_text(emit_swift())
    print(f"  {sw.relative_to(REPO)}")

    wm = load_wordmark()

    wts = REPO / "web/src/components/wordmarkGeometry.ts"
    wts.write_text(emit_wordmark_ts(wm))
    print(f"  {wts.relative_to(REPO)}")

    wsw = REPO / "ios/RoomStudioCapture/RoomStudioCapture/DesignSystem/WordmarkGeometry.swift"
    wsw.write_text(emit_wordmark_swift(wm))
    print(f"  {wsw.relative_to(REPO)}")


if __name__ == "__main__":
    main()
