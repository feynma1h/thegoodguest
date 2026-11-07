"""The geometry kernel: overlap, gaps, polygons and the floor grid."""
import math

import numpy as np
import pytest

from thegoodguest_room_guide.geometry import (
    Box, FloorGrid, box_inside_polygon, clearance, flood, footprint_gap, footprint_penetration,
    largest_open_rectangle, penetration, point_in_polygon, widest_path,
)

SQUARE = np.array([[-2.0, -1.5], [-2.0, 1.5], [2.0, 1.5], [2.0, -1.5]])


def box(x, z, sx, sz, yaw=0.0, y0=0.0, y1=1.0):
    return Box(x, z, sx / 2, sz / 2, yaw, y0, y1)


def test_front_follows_the_viewers_yaw_convention():
    assert box(0, 0, 1, 1, yaw=0).front == pytest.approx((0, 1))
    assert box(0, 0, 1, 1, yaw=math.pi / 2).front == pytest.approx((1, 0))
    assert box(0, 0, 1, 1, yaw=math.pi / 2).across == pytest.approx((0, -1))


def test_axis_aligned_overlap_depth():
    a, b = box(0, 0, 1, 1), box(0.9, 0, 1, 1)
    assert footprint_penetration(a, b) == pytest.approx(0.1)
    assert footprint_penetration(a, box(1.2, 0, 1, 1)) < 0


def test_rotated_boxes_that_only_look_close_do_not_overlap():
    a = box(0, 0, 1, 1)
    diamond = box(1.25, 0, 1, 1, yaw=math.pi / 4)   # its near corner is 1.25 - 0.707 from centre
    assert footprint_penetration(a, diamond) < 0
    assert footprint_gap(a, diamond) == pytest.approx(1.25 - math.sqrt(0.5) - 0.5, abs=1e-6)


def test_height_ranges_separate_a_shelf_from_what_stands_under_it():
    desk_top = box(0, 0, 1.2, 0.6, y0=0.70, y1=0.74)
    stool = box(0, 0, 0.4, 0.4, y0=0.0, y1=0.45)
    assert footprint_penetration(desk_top, stool) > 0
    assert penetration(desk_top, stool) < 0


def test_gap_between_parallel_boxes():
    assert footprint_gap(box(0, 0, 1, 1), box(2, 0, 1, 1)) == pytest.approx(1.0)
    assert footprint_gap(box(0, 0, 1, 1), box(0.5, 0, 1, 1)) == 0.0


def test_point_in_polygon_and_containment():
    pts = np.array([[0, 0], [2.5, 0], [-1.99, 1.49]])
    assert point_in_polygon(pts, SQUARE).tolist() == [True, False, True]
    assert box_inside_polygon(box(0, 0, 1, 1), SQUARE)
    assert not box_inside_polygon(box(1.8, 0, 1, 1), SQUARE)
    assert box_inside_polygon(box(1.505, 0, 1, 1), SQUARE, tol=0.01)


def test_containment_catches_a_reflex_corner_poking_in():
    ell = np.array([[0, 0], [0, 4], [2, 4], [2, 2], [4, 2], [4, 0]])   # an L
    assert box_inside_polygon(box(1, 1, 1.8, 1.8), ell)
    assert not box_inside_polygon(box(2.5, 2.5, 2.4, 2.4), ell)


def test_widest_path_through_a_doorway():
    grid = FloorGrid.over(SQUARE, cell=0.05)
    # A wall across the room with a 0.8 m gap in the middle.
    blockers = [box(0, -0.9, 0.1, 1.2), box(0, 1.0, 0.1, 1.0)]
    clear = clearance(grid, blockers, SQUARE)
    left = grid.inside & (grid.points[:, 0] < -1.5)
    right = grid.inside & (grid.points[:, 0] > 1.5)
    w = widest_path(clear, left, right, grid.shape)
    gap = (1.0 - 0.5) - (-0.9 + 0.6)          # from the lower wall's top to the upper wall's bottom
    assert w == pytest.approx(gap, abs=0.06)


def test_flood_stops_at_a_closed_wall():
    grid = FloorGrid.over(SQUARE, cell=0.1)
    clear = clearance(grid, [box(0, 0, 0.2, 3.2)], SQUARE)
    passable = clear > 0.05
    left = grid.inside & (grid.points[:, 0] < -1.5)
    reached = flood(left, passable, grid.shape)
    assert not np.any(reached & (grid.points[:, 0] > 0.5))


def test_largest_open_rectangle():
    free = np.ones((4, 5), dtype=bool)
    free[1, 2] = False
    assert largest_open_rectangle(free.ravel(), (4, 5)) == 10   # rows 2-3, all five columns
