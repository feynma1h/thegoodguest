#!/usr/bin/env python3
"""The product mark — the ONE source it is drawn from, for every surface.

The mark is the room corner: a pointy-top hexagon divided by a three-way seam
into two wall faces and a floor, seen at true 30 degree isometric. It appears on
five surfaces that used to be five hand-maintained copies:

    ios/.../Assets.xcassets/AppIcon.appiconset/icon-{light,dark,tinted}-1024.png
    web/src/app/favicon.ico                     (16/32/48, legacy tab icon)
    web/src/app/icon.svg                        (theme-aware tab icon)
    web/src/components/markGeometry.ts          (consumed by Wordmark.tsx)
    ios/.../DesignSystem/MarkGeometry.swift     (consumed by Wordmark.swift)

Regenerate all of them from the repo root with:

    .venv/bin/python tools/gen_mark.py

A change to the mark is a change to this file and nothing else. `tools/
test_gen_mark.py` fails if a generated file on disk stops matching.

THE CONSTRUCTION, and why it is a fill rather than a stroke.

Everything derives from one hexagon of circumradius R about the canvas centre.
Its three faces are that hexagon cut by the seam from the centre to the top
vertex and to the two lower vertices. Each face is then inset from the lines it
touches by one of two amounts:

    RIM_BAND   68.0    where a face meets the hexagon's outer edge
    SEAM_HALF  25.2    where a face meets one of the three seam lines

The ink is not drawn as a stroke. It is a solid hexagon *plate* laid down first,
with the three faces painted on top; the bands are what the faces leave
uncovered. That matters for consistency: a stroke's width is a separate number
that has to be re-chosen per size and per renderer, and that is exactly how the
web wordmark drifted from the icon (its band ran ~9.1% of mark height where the
icon's runs ~7.8%, and its seam matched its outline where the icon's seam is
deliberately lighter). With a fill there is no second number. Every surface is
the same polygons scaled, and the band ratio is a consequence rather than a
setting.

THE TWO PLATES, and why the mark still needs two of them.

The plate is the only thing that changes between appearances:

    framed     plate at R           the rim band shows; for a LIGHT field
    frameless  plate at R_INNER     only the seams show; for a DARK field

R_INNER is not a taste choice, it is forced: insetting a hexagon's edges by
RIM_BAND drops its apothem to R*sqrt(3)/2 - RIM_BAND, so the plate that
circumscribes the three faces exactly has circumradius 301.48. Decision 0176
measured why dark needs it -- a dark icon keeping the full band sits 0.11 off
its field and reads as a heavy ring rather than a drawn edge.

The face colours are ABSOLUTE in both plates. They never inherit `currentColor`
or the surrounding text colour. That is what makes this one logo rather than a
shape that happens to be hexagonal: the mark carries its own cream and its own
rust onto any background, so a person meets the same object on the phone icon,
the browser tab, the site header and the dark room page. The web wordmark's
old `currentColor` outline is precisely what broke that -- on the room page its
walls went ink-dark and the mark rendered as its own negative.

Tinted is iOS 18's third appearance and is NOT a multiply of the others; the
system re-maps luminance on its own. Decision 0176 sampled the real mapping off
a home screen, and the four surfaces here are the authored grayscale values it
records as landing correctly once the system is done with them.
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw

REPO = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------- geometry ---

CANVAS = 1024.0
R = 380.0
RIM_BAND = 68.0
SEAM_HALF = 25.2

S = math.sqrt(3.0) / 2.0
#: The plate that circumscribes the three faces exactly -- see the docstring.
R_INNER = (R * S - RIM_BAND) / S

Pt = tuple[float, float]

#: Hexagon vertices, screen coordinates (y down), relative to the centre.
T: Pt = (0.0, -R)
UR: Pt = (R * S, -R / 2)
LR: Pt = (R * S, R / 2)
B: Pt = (0.0, R)
LL: Pt = (-R * S, R / 2)
UL: Pt = (-R * S, -R / 2)
CENTRE: Pt = (0.0, 0.0)

RIM = "rim"
SEAM = "seam"

#: Each face as (vertices, per-edge band). Edge i runs vertex i -> vertex i+1.
FACES: list[tuple[list[Pt], list[str]]] = [
    # right wall
    ([CENTRE, T, UR, LR], [SEAM, RIM, RIM, SEAM]),
    # left wall
    ([CENTRE, LL, UL, T], [SEAM, RIM, RIM, SEAM]),
    # floor
    ([CENTRE, LR, B, LL], [SEAM, RIM, RIM, SEAM]),
]


def hexagon(radius: float) -> list[Pt]:
    """The pointy-top hexagon of the given circumradius, centred on the origin."""
    return [
        (radius * math.cos(math.radians(a)), radius * math.sin(math.radians(a)))
        for a in (-90, -30, 30, 90, 150, 210)
    ]


def _inward_normal(p: Pt, q: Pt, inside: Pt) -> Pt:
    dx, dy = q[0] - p[0], q[1] - p[1]
    n = (dy, -dx)
    length = math.hypot(*n)
    n = (n[0] / length, n[1] / length)
    if n[0] * (inside[0] - p[0]) + n[1] * (inside[1] - p[1]) < 0:
        n = (-n[0], -n[1])
    return n


def inset(vertices: list[Pt], bands: list[str]) -> list[Pt]:
    """Move each edge inward by its band, then re-intersect to get the corners.

    Per-edge rather than uniform: a face's rim edges and its seam edges carry
    different bands, which is what gives the mark a heavier outer edge than
    seam. Insetting the polygon by a single amount would flatten that.
    """
    amounts = [RIM_BAND if b == RIM else SEAM_HALF for b in bands]
    cx = sum(v[0] for v in vertices) / len(vertices)
    cy = sum(v[1] for v in vertices) / len(vertices)

    lines = []  # (nx, ny, c) with n.p == c on the offset line
    for i, amount in enumerate(amounts):
        p, q = vertices[i], vertices[(i + 1) % len(vertices)]
        n = _inward_normal(p, q, (cx, cy))
        lines.append((n[0], n[1], n[0] * p[0] + n[1] * p[1] + amount))

    out: list[Pt] = []
    for i in range(len(lines)):
        a1, b1, c1 = lines[i - 1]
        a2, b2, c2 = lines[i]
        det = a1 * b2 - a2 * b1
        out.append(((c1 * b2 - c2 * b1) / det, (a1 * c2 - a2 * c1) / det))
    return out


#: The three faces, inset. Identical in every appearance -- only the plate moves.
FACE_POLYS: list[list[Pt]] = [inset(v, b) for v, b in FACES]

# ---------------------------------------------------------------- palettes ---


@dataclass(frozen=True)
class Appearance:
    """One rendering of the mark. `plate` is the ink hexagon's circumradius."""

    name: str
    plate: float
    ink: str
    wall: str
    floor: str
    field: str | None  # None => transparent (the mark sits on the page)


