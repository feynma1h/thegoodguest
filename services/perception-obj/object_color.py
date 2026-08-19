"""Per-object colour, measured from the object's own gaussians (decision 0184).

A person names their furniture by colour long before they name it by size or
position — "the red chair", not "the 0.68 m chair". Every manifest object
already ships a reconstruction whose gaussians carry per-point RGB (it is why
the room renders in colour in front of the person), and nothing read it: asked
to move "the red chair", the deployed guest answered that no colours came
through in the scan at all. This module is the half of that fix that lives in
perception; the word for the colour lives with the guest's vocabulary in
api-public's scene_facts, on the 0143 precedent — perception declares what was
measured, language belongs where the guest speaks.

WHAT IS MEASURED, and what it is not. The reading is the opacity-weighted
median of the VISIBLE gaussians' base colour: this is how the piece came out
under the light that was in the room when it was scanned, not a paint chip.
A white cabinet in the reference room reads #bdbdba. The hedging that belongs
beside that is the guest's job; ours is not to launder it into something more
confident than it is.

WARRANTED, OR ABSENT — the 0143 rule again, and 0069's before it. A colour
ships only when the visible mass concentrates around its own median. Real
objects fail this often and should: mirrors (specular, so their gaussians
carry whatever they reflected), beds under patterned covers, a truncated
reconstruction whose remaining mass is half object and half the wall behind
it. Measured across the four walked rooms, 30 of 67 cached object splats are
refused, including every mirror.

STABILITY, measured rather than assumed (the 0100 hazard: an inference that is
stable only because nothing re-runs it is not stable). A colour is re-derived
on every re-drive from whichever view wins, so two views of one piece must
agree or the person's room changes colour between re-drives. Grouping the
walk rooms' per-frame observations by label and world position gives 10 pieces
read by two or more views through this gate: 8 agree on the colour family with
an RGB spread of 0.024-0.107, and the 2 that disagree are both grey-versus-
black on a piece sitting at value 0.11-0.48 — a threshold artefact in the dark
achromatic band, never a disagreement about hue. All five chromatic pieces
(one red chair, three brown doors and cabinets, one blue curtain) agree. The
consumer's naming rule is built on exactly that: hue is a name, dark grey is
not.

Clipping to the measured box (0104) was measured and is NOT done: over the
nine objects carrying a `splat_clip`, restricting the reading to the kept mass
moves it by at most 0.035 in RGB and changes no name, so the pass stays
decoupled from the clip.

Nothing here reads pixels of the room, only the reconstruction, so a person
standing in the scan cannot reach a colour: `person` is suppressed before
reconstruction (decision 0089) and no suppressed concept ever gets a splat.

Consumers: fusion.py (the post-pass), api-public's scene_facts.py (names it).
"""
from __future__ import annotations

import os

import numpy as np

# A gaussian below this opacity contributes almost nothing to what the person
# sees, so it should not vote on what they are looking at.
_MIN_OPACITY = float(os.environ.get("PERCEPTION_COLOR_MIN_OPACITY", "0.3"))

# Absolute and relative floors on the visible mass. A handful of surviving
# gaussians is not a description of an object.
_MIN_VISIBLE_POINTS = int(os.environ.get("PERCEPTION_COLOR_MIN_POINTS", "2000"))
_MIN_VISIBLE_FRACTION = float(os.environ.get("PERCEPTION_COLOR_MIN_COVERAGE", "0.25"))

# Euclidean RGB radius counted as "the same colour", and the share of visible
# mass that must fall inside it. 0.55 keeps every stable reading measured on
# the walk rooms and refuses the mottled ones; raising it to 0.65 refuses four
# more without fixing either of the two dark-band disagreements, which is why
# the gate is not tuned upward to chase them.
_SAME_COLOR_RADIUS = float(os.environ.get("PERCEPTION_COLOR_RADIUS", "0.15"))
_MIN_CONCENTRATION = float(os.environ.get("PERCEPTION_COLOR_MIN_CONCENTRATION", "0.55"))


def _weighted_median(values: np.ndarray, weights: np.ndarray) -> float:
    order = np.argsort(values, kind="stable")
    v, w = values[order], weights[order]
    cumulative = np.cumsum(w)
    return float(v[int(np.searchsorted(cumulative, cumulative[-1] / 2.0))])


def to_hex(rgb) -> str:
    return "#" + "".join(
        f"{int(round(255 * min(1.0, max(0.0, float(c))))):02x}" for c in rgb
    )


def read_object_color(colors, opacity) -> dict | None:
    """The `color` manifest block for one reconstruction, or None when the
    gaussians do not warrant one.

    `colors` is (N, 3) in [0, 1] and `opacity` is (N,) in [0, 1] — exactly
    what reproject.load_splat_appearance returns. Pure and deterministic:
    the same splat always reads the same colour.
    """
    if colors is None or opacity is None:
        return None
    c = np.asarray(colors, dtype=np.float64)
    w = np.asarray(opacity, dtype=np.float64)
    if c.ndim != 2 or c.shape[1] != 3 or w.shape[0] != c.shape[0] or c.shape[0] == 0:
        return None
    finite = np.isfinite(w) & np.all(np.isfinite(c), axis=1)
    if not finite.any():
        return None
    c, w = c[finite], w[finite]

    visible = w >= _MIN_OPACITY
    visible_points = int(visible.sum())
    visible_fraction = float(visible.mean())
    if visible_points < _MIN_VISIBLE_POINTS or visible_fraction < _MIN_VISIBLE_FRACTION:
        return None

    cv, wv = c[visible], w[visible]
    median = np.array([_weighted_median(cv[:, i], wv) for i in range(3)])
    near = np.linalg.norm(cv - median, axis=1) <= _SAME_COLOR_RADIUS
    concentration = float((wv * near).sum() / wv.sum())
    if concentration < _MIN_CONCENTRATION:
        return None

    return {
        "hex": to_hex(median),
        "concentration": round(concentration, 4),
        "visible_fraction": round(visible_fraction, 4),
        "visible_points": visible_points,
    }


def apply_object_colors(fused: list[dict], ctx) -> None:
    """Attach `color` to every fused object whose reconstruction warrants one.

    In place, over the whole object list — box-anchored, free, and unplaced
    alike. An unplaced piece is the case that most needs it: it cannot be
    moved or turned, so a colour is the only handle a person has for saying
    which one they mean.

    Never raises and never partially writes: an unreadable splat leaves that
    object exactly as it was.
    """
    get_appearance = getattr(ctx, "get_appearance", None)
    if get_appearance is None:
        return
    for obj in fused:
        uri = obj.get("splat_gcs_uri")
        if not uri or obj.get("color"):
            continue
        try:
            appearance = get_appearance(uri)
        except Exception:
            continue
        if appearance is None:
            continue
        try:
            color = read_object_color(appearance.colors, appearance.opacity)
        except Exception:
            continue
        if color is not None:
            obj["color"] = color
