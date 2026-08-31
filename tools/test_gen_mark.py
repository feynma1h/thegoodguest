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
from PIL import Image, ImageDraw, ImageFilter

REPO = Path(__file__).resolve().parent.parent


# ------------------------------------------------------------------ geometry --


def test_every_master_is_the_same_drawing_in_shape():
    """Scale, band and separation vary between masters; the SHAPE does not.

    If the axis ratio or the tilt ever drifts between them, the tab icon stops
    being the same mark as the app icon at a smaller size and becomes a second
    mark that merely resembles it.
    """
    for master in gen_mark.MASTERS:
        assert master.axis_ratio == pytest.approx(1.4047, abs=0.0005), master.name
    assert gen_mark.TILT_DEG == -35.0


def test_the_pair_has_exact_180_degree_rotational_symmetry():
    """Which is what makes the geometric centre the optical centre, so no
    surface needs a fudge factor to place the mark."""
    for master in gen_mark.MASTERS:
        left, right = master.centres
        assert left[0] + right[0] == pytest.approx(gen_mark.CANVAS), master.name
        assert left[1] == pytest.approx(gen_mark.CANVAS / 2), master.name
        assert right[1] == pytest.approx(gen_mark.CANVAS / 2), master.name


def test_the_small_masters_carry_a_heavier_band_than_the_logo():
    """The whole reason a tab icon cannot use the logo master: at the logo's
    band ratio the 16px band rasterises to 0.72px and greys out."""
    logo_ratio = gen_mark.LOGO.band / gen_mark.LOGO.ink_height
    assert logo_ratio == pytest.approx(0.077, abs=0.001)
    # The icon is the logo scaled, so its ratio is unchanged.
    assert gen_mark.ICON.band / gen_mark.ICON.ink_height == pytest.approx(
        logo_ratio, abs=0.001
    )
    # Both tab masters are heavier, and 16 is heavier than 32/48.
    assert gen_mark.TAB_REG.band / gen_mark.TAB_REG.ink_height > logo_ratio
    assert (
        gen_mark.TAB_16.band / gen_mark.TAB_16.ink_height
        > gen_mark.TAB_REG.band / gen_mark.TAB_REG.ink_height
    )
    # Compared at the same MARK WIDTH, which is the only fair comparison --
    # the two masters fill their 1024 box differently. At a 16px-wide mark the
    # logo's band is a grey smear and the 16px master's is a line.
    assert gen_mark.LOGO.band * 16 / gen_mark.LOGO.ink_width == pytest.approx(
        0.72, abs=0.01
    )
    assert gen_mark.TAB_16.band * 16 / gen_mark.TAB_16.ink_width == pytest.approx(
        1.67, abs=0.01
    )
    # And as actually shipped: favicon.svg draws a 1024 viewBox at 16px.
    assert gen_mark.TAB_16.band * 16 / gen_mark.CANVAS == pytest.approx(1.62, abs=0.01)


def test_the_16px_master_opens_the_rings_further_apart():
    """At 16px two counters at the logo's separation merge into one dark
    lozenge. Opening them is the only thing that keeps both holes readable."""
    assert gen_mark.TAB_16.dx / gen_mark.TAB_16.a == pytest.approx(0.620, abs=0.002)
    for master in (gen_mark.LOGO, gen_mark.ICON, gen_mark.TAB_REG):
        assert master.dx / master.a == pytest.approx(0.538, abs=0.002), master.name


N = 1024


def _runs(row: np.ndarray) -> list[tuple[int, int]]:
    """The inked spans of one scanline, as (start, end) pixel pairs."""
    on = np.nonzero(row)[0]
    if not len(on):
        return []
    breaks = np.nonzero(np.diff(on) > 1)[0]
    starts = np.r_[on[0], on[breaks + 1]]
    ends = np.r_[on[breaks], on[-1]]
    return list(zip(starts.tolist(), ends.tolist()))