#: Absolute, and shared with the web's design tokens: --ink, --paper, --accent.
INK = "#3a2d22"
WALL = "#f7efdf"
FLOOR = "#8e3b2f"

FRAMED = Appearance("framed", R, INK, WALL, FLOOR, None)
FRAMELESS = Appearance("frameless", R_INNER, INK, WALL, FLOOR, None)

#: The three iOS 18 app-icon appearances, each on its own tile field.
ICON_LIGHT = Appearance("light", R, INK, WALL, FLOOR, "#e9e2d2")
ICON_DARK = Appearance("dark", R_INNER, INK, WALL, FLOOR, "#181109")
#: Authored grayscale; the system re-maps it (0176). NOT a multiply of the above.
ICON_TINTED = Appearance("tinted", R, "#242424", "#f2f2f2", "#878787", "#1a1a1a")

# --------------------------------------------------------------- rendering ---


def _hex_rgb(h: str) -> tuple[int, int, int]:
    return tuple(int(h[i : i + 2], 16) for i in (1, 3, 5))  # type: ignore[return-value]


def render(appearance: Appearance, size: int, supersample: int = 8) -> Image.Image:
    """Rasterise the mark to a square RGBA image of the given size."""
    n = size * supersample
    scale = n / CANVAS
    mid = n / 2.0

    def to_px(pts: list[Pt]) -> list[tuple[float, float]]:
        return [(mid + x * scale, mid + y * scale) for x, y in pts]

    field = (*_hex_rgb(appearance.field), 255) if appearance.field else (0, 0, 0, 0)
    img = Image.new("RGBA", (n, n), field)
    draw = ImageDraw.Draw(img)
    draw.polygon(to_px(hexagon(appearance.plate)), fill=(*_hex_rgb(appearance.ink), 255))
    for poly, colour in zip(
        FACE_POLYS, (appearance.wall, appearance.wall, appearance.floor), strict=True
    ):
        draw.polygon(to_px(poly), fill=(*_hex_rgb(colour), 255))
    return img.resize((size, size), Image.LANCZOS)


def path_data(pts: list[Pt], centre: float = CANVAS / 2) -> str:
    """An SVG path for a closed polygon, in the 0..1024 viewBox."""

    def fmt(v: float) -> str:
        return f"{v:.2f}".rstrip("0").rstrip(".")

    head, *rest = [(centre + x, centre + y) for x, y in pts]
    body = " ".join(f"{fmt(x)} {fmt(y)}" for x, y in rest)
    return f"M{fmt(head[0])} {fmt(head[1])} {body}Z"


