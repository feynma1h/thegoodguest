"""The privacy gate for pixels (decision 0352). Every picture that can reach
Claude is built here, and only here.

  photo_crop   a crop around one boxed object: person pixels blacked out BEFORE
               the crop is shrunk, refused when the mask is unknown or the crop
               is mostly person, long side capped so text cannot be read.
  render_image our own render of the model (not a photo; capped for size).
  atlas_image  a rectified wall/floor atlas: a median over frames, so people
               and furniture have dropped out; the finish pass sends these only.

Nothing is written to disk and nothing is logged here.
"""
from __future__ import annotations

import io

import numpy as np
from PIL import Image as PILImage

from . import constants as C
from .client import Image


def _png(im: PILImage.Image) -> bytes:
    buf = io.BytesIO()
    im.save(buf, format="PNG", optimize=False)
    return buf.getvalue()


def _cap(im: PILImage.Image, side: int) -> PILImage.Image:
    im = im.copy()
    im.thumbnail((side, side), PILImage.LANCZOS)
    return im


def resize_mask(mask: np.ndarray, size: tuple[int, int]) -> np.ndarray:
    """Nearest-neighbour resize of a bool mask to (width, height)."""
    if mask.shape == (size[1], size[0]):
        return mask
    return np.asarray(PILImage.fromarray(mask.astype(np.uint8) * 255).resize(size, PILImage.NEAREST)) > 127


def photo_crop(photo: PILImage.Image, bbox: tuple[float, float, float, float], turn: int,
               person: np.ndarray | None, label: str = "") -> Image | None:
    """-> a masked, capped photo Image, or None when the frame must not be used."""
    if person is None:
        return None
    x0, y0, x1, y1 = bbox
    pw, ph = (x1 - x0) * C.CROP_PAD, (y1 - y0) * C.CROP_PAD
    box = (int(max(x0 - pw, 0)), int(max(y0 - ph, 0)), int(min(x1 + pw, photo.width)), int(min(y1 + ph, photo.height)))
    if box[2] - box[0] < 16 or box[3] - box[1] < 16:
        return None
    rgb = np.array(photo.convert("RGB").crop(box))
    if person.shape == (1, 1):  # "assume no people": the local fake-client run only
        hit = np.zeros(rgb.shape[:2], bool)
    else:
        hit = resize_mask(person, photo.size)[box[1]:box[3], box[0]:box[2]]
    if hit.mean() > C.MAX_SUPPRESSED_SHARE:
        return None
    rgb[hit] = C.SUPPRESSED_FILL_RGB
    im = PILImage.fromarray(rgb)
    if turn:
        im = im.rotate(turn, expand=True)
    im = _cap(im, C.PHOTO_CROP_MAX_SIDE_PX)
    return Image("photo", _png(im), im.width, im.height, label, masked=True)


def render_image(render_rgb: PILImage.Image, label: str = "") -> Image:
    im = _cap(render_rgb.convert("RGB"), C.PHOTO_CROP_MAX_SIDE_PX)
    return Image("render", _png(im), im.width, im.height, label)


def atlas_image(lab: np.ndarray, label: str, flip_v: bool = False) -> Image:
    """A Lab atlas as a PNG; texels no frame saw are magenta, as in shell_atlas.save_png."""
    from thegoodguest_room_look.shell_finish import lab_to_rgb

    rgb = (lab_to_rgb(np.nan_to_num(lab, nan=0.0)) * 255).clip(0, 255).astype(np.uint8)
    rgb[~np.isfinite(lab[:, :, 0])] = (255, 0, 255)
    if flip_v:
        rgb = rgb[::-1]
    im = _cap(PILImage.fromarray(np.ascontiguousarray(rgb)), C.FINISH_IMAGE_MAX_SIDE_PX)
    return Image("atlas", _png(im), im.width, im.height, label)
