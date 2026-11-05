"""The accept/reject arithmetic (design 4.7, decision 0354). Pure functions of
numbers: no I/O, no Claude. Thresholds are in constants.py, marked [proposed]
until calibrated on the cloud renderer.

Furniture: a render is compared with the photo inside the render's own piece
mask. Three numbers, each the median over the evidence frames:
  dl     |photo L - render L - scene offset|  (whites render lighter than photos:
         the scene offset is the lightness the finish pass fitted, so the loop
         does not darken everything to chase it)
  dab    distance in the Lab a,b plane (hue and chroma are compared exactly)
  gap    1 - IoU of the render mask's bounding box and the box's projected rectangle
An edit is accepted when none of them gets worse than the tolerance.
"""
from __future__ import annotations

import statistics
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

from . import constants as C


@dataclass(frozen=True)
class PieceScore:
    dl: float
    dab: float
    gap: float
    share: float  # render mask area / box's projected rectangle
    frames: int

    def as_json(self) -> dict:
        return {k: round(v, 3) if isinstance(v, float) else v for k, v in asdict(self).items()}


def score_piece(ws: Path, evidence: list[dict], idx: int, offset_l: float = 0.0) -> PieceScore | None:
    """Score the render in `ws/renders` of the piece drawn as mask number idx+1.
    None when no evidence frame has a usable overlap."""
    from PIL import Image
    from thegoodguest_room_look import finish_compare as fc
    from thegoodguest_room_look.shell_finish import rgb_to_lab

    want = fc._srgb(30 * (idx + 1))
    rows = []
    for e in evidence:
        rp, mp = ws / "renders" / f"frame_{e['frame']}.png", ws / "renders" / f"mask_{e['frame']}.png"
        if not (rp.exists() and mp.exists()):
            continue
        photo = Image.open(ws / "captures" / "frames" / e["file"]).convert("RGB")
        rend = Image.alpha_composite(Image.new("RGBA", Image.open(rp).size, (200, 200, 205, 255)),
                                     Image.open(rp).convert("RGBA")).convert("RGB").resize(photo.size)
        m = np.asarray(Image.open(mp).convert("RGBA").resize(photo.size, Image.NEAREST))
        mask = fc.erode((m[:, :, 3] > 200) & (np.abs(m[:, :, 0].astype(int) - want) < 5), C.MASK_ERODE_PX)
        if mask.sum() < C.MIN_MASK_PX:
            continue
        d = rgb_to_lab(np.asarray(photo, float) / 255.0)[mask].mean(0) - rgb_to_lab(np.asarray(rend, float) / 255.0)[mask].mean(0)
        ys, xs = np.nonzero(mask)
        x0, y0, x1, y1 = e["bbox"]
        ix = max(min(xs.max(), x1) - max(xs.min(), x0), 0)
        iy = max(min(ys.max(), y1) - max(ys.min(), y0), 0)
        inter = ix * iy
        union = (xs.max() - xs.min()) * (ys.max() - ys.min()) + (x1 - x0) * (y1 - y0) - inter
        rows.append((abs(float(d[0]) - offset_l), float(np.hypot(d[1], d[2])), 1.0 - (inter / union if union > 0 else 0.0),
                     float(mask.sum()) / max((x1 - x0) * (y1 - y0), 1.0)))
    if len(rows) < C.MIN_USABLE_FRAMES:
        return None
    med = [statistics.median(r[k] for r in rows) for k in range(4)]
    return PieceScore(float(med[0]), float(med[1]), float(med[2]), float(med[3]), len(rows))


def edit_accepted(new: PieceScore, best: PieceScore) -> bool:
    return bool(new.dl <= best.dl + C.TOL_DL and new.dab <= best.dab + C.TOL_DL and new.gap <= best.gap + C.TOL_BBOX_GAP)


def gain(new: PieceScore, best: PieceScore) -> float:
    return best.dl - new.dl


