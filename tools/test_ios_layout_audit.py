"""The layout audit's geometry, on drawn frames rather than screenshots.

Each test draws the one thing the audit has been fooled by, at a known size in
points, and checks the number that comes back. The screenshots themselves are
not in git; these pin the instrument so a change to it is measured before it
is believed (0252).
"""
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ios_layout_audit as audit  # noqa: E402

S = 3
GROUND = (244, 245, 247)
INK = (18, 26, 35)
INK2 = (74, 86, 100)
WHITE = (253, 253, 253)


def phone(w=402, h=874, s=S):
    a = np.empty((h * s, w * s, 3), np.uint8)
    a[:] = GROUND
    # The status bar: the time on the left, the battery on the right.
    box(a, 57, 26, 80, 39, INK, s)
    box(a, w - 62, 26, w - 36, 39, INK, s)
    return a


def box(a, x0, y0, x1, y1, colour, s=S):
    a[round(y0 * s):round(y1 * s), round(x0 * s):round(x1 * s)] = colour


def pill(a, x0, y0, x1, y1, colour, s=S):
    """A capsule: flat top and bottom, round ends."""
    h, w = a.shape[:2]
    ys, xs = np.mgrid[0:h, 0:w] / s
    r = (y1 - y0) / 2
    cy = (y0 + y1) / 2
    inside = (ys >= y0) & (ys < y1) & (
        ((xs >= x0 + r) & (xs < x1 - r))
        | ((xs - (x0 + r)) ** 2 + (ys - cy) ** 2 < r * r)
        | ((xs - (x1 - r)) ** 2 + (ys - cy) ** 2 < r * r))
    a[inside] = colour


def save(tmp_path, a, name="frame"):
    p = tmp_path / f"{name}.png"
    Image.fromarray(a).save(p)
    return p


@pytest.mark.parametrize("w,h,s,inset,col", [
    (402, 874, 3, 34, 16),     # iPhone 17 Pro
    (390, 844, 3, 34, 16),     # iPhone 17e: the previous version crashed here
    (440, 956, 3, 34, 16),     # iPhone 17 Pro Max
    (375, 667, 2, 0, 16),      # iPhone SE: a home button, so no indicator inset
    (1032, 1376, 2, 20, 196),  # iPad Pro 13-inch: the column centres at 640
])
def test_the_frame_column_and_safe_area_are_read_from_the_image(tmp_path, w, h, s, inset, col):
    a = phone(w, h, s)
    box(a, col, 120, col + 180, 150, INK, s)
    pill(a, col, h - inset - 4 - 60, w - col, h - inset - 4, INK, s)
    r = audit.measure(save(tmp_path, a))
    f = r["frame"]
    assert (f.pt(f.W), f.pt(f.H), f.bottom_inset) == (w, h, inset)
    assert audit.column(f) == col
    b = r["button"]
    assert b["bottom_up"] - f.bottom_inset == pytest.approx(4, abs=0.5)
    assert b["left"] == pytest.approx(col, abs=0.5)
    assert b["right_in"] == pytest.approx(col, abs=0.5)


@pytest.mark.parametrize("under,colour,expected", [
    (None, None, "-"), ("quiet", INK, "q"), ("caption", INK2, "c")])
def test_what_sits_under_the_pill_is_told_by_its_ink(tmp_path, under, colour, expected):
    a = phone()
    bottom = 874 - 90
    pill(a, 16, bottom - 60, 386, bottom, INK)
    box(a, 150, bottom - 38, 250, bottom - 24, WHITE)       # its label
    if under:
        box(a, 160, bottom + 18, 240, bottom + 30, colour)
    b = audit.measure(save(tmp_path, a))["button"]
    assert b["under"] == expected
    assert b["bottom_up"] == pytest.approx(90, abs=0.5)
    assert b["height"] == pytest.approx(60, abs=0.5)


def test_a_filled_button_in_the_content_is_not_the_pinned_one(tmp_path):
    # Account's sign-in pills are filled and full width, high in the content.
    a = phone()
    pill(a, 16, 250, 386, 300, (0, 0, 0))
    assert audit.measure(save(tmp_path, a))["button"] is None