def svg(appearance: Appearance, *, field: bool = False) -> str:
    plate = path_data(hexagon(appearance.plate))
    parts = []
    if field and appearance.field:
        parts.append(f'<rect width="1024" height="1024" fill="{appearance.field}"/>')
    parts.append(f'<path d="{plate}" fill="{appearance.ink}"/>')
    for poly, colour in zip(
        FACE_POLYS, (appearance.wall, appearance.wall, appearance.floor), strict=True
    ):
        parts.append(f'<path d="{path_data(poly)}" fill="{colour}"/>')
    return "".join(parts)


def write_ico(path: Path, sizes: tuple[int, ...] = (16, 32, 48)) -> None:
    """An ICO of the framed mark on a transparent field, one PNG entry per size.

    Framed, because a .ico is the legacy fallback and cannot answer a media
    query -- the framed plate is the one that survives on a light tab strip,
    which is what a browser falling back to .ico is most likely showing. The
    theme-aware answer ships alongside it as icon.svg.
    """
    entries = []
    for size in sizes:
        buf = BytesIO()
        render(FRAMED, size).save(buf, format="PNG")
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

BANNER_TS = "// Generated by tools/gen_mark.py. Do not edit; edit the generator."
BANNER_SWIFT = "// Generated by tools/gen_mark.py. Do not edit; edit the generator."


def emit_ts() -> str:
    faces = ",\n  ".join(f'"{path_data(p)}"' for p in FACE_POLYS)
    return f"""{BANNER_TS}
//
// The product mark's geometry, in a 0 0 1024 1024 viewBox. Consumed by
// components/Wordmark.tsx. See tools/gen_mark.py for the construction and for
// why the mark is a fill rather than a stroke.

/** Ink plate for a mark sitting on a LIGHT field -- the rim band shows. */
export const PLATE_FRAMED = "{path_data(hexagon(R))}";

/** Ink plate for a mark sitting on a DARK field -- only the seams show. */
export const PLATE_FRAMELESS = "{path_data(hexagon(R_INNER))}";

/** Right wall, left wall, floor. Identical under either plate. */
export const FACES = [
  {faces},
] as const;

/** Absolute mark colours. These never inherit from surrounding text. */
export const MARK_INK = "{INK}";
export const MARK_WALL = "{WALL}";
export const MARK_FLOOR = "{FLOOR}";
"""


def emit_swift() -> str:
    def swift_poly(pts: list[Pt]) -> str:
        body = ", ".join(
            f"CGPoint(x: {CANVAS / 2 + x:.2f}, y: {CANVAS / 2 + y:.2f})" for x, y in pts
        )
        return f"[{body}]"

    faces = ",\n        ".join(swift_poly(p) for p in FACE_POLYS)
    return f"""{BANNER_SWIFT}
//
// The product mark's geometry, in a 1024x1024 design space. Consumed by
// DesignSystem/Wordmark.swift. See tools/gen_mark.py for the construction and
// for why the mark is a fill rather than a stroke.

import CoreGraphics

enum MarkGeometry {{
    /// The design space the points below are expressed in.
    static let canvas: CGFloat = {CANVAS:.0f}

    /// Ink plate for a mark on a LIGHT field -- the rim band shows.
    static let plateFramed: [CGPoint] = {swift_poly(hexagon(R))}

    /// Ink plate for a mark on a DARK field -- only the seams show.
    static let plateFrameless: [CGPoint] = {swift_poly(hexagon(R_INNER))}

    /// Right wall, left wall, floor. Identical under either plate.
    static let faces: [[CGPoint]] = [
        {faces},
    ]
}}
"""


ICON_DIR = REPO / "ios/RoomStudioCapture/RoomStudioCapture/Assets.xcassets/AppIcon.appiconset"
WEB_APP = REPO / "web/src/app"


def main() -> None:
    for appearance in (ICON_LIGHT, ICON_DARK, ICON_TINTED):
        out = ICON_DIR / f"icon-{appearance.name}-1024.png"
        render(appearance, 1024).convert("RGB").save(out)
        print(f"  {out.relative_to(REPO)}")

    write_ico(WEB_APP / "favicon.ico")
    print(f"  {(WEB_APP / 'favicon.ico').relative_to(REPO)}")

    icon_svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 1024">'
        "<style>"
        ".frameless{display:none}"
        "@media(prefers-color-scheme:dark){"
        ".framed{display:none}.frameless{display:inline}}"
        "</style>"
        f'<g class="framed">{svg(FRAMED)}</g>'
        f'<g class="frameless">{svg(FRAMELESS)}</g>'
        "</svg>"
    )
    (WEB_APP / "icon.svg").write_text(icon_svg + "\n")
    print(f"  {(WEB_APP / 'icon.svg').relative_to(REPO)}")

    ts = REPO / "web/src/components/markGeometry.ts"
    ts.write_text(emit_ts())
    print(f"  {ts.relative_to(REPO)}")

    sw = REPO / "ios/RoomStudioCapture/RoomStudioCapture/DesignSystem/MarkGeometry.swift"
    sw.write_text(emit_swift())
    print(f"  {sw.relative_to(REPO)}")


if __name__ == "__main__":
    main()
