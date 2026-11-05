"""Render-equality helper."""

import io

import numpy as np
from image_diff import diff_dirs, diff_images
from PIL import Image


def png(arr) -> bytes:
    b = io.BytesIO()
    Image.fromarray(np.asarray(arr, np.uint8), "RGBA").save(b, "PNG")
    return b.getvalue()


def flat(v, size=(10, 10)):
    a = np.full((*size, 4), 255, np.uint8)
    a[..., :3] = v
    return a


def test_identical_images():
    assert diff_images(png(flat(50)), png(flat(50))).identical


def test_difference_is_measured_per_channel_level():
    a, b = flat(50), flat(50)
    b[:5, :, :3] = 70  # half the pixels differ by 20 levels
    d = diff_images(png(a), png(b), "x")
    assert not d.identical
    assert d.mean == 10.0 and d.over_level == 0.5


def test_diff_dirs_compares_shared_names_only(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    (tmp_path / "a" / "one.png").write_bytes(png(flat(1)))
    (tmp_path / "b" / "one.png").write_bytes(png(flat(1)))
    (tmp_path / "a" / "only_a.png").write_bytes(png(flat(1)))
    assert [d.name for d in diff_dirs(tmp_path / "a", tmp_path / "b")] == ["one.png"]