def test_the_ring_interior_is_a_real_hole():
    """A ring is outer XOR inner. Fill it nonzero instead and the mark becomes
    two solid ellipses -- the interlock, which is the whole idea, is gone.

    Asserted structurally rather than by sampling magic coordinates. Because
    both rings lean 35 degrees, the row through the mark's centre cuts FOUR
    limbs -- left ring's left, right ring's left, left ring's right, right
    ring's right -- and every one of them is a band of the same weight.
    """
    mask = np.asarray(gen_mark.mark_mask(gen_mark.LOGO, N))
    runs = _runs(mask[N // 2])
    assert len(runs) == 4, f"expected four limbs on the centre row, got {runs}"

    widths = [end - start for start, end in runs]
    assert max(widths) - min(widths) <= 1, f"limbs differ in weight: {widths}"

    # Each ring's own centre sits in a hole, which is what makes it a ring.
    for cx, cy in gen_mark.LOGO.centres:
        px = int(cx / gen_mark.CANVAS * N)
        py = int(cy / gen_mark.CANVAS * N)
        assert not mask[py, px], "a ring interior is filled -- the fill rule is wrong"


def test_the_two_rings_interlock_rather_than_cancel():
    """Where the two bands cross, the ink must SURVIVE.

    The tempting simplification -- one even-odd path over all four ellipses --
    punches holes at exactly those four crossings. This builds that wrong
    version and pins that ours has strictly more ink, and that the difference
    is small and confined to the crossings rather than spread over the mark.
    """
    n = 512
    correct = np.asarray(gen_mark.mark_mask(gen_mark.LOGO, n))

    # The wrong version: every ellipse XOR-ed into one even-odd path.
    from PIL import ImageChops as chops

    wrong = Image.new("1", (n, n), 0)
    for centre in gen_mark.LOGO.centres:
        for axes in (gen_mark.LOGO.outer, gen_mark.LOGO.inner):
            layer = Image.new("1", (n, n), 0)
            ImageDraw.Draw(layer).polygon(
                gen_mark._flatten(centre, *axes, n / gen_mark.CANVAS), fill=1
            )
            wrong = chops.logical_xor(wrong, layer)
    wrong = np.asarray(wrong)

    assert correct.sum() > wrong.sum(), "the crossings did not survive"

    # The two agree everywhere except the crossings, which are a few percent of
    # the ink -- if this grew, the two constructions would be diverging broadly
    # rather than only where the bands meet.
    lost = correct & ~wrong
    assert not (wrong & ~correct).any(), "the wrong version inked what ours does not"
    assert 0.01 < lost.sum() / correct.sum() < 0.10, lost.sum() / correct.sum()


# ------------------------------------------------------------------- outputs --


@pytest.mark.parametrize(
    "relative",
    [
        "web/src/components/markGeometry.ts",
        "ios/TheGoodGuestCapture/TheGoodGuestCapture/DesignSystem/MarkGeometry.swift",
        "web/src/app/icon.svg",
        "web/src/components/wordmarkGeometry.ts",
        "ios/TheGoodGuestCapture/TheGoodGuestCapture/DesignSystem/WordmarkGeometry.swift",
    ],
)
def test_generated_text_matches_the_generator(relative: str):
    """A generated file on disk must be what the generator produces today."""
    on_disk = (REPO / relative).read_text()
    # Order matters: "wordmarkGeometry.ts" ends with "markGeometry.ts".
    if relative.endswith("wordmarkGeometry.ts"):
        assert on_disk == gen_mark.emit_wordmark_ts(gen_mark.load_wordmark())
    elif relative.endswith("WordmarkGeometry.swift"):
        assert on_disk == gen_mark.emit_wordmark_swift(gen_mark.load_wordmark())
    elif relative.endswith("markGeometry.ts"):
        assert on_disk == gen_mark.emit_ts()
    elif relative.endswith("MarkGeometry.swift"):
        assert on_disk == gen_mark.emit_swift()
    else:
        assert on_disk == gen_mark.icon_svg() + "\n"


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

    assert gen_mark.BRAND_INK == token("accent")
    assert gen_mark.LIGHT_GROUND == token("paper")
    assert gen_mark.DARK_GROUND == token("ink")


def test_mark_colours_match_the_ios_design_tokens():
    swift = (REPO / "ios/TheGoodGuestCapture/TheGoodGuestShared/DesignSystem/RSColor.swift").read_text()

    def token(name: str) -> str:
        match = re.search(rf"static let {name} = Color\(rsHex: 0x([0-9a-fA-F]{{6}})\)", swift)
        assert match, f"{name} not found in RSColor.swift"
        return "#" + match.group(1).lower()

    assert gen_mark.BRAND_INK == token("rsAction")
    assert gen_mark.REVERSE_INK == token("rsOnDark")
    # The icon's two tile fields are the app's own surfaces, not new colours.
    assert gen_mark.ICON_LIGHT.field == token("rsSurface")
    assert gen_mark.ICON_DARK.field == token("rsInk")


def test_no_surface_hand_authors_the_mark():
    """Each consumer must import the geometry rather than redraw it."""
    wordmark_tsx = (REPO / "web/src/components/Wordmark.tsx").read_text()
    assert "markGeometry" in wordmark_tsx

    wordmark_swift = (
        REPO / "ios/TheGoodGuestCapture/TheGoodGuestCapture/DesignSystem/Wordmark.swift"
    ).read_text()
    assert "MarkGeometry." in wordmark_swift

    # The share card has no build step, so its wordmark is the generator's path
    # data pasted inline. Pin it, or it silently becomes a hand-maintained copy.
    og_card = (REPO / "docs/product/og-card.html").read_text()
    wm = gen_mark.load_wordmark()
    assert gen_mark.wordmark_script_path(wm) in og_card
    for d in gen_mark.wordmark_ring_paths(wm):
        assert d in og_card

    # The placeholder diamond the iOS lockup and the share card used to draw.
    for relative in (
        "web/src/components/Wordmark.tsx",
        "ios/TheGoodGuestCapture/TheGoodGuestCapture/DesignSystem/Wordmark.swift",
        "docs/product/og-card.html",
    ):
        assert "❖" not in (REPO / relative).read_text(), relative


def test_no_surface_sets_the_mark_beside_the_name():
    """The mark IS the "oo" of the name, so a lockup of the two would print
    those two letters twice. Every surface picks one or the other.

    Checked as a string proximity rather than by reading each layout, because
    the failure mode is someone adding the name back next to an existing mark
    without knowing the rule -- which is exactly what these files used to do.
    """
    name = "The Good Guest"
    for relative in (
        "web/src/components/Wordmark.tsx",
        "web/src/components/SiteNav.tsx",
        "web/src/app/room/page.tsx",
        "ios/TheGoodGuestCapture/TheGoodGuestCapture/DesignSystem/Wordmark.swift",
        "ios/TheGoodGuestCapture/TheGoodGuestCapture/Home/HomeView.swift",
        "ios/TheGoodGuestCapture/TheGoodGuestCapture/Gating/UnsupportedDeviceView.swift",
    ):
        text = (REPO / relative).read_text()
        # Strip comments and docstrings, which discuss the rule by name.
        code = "\n".join(
            line
            for line in text.splitlines()
            if not line.lstrip().startswith(("*", "//", "///", "/*"))
        )
        draws_mark = "<Mark" in code or "Mark(height:" in code
        # DEFINING the name is what the one-file seam is for; what the rule
        # forbids is RENDERING it. An aria-label is not a rendering.
        renders_name = any(
            token in code
            for token in (
                "Text(RSBrand.name)",
                f'Text("{name}")',
                ">{BRAND_NAME}",
                "{BRAND_NAME}<",
                f">{name}<",
            )
        )
        assert not (draws_mark and renders_name), (
            f"{relative} draws the mark AND renders the name -- see the rule in "
            "web/src/components/Wordmark.tsx"
        )


# ------------------------------------------------------------------ wordmark --


def test_the_wordmarks_oo_is_the_mark_itself():
    """Not a shape that resembles it -- the same shape, uniformly scaled.

    This is what makes the iOS splash's carry a scale-and-translate rather than
    a shape interpolation, and it is why the two may never be set side by side.
    """
    wm = gen_mark.load_wordmark()
    # Every ratio that defines the mark survives the placement.
    a = gen_mark.LOGO.a * wm.oo_scale
    b = gen_mark.LOGO.b * wm.oo_scale
    band = gen_mark.LOGO.band * wm.oo_scale
    dx = gen_mark.LOGO.dx * wm.oo_scale
    assert a / b == pytest.approx(gen_mark.LOGO.axis_ratio)
    assert dx / a == pytest.approx(gen_mark.LOGO.dx / gen_mark.LOGO.a)
    assert band / a == pytest.approx(gen_mark.LOGO.band / gen_mark.LOGO.a)


def test_the_oo_lands_at_the_scripts_own_stroke_weight():
    """The mark IS the oo at its natural size -- nothing was rescaled to fit.

    The traced script's monoline stroke is 6.2 units. A mark placed at the ring
    pair's measured height carries a band of the same weight, which is why the
    substitution needed no adjustment to the lettering around it.
    """
    wm = gen_mark.load_wordmark()
    band = gen_mark.LOGO.band * wm.oo_scale
    assert band == pytest.approx(6.2, abs=0.05)


def test_the_lettering_survives_the_cut():
    """The cut removes the ring outlines and NOTHING else.

    15 contours in, 13 out: contour 1 becomes two (the g side and the d side),
    and the three counters the old oo carried are gone with it.
    """
    wm = gen_mark.load_wordmark()
    assert len(wm.script) == 13

    # The lettering still spans the full width -- a mis-cut would truncate it.
    xs = [p[0] for start, segs in wm.script for p in [start] + [s[2] for s in segs]]
    assert min(xs) < 5
    assert max(xs) > wm.width - 5


def test_the_wordmark_is_never_the_mark_at_chrome_size():
    """A guard on the one number that makes this artwork illegible.

    The script's x-height is 16% of its box, so a wordmark set at a chrome size
    has an x-height of about 3px. Every surface that sets it must clear the
    design file's 8px floor, which puts the minimum height near 50.
    """
    wm = gen_mark.load_wordmark()
    floor = 8.0 * wm.height / wm.x_height
    assert floor == pytest.approx(49.2, abs=0.5)

    for relative, pattern in (
        ("web/src/lib/card/layout.ts", r'kind: "wordmark".*?height: (\d+)'),
        ("docs/product/og-card.html", r'aria-label="The Good Guest"'),
    ):
        text = (REPO / relative).read_text()
        for match in re.finditer(pattern, text, re.S):
            if match.groups():
                assert float(match.group(1)) >= floor, relative


# ------------------------------------------------------------- the app's name --


def _pbxproj() -> str:
    return (REPO / "ios/TheGoodGuestCapture/TheGoodGuestCapture.xcodeproj/project.pbxproj").read_text()


def test_the_home_screen_name_is_the_products_name():
    """What sits under the icon, which is the most-seen brand surface there is.

    Without CFBundleDisplayName the app falls through to TARGET_NAME and the
    Home Screen reads "TheGoodGuestCapture" -- which it did, unnoticed, past every
    "the name lives in N places" claim in the repo. The key cannot read
    RSBrand.name, so this is what keeps the two in step.
    """
    swift = (
        REPO / "ios/TheGoodGuestCapture/TheGoodGuestCapture/DesignSystem/Wordmark.swift"
    ).read_text()
    name = re.search(r'static let name = "([^"]+)"', swift).group(1)

    shown = re.findall(r'INFOPLIST_KEY_CFBundleDisplayName = "([^"]+)"', _pbxproj())
    # Both configurations of the app, plus both of the Live Activity extension,
    # whose own name is what the Lock Screen calls the activity.
    assert shown.count(name) == 2, f"app display name is {shown}, expected {name} twice"


def test_the_bundle_identifier_is_untouched():
    """The stand-in stays wherever it is an IDENTIFIER rather than a name.

    Changing this is a different app: it breaks the installed build's identity,
    the keychain access group, and every existing room's ownership. The Home
    Screen name is the presentation, and that is what was fixed instead.
    """
    assert "PRODUCT_BUNDLE_IDENTIFIER = com.thegoodguest.TheGoodGuestCapture;" in _pbxproj()


def test_no_user_visible_string_carries_the_old_stand_in():
    """The permission dialog is the first sentence the product says to anyone.

    It said "TheGoodGuest captures your room with ARKit" past the name landing.
    Every INFOPLIST_KEY_* value is user-visible somewhere -- a permission
    dialog, Settings, the Home Screen, the Lock Screen -- so none may carry it.
    """
    for key, value in re.findall(r"(INFOPLIST_KEY_\w+) = \"([^\"]+)\"", _pbxproj()):
        assert "roomstudio" not in value.lower(), f"{key} = {value}"