class LoopState:
    """Early-stop bookkeeping for one piece's edit loop."""

    def __init__(self) -> None:
        self.edits = 0
        self.rejected_in_a_row = 0
        self.small_gains = 0

    def after_edit(self, accepted: bool, gain_l: float) -> None:
        self.edits += 1
        self.rejected_in_a_row = 0 if accepted else self.rejected_in_a_row + 1
        if accepted:
            self.small_gains = self.small_gains + 1 if gain_l < C.MIN_GAIN_L else 0

    def stop_reason(self) -> str | None:
        if self.edits >= C.MAX_EDITS:
            return "edit cap"
        if self.rejected_in_a_row >= C.MAX_REJECTED_IN_A_ROW:
            return "two edits rejected in a row"
        if self.small_gains >= 2:
            return "no further gain"
        return None


def usable_first_render(s: PieceScore | None) -> str | None:
    """None when the first render is good enough to keep a model; else why not."""
    if s is None:
        return "the model never overlapped the box in any evidence frame"
    if s.gap > C.PLACEMENT_UNCERTAIN_GAP:
        return f"placement uncertain: bounding-box gap {s.gap:.2f} > {C.PLACEMENT_UNCERTAIN_GAP}"
    return None


# --- Finish ------------------------------------------------------------------------
def residual(summary: dict) -> tuple[float, dict[str, float]]:
    """(sum of |dL| over measurable regions, per-region |dL|) from finish_compare.calibrate."""
    per = {k: abs(v["delta_lab"][0]) for k, v in summary.items() if k != "casing"}
    return sum(per.values()), per


def finish_gate(before: dict, after: dict) -> tuple[bool, str]:
    """Accept a hint (group) when the residual over measurable regions falls
    by GATE_MIN_GAIN_L and no region worsens by more than GATE_MAX_REGION_WORSE_L.
    Regions measurable in only one of the two renders are not compared."""
    b_sum, b = residual(before)
    a_sum, a = residual(after)
    common = set(a) & set(b)
    if not common:
        return False, "no region measurable in both renders"
    d_sum = sum(b[k] - a[k] for k in common)
    worst = max(a[k] - b[k] for k in common)
    if d_sum < C.GATE_MIN_GAIN_L:
        return False, f"residual fell by {d_sum:.2f} L, needs {C.GATE_MIN_GAIN_L}"
    if worst > C.GATE_MAX_REGION_WORSE_L:
        return False, f"a region worsened by {worst:.2f} L, limit {C.GATE_MAX_REGION_WORSE_L}"
    return True, f"residual fell by {d_sum:.2f} L"


def wainscot_edge_ok(claimed_m: float, measured_m: float | None, baseline_m: float | None) -> tuple[bool, str]:
    """Structure overlap for the wainscot: the claimed band top vs the edge the atlases show."""
    if measured_m is None:
        return False, "no atlas edge to check the claimed band against"
    err = abs(claimed_m - measured_m)
    if err > C.GATE_WAINSCOT_EDGE_M:
        return False, f"claimed {claimed_m:.2f} m is {err:.2f} m from the atlas edge (limit {C.GATE_WAINSCOT_EDGE_M})"
    if baseline_m is not None and err > abs(baseline_m - measured_m) + 1e-9:
        return False, "no closer to the atlas edge than the measurement alone"
    return True, f"within {err:.3f} m of the atlas edge"


def clamp_calibration_step(delta: list[float]) -> list[float]:
    dl = max(-C.CALIBRATION_MAX_STEP_L, min(C.CALIBRATION_MAX_STEP_L, delta[0]))
    ab = np.array(delta[1:], float)
    n = float(np.linalg.norm(ab))
    if n > C.CALIBRATION_MAX_STEP_AB:
        ab = ab * (C.CALIBRATION_MAX_STEP_AB / n)
    return [round(dl, 1), round(float(ab[0]), 1), round(float(ab[1]), 1)]