def test_the_bar_is_its_items_in_their_slots(tmp_path):
    a = phone()
    box(a, 31, 75, 40, 94, INK)        # a back chevron, left slot
    box(a, 341, 75, 374, 94, INK)      # an account button, right slot
    box(a, 16, 120, 268, 152, INK)     # the title under it
    r = audit.measure(save(tmp_path, a))
    assert r["frame"].pt(r["bar_px"]) == pytest.approx(84.5, abs=0.5)
    assert r["frame"].pt(r["title_px"]) == pytest.approx(120, abs=0.5)


def test_a_title_that_has_moved_up_into_the_bars_place_is_not_a_bar(tmp_path):
    # What deletion's last states do: the bar drops out and the title lands
    # within 3pt of where the bar's items sit.
    a = phone()
    box(a, 21, 71, 90, 92, INK)
    r = audit.measure(save(tmp_path, a))
    assert r["bar_px"] is None
    assert r["frame"].pt(r["title_px"]) == pytest.approx(71, abs=0.5)


def test_a_cards_shadow_is_not_its_margin(tmp_path):
    # A card's fill is ~9 levels lighter than the ground and its shadow up to 8
    # darker. Measured on home, the shadow that matters is the band under each
    # card: ~8 dark right across the screen between cards, and only ~1 in the
    # edge strips the ground is sampled from. Read in either direction at one
    # threshold, that band's left end became the margin.
    a = phone()
    for top in (200, 300, 400):
        box(a, 16, top, 386, top + 84, WHITE)
        box(a, 2, top + 84, 8, top + 100, (243, 244, 246))
        box(a, 8, top + 84, 394, top + 100, (236, 237, 239))
        box(a, 394, top + 84, 400, top + 100, (243, 244, 246))
    f = audit.Frame(save(tmp_path, a))
    assert audit.margin(f, f.px(150), f.px(560)) == pytest.approx(16, abs=0.4)


def test_a_frame_that_is_blank_or_still_fading_in_is_unsettled(tmp_path):
    blank = phone()
    f = audit.Frame(save(tmp_path, blank, "blank"))
    assert audit.unsettled(f, audit.status_bar(f)).startswith("blank")

    faded = phone()
    grey = tuple(round(0.4 * i + 0.6 * g) for i, g in zip(INK, GROUND))
    box(faded, 20, 120, 300, 150, grey)
    f = audit.Frame(save(tmp_path, faded, "faded"))
    assert audit.unsettled(f, audit.status_bar(f)).startswith("faded")

    terracotta = phone()
    box(terracotta, 150, 380, 250, 420, (192, 77, 62))   # the splash's mark alone
    f = audit.Frame(save(tmp_path, terracotta, "mark"))
    assert audit.unsettled(f, audit.status_bar(f)) is None


def test_the_home_screen_is_not_mistaken_for_the_app(tmp_path):
    # The first launch after an install photographed the home screen: icons on
    # a wallpaper, with ink enough to measure.
    a = phone()
    a[:, :] = (52, 90, 140)
    for y in range(120, 700, 90):
        for x in range(30, 380, 90):
            box(a, x, y, x + 60, y + 60, (240, 240, 240))
    f = audit.Frame(save(tmp_path, a, "springboard"))
    assert audit.unsettled(f, audit.status_bar(f), ordinary=True).startswith("not the app")
    dusk = phone()
    dusk[:, :] = (13, 20, 28)
    box(dusk, 16, 120, 386, 460, (18, 27, 37))
    box(dusk, 16, 480, 300, 520, (238, 242, 246))
    f = audit.Frame(save(tmp_path, dusk, "dusk"))
    assert audit.unsettled(f, audit.status_bar(f), ordinary=True) is None


def test_an_ipads_resize_grip_is_not_a_line_under_the_pill(tmp_path):
    # iPadOS draws a window's resize grip in its bottom corner, beside the
    # pinned bar; it read as a caption under every lone pill.
    w, h, s = 1032, 1376, 2
    a = phone(w, h, s)
    pill(a, 196, h - 20 - 4 - 60, w - 196, h - 20 - 4, INK, s)
    box(a, w - 20, h - 26, w - 6, h - 22, INK, s)
    b = audit.measure(save(tmp_path, a))["button"]
    assert b["under"] == "-"
    assert b["bottom_up"] - 20 == pytest.approx(4, abs=0.5)
