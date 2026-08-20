"""The mark is one drawing — these are the pins that keep it one drawing.

`tools/gen_mark.py` generates every surface the product mark appears on. That
only buys consistency if the generated files on disk are actually what the
generator produces, and if the colours it bakes in still agree with the design
tokens each platform reads. Both drift silently: a generated file is editable,
and a token can be changed in `globals.css` or `RSColor.swift` without anyone
thinking about the icon.

The mark previously lived as three hand-maintained copies and they diverged in
exactly these two ways — a treatment that no longer matched the icon, and an
iOS lockup that had drifted to a different glyph altogether while its own
docstring still claimed to mirror the web. These tests are the cheap guard
against that recurring.
"""

from __future__ import annotations

import math
import re
from pathlib import Path

import gen_mark
import numpy as np
import pytest
from PIL import Image, ImageFilter

REPO = Path(__file__).resolve().parent.parent


# ------------------------------------------------------------------ geometry --


def test_frameless_plate_circumscribes_the_faces_exactly():
    """The dark plate is forced by the rim band, not chosen (decision 0176).

    If this drifts, the dark icon either shows a sliver of frame or clips the
    faces -- both of which read as a drawing mistake rather than a variant.
    """
    expected = (gen_mark.R * gen_mark.S - gen_mark.RIM_BAND) / gen_mark.S
    assert gen_mark.R_INNER == pytest.approx(expected)
    assert gen_mark.R_INNER == pytest.approx(301.48, abs=0.01)

    # Every face vertex lies inside the frameless plate, and at least one sits
    # on its boundary -- that is what "circumscribes exactly" means.
    apothem = gen_mark.R_INNER * gen_mark.S
    distances = []
    for face in gen_mark.FACE_POLYS:
        for x, y in face:
            # distance from centre to the point, projected onto each edge normal
            for k in range(6):
                angle = math.radians(k * 60)
                distances.append(x * math.cos(angle) + y * math.sin(angle))
    assert max(distances) <= apothem + 1e-6
    assert max(distances) == pytest.approx(apothem, abs=1e-6)


def test_the_mark_is_a_regular_pointy_top_hexagon():
    hexagon = gen_mark.hexagon(gen_mark.R)
    width = max(x for x, _ in hexagon) - min(x for x, _ in hexagon)
    height = max(y for _, y in hexagon) - min(y for _, y in hexagon)
    assert width / height == pytest.approx(math.sqrt(3) / 2, abs=1e-6)


def test_rim_band_is_heavier_than_the_seam():
    """The outer edge reads heavier than the seam. Equalising them is the
    single change that most makes the mark stop looking like the icon."""
    assert gen_mark.RIM_BAND > 2 * gen_mark.SEAM_HALF


# ------------------------------------------------------------------- outputs --


@pytest.mark.parametrize(
    "relative",
    [
        "web/src/components/markGeometry.ts",
        "ios/RoomStudioCapture/RoomStudioCapture/DesignSystem/MarkGeometry.swift",
        "web/src/app/icon.svg",
    ],
)
def test_generated_text_matches_the_generator(relative: str):
    """A generated file on disk must be what the generator produces today."""
    on_disk = (REPO / relative).read_text()
    if relative.endswith("markGeometry.ts"):
        assert on_disk == gen_mark.emit_ts()
    elif relative.endswith("MarkGeometry.swift"):
        assert on_disk == gen_mark.emit_swift()
    else:
        assert "prefers-color-scheme" in on_disk
        assert gen_mark.svg(gen_mark.FRAMED) in on_disk
        assert gen_mark.svg(gen_mark.FRAMELESS) in on_disk


@pytest.mark.parametrize("appearance_name", ["light", "dark", "tinted"])
def test_app_icon_matches_the_generator(appearance_name: str):
    """The shipped 1024 is the generator's output, not a design-file export.

    Compared with a tolerance because rasterisers differ at polygon edges; the
    pin is that no REGION differs, which is what a geometry change would cause.
    """
    appearance = {
        "light": gen_mark.ICON_LIGHT,
        "dark": gen_mark.ICON_DARK,
        "tinted": gen_mark.ICON_TINTED,
    }[appearance_name]
    shipped = np.asarray(
        Image.open(gen_mark.ICON_DIR / f"icon-{appearance_name}-1024.png").convert("RGB")
    ).astype(int)
    regenerated = np.asarray(gen_mark.render(appearance, 1024).convert("RGB")).astype(int)

    differing = Image.fromarray(
        ((np.abs(shipped - regenerated).max(axis=2) > 8) * 255).astype(np.uint8)
    )
    # Antialiasing differences are 1-2px lines; nothing should survive erosion.
    eroded = np.asarray(differing.filter(ImageFilter.MinFilter(5)))
    assert int((eroded > 0).sum()) == 0


def test_favicon_carries_the_three_legacy_sizes():
    ico = Image.open(REPO / "web/src/app/favicon.ico")
    assert ico.info["sizes"] == {(16, 16), (32, 32), (48, 48)}


# -------------------------------------------------------------------- tokens --


def test_mark_colours_match_the_web_design_tokens():
    css = (REPO / "web/src/app/globals.css").read_text()

    def token(name: str) -> str:
        match = re.search(rf"--{name}:\s*(#[0-9a-fA-F]{{6}})", css)
        assert match, f"--{name} not found in globals.css"
        return match.group(1).lower()

    assert gen_mark.INK == token("ink")
    assert gen_mark.WALL == token("paper")
    assert gen_mark.FLOOR == token("accent")


def test_mark_colours_match_the_ios_design_tokens():
    swift = (REPO / "ios/RoomStudioCapture/RoomStudioShared/DesignSystem/RSColor.swift").read_text()

    def token(name: str) -> str:
        match = re.search(rf"static let {name} = Color\(rsHex: 0x([0-9a-fA-F]{{6}})\)", swift)
        assert match, f"{name} not found in RSColor.swift"
        return "#" + match.group(1).lower()

    assert gen_mark.INK == token("rsInk")
    assert gen_mark.WALL == token("rsSurface")
    assert gen_mark.FLOOR == token("rsAction")
    # The icon's two tile fields are the app's own surfaces, not new colours.
    assert gen_mark.ICON_LIGHT.field == token("rsBackground")
    assert gen_mark.ICON_DARK.field == token("rsCaptureBase")


def test_no_surface_hand_authors_the_mark():
    """Each consumer must import the geometry rather than redraw it."""
    wordmark_tsx = (REPO / "web/src/components/Wordmark.tsx").read_text()
    assert "markGeometry" in wordmark_tsx

    wordmark_swift = (
        REPO / "ios/RoomStudioCapture/RoomStudioCapture/DesignSystem/Wordmark.swift"
    ).read_text()
    assert "MarkGeometry." in wordmark_swift

    # The share card has no build step, so its mark is the generator's SVG
    # pasted inline. Pin it, or it silently becomes a sixth hand-maintained copy.
    og_card = (REPO / "docs/product/og-card.html").read_text()
    assert gen_mark.svg(gen_mark.FRAMED) in og_card

    # The placeholder diamond the iOS lockup and the share card used to draw.
    for relative in (
        "web/src/components/Wordmark.tsx",
        "ios/RoomStudioCapture/RoomStudioCapture/DesignSystem/Wordmark.swift",
        "docs/product/og-card.html",
    ):
        assert "❖" not in (REPO / relative).read_text(), relative
