"""Derived facts layer for conversation stage 1 (decision 0058).

`derive_scene_facts(manifest)` turns a perception manifest (manifest_version 2,
see services/perception-obj/fusion.py) into `SceneFacts` — the guest model's
ENTIRE world. The raw manifest never enters the prompt: no quaternions, no
float triples, nothing the model could do 3D arithmetic on. Grounding is
enforced by construction, not discipline.

Fact classes (decision 0058 "Grounding", extended by 0096):
  - inventory with confidence tiers (from quality.frames_observed /
    cluster_spread_m), each optionally carrying a measured size
  - pairwise center-to-center distances. Epistemics live INSIDE the strings:
    comparative/ordinal claims are freely speakable; absolute quantities are
    speakable only as server-formatted strings carrying their own framing
    ("about 1.3 m between their centers"), pre-rounded to honest precision.
  - sizes and size comparisons — see SIZES below
  - clearances, as rigorous LOWER BOUNDS — see CLEARANCES below
  - vertical relations between centers (relative only — no floor exists)
  - provenance (where the facts came from)
  - a machine-generated limits list (what THIS scene's data cannot answer;
    capability-level truths live in guest_prompt's static charter instead)

NO orientation-derived facts: SAM 3D layout conventions are runtime-unverified
(CLAUDE.md); position-derived facts don't share that exposure.

SIZES (facts_version 3). Only `roomplan_box` measurements are spoken as a
size, and only at box confidence high/medium. Two measured reasons:

  - Splat-derived extents are not size truth. In the reference manifest a real
    meter-scale rug ships `extent_m_sorted` of 0.46 x 0.29 x 0.005 (the
    textile scale collapse, decision 0075), and every splat extent is exposed
    to visible-region truncation, an open reconstruction defect (0080).
    A confident wrong size is worse than no size, so splat extents are size-
    silent. RoomPlan box dims own measurement truth for covered categories.
  - Low box confidence is where the labels are wrong too (the spike room's
    wardrobe arrives as a low-confidence "refrigerator"). The iOS live floor
    plan already withholds the NAME at low box confidence; withholding the
    authoritative-sounding size that would attach to that wrong name follows
    the same rule.

Both gates are unchanged from facts_version 2. What changed is WHICH size:
a measured piece now speaks its HEIGHT and its two horizontal extents, from
`roomplan_box.extent_axes_m` (decision 0143), instead of only "at its
longest". The old rule outlived its reason twice over — 0096 recorded the
`dims` triple as descending-sorted with no recoverable axis semantics, 0137
measured 31 boxes and found it is not sorted in any order with index 1 the
vertical extent, and 0143 then had perception declare the up axis rather
than leave anyone inferring it. A guest holding a high-confidence measured
height and answering "I can't say" is not being careful; it is withholding a
measurement (decision 0178).

The horizontals stay UNNAMED — RoomPlan does not fix which of X/Z is long,
so "width" and "depth" would certify more than was measured (0143). And
`extent_axes_m` is ABSENT when the box's tilt exceeds perception's threshold,
because a leaning box's vertical extent is not a height; that falls back to
the honest "at its longest", never to silence.

COLOR (facts_version 3, decision 0184). People name furniture by colour
before anything else — "the red chair". Perception measures a `color` block
per object from that object's own gaussians and ships it only when the
visible mass concentrates around one reading; this module turns the measured
hex into a word and, where the word is distinctive, into part of the piece's
NAME. Two properties of the measurement decide how far the word is trusted,
both measured across the four walked rooms (decision 0184):

  - hue is stable across views; the dark achromatic band is not. All five
    chromatic pieces read by two or more views agree on the family; the only
    two disagreements are grey-versus-black on pieces sitting at value
    0.11-0.48. So a hue, or an unambiguous black or white, may name a piece;
    a mid grey may be spoken but never used to tell two pieces apart.
  - it is the piece under the light that was in the room, not a paint chip.
    A white cabinet reads #bdbdba. The charter carries that hedge; nothing
    here rounds it up.

NAMING. Duplicate labels used to become "first chair", "second chair", and
the operator's own walk showed the cost: by the third turn the person was
saying "move the first chair" back to the product (decision 0178). Colour
replaces the ordinal wherever it distinguishes. Where nothing does, the
ordinal survives as BOOKKEEPING and is named as such in the limits, because
an index is not a referent — the person cannot tell which chair is the third
one either, so offering it as a choice is offering nothing.

CLEARANCES. Never a restated center distance — the charter forbids exactly
that, and it stays forbidden. What IS derivable is a rigorous lower bound:
for two boxes at center distance d with circumradii r = |dims|/2, no point of
one is closer than d - (r_a + r_b) to the other, whatever their yaw. Emitted
only when that bound is positive, rounded DOWN, and phrased "at least". Both
objects must be RoomPlan boxes: a truncated splat extent understates the
object, which would make the bound overstate the gap — the one direction the
error must never go.

Everything here is pure and deterministic — same manifest, same facts, byte
for byte (this also keeps the rendered facts block prompt-cacheable). The
in-memory cache is keyed (scene_id, FACTS_VERSION): manifests are immutable
once a scene is ready, and bumping FACTS_VERSION invalidates naturally.

Consumers: public_server.py (conversation routes), guest_prompt.py
(build_system_prompt renders `render_facts_block`).
"""
from __future__ import annotations

import colorsys
import math
import threading
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass

# Bump when the derivation or rendering logic changes meaning — recorded per
# turn (reproducibility triple: facts_version, prompt_version, model).
# 2: sizes, size comparisons and clearance lower bounds (decision 0096).
# 3: measured heights and horizontal extents in place of "at its longest"
#    (decisions 0143/0178), per-object colour, and colour-based naming in
#    place of ordinals (decision 0184).
FACTS_VERSION = 3

# Box confidence tiers whose dimensions may be spoken as a size. RoomPlan's
# own grading; "low" is where the label is also unreliable (see SIZES above).
_SIZE_TRUSTED_BOX_CONFIDENCE = frozenset({"high", "medium"})

# Below this, a clearance bound is not worth saying — it is inside the
# fusion pipeline's own position error and reads as false precision.
_MIN_QUOTABLE_CLEARANCE_M = 0.1

# Placed objects observed in >= this many frames with cluster spread <= the
# threshold are "well observed"; other placed objects are "provisional".
_WELL_OBSERVED_MIN_FRAMES = 3
_WELL_OBSERVED_MAX_SPREAD_M = 0.15

# Below this center-to-center distance we refuse a number: at sub-5 cm the
# fused positions' own error dominates, and "about 0.0 m" reads as nonsense.
_MIN_QUOTABLE_DISTANCE_M = 0.05

# Vertical deltas under this read as "about the same height" — quoting a
# smaller number would claim precision the fusion pipeline doesn't have.
_SAME_HEIGHT_BAND_M = 0.15

# --- Colour vocabulary (decision 0184) -------------------------------------
# Family boundaries. Deliberately coarse: the guest says "the red chair", not
# "the #880607 chair", and every qualifier ("dark", "muted") is a second
# claim the measurement does not separately support.
_COLOR_GREY_MAX_SAT = 0.18       # below this there is no hue worth naming
_COLOR_BLACK_MAX_VALUE = 0.20    # below this a piece reads black whatever its hue
_COLOR_WHITE_MIN_VALUE = 0.90

# The stricter margins a reading must clear before its word may be used to
# TELL TWO PIECES APART, as opposed to merely described. Measured (0184): the
# hue families are stable across views, and the only cross-view disagreements
# are grey-versus-black on pieces sitting either side of the black boundary —
# so a name is allowed only where the reading is not near one.
_COLOR_NAMEABLE_MIN_SAT = 0.35
_COLOR_NAMEABLE_BLACK_MAX_VALUE = 0.15
_COLOR_NAMEABLE_WHITE_MIN_VALUE = 0.92

# Words that describe a surface but do not point at one. Two grey chairs are
# not told apart by calling one of them grey.
_COLOR_NOT_A_HANDLE = frozenset({"grey", "beige"})


@dataclass(frozen=True)
class InventoryItem:
    """One physical object, as the guest may speak of it.

    `name` is the disambiguated spoken name — the plain label where it is
    unique ("sofa"), the label with its measured colour where that tells it
    from its siblings ("red chair"), and only failing both an ordinal.

    `named_by_bookkeeping` marks that last case. An ordinal is not a referent:
    the person cannot tell which chair is the third one either, so the limits
    say so and the charter forbids offering one as a choice (decision 0184).
    """
    object_id: str
    name: str
    placed: bool
    confidence: str  # "well_observed" | "provisional" | "glimpsed"
    # Server-formatted, verbatim-only size string, or None when this object
    # has no trustworthy measurement (see SIZES in the module docstring).
    # Present independently of `placed` — a RoomPlan box that failed placement
    # still measured the thing.
    size_text: str | None = None
    # The measured colour as one coarse word ("red", "grey"), or None when
    # perception refused a reading for this object (see COLOR above).
    color_word: str | None = None
    named_by_bookkeeping: bool = False


@dataclass(frozen=True)
class DistanceFact:
    """One distance statement. kind is "absolute" (framed, pre-rounded,
    verbatim-only) or "comparative" (ordinal — freely speakable)."""
    kind: str
    text: str


@dataclass(frozen=True)
class SceneFacts:
    """The guest's entire world for one scene. All strings are final —
    the prompt renders them verbatim and the charter forbids restating."""
    facts_version: int
    scene_id: str
    inventory: tuple[InventoryItem, ...]
    distances: tuple[DistanceFact, ...]
    size_comparisons: tuple[str, ...]
    clearances: tuple[str, ...]
    vertical_relations: tuple[str, ...]
    provenance: str
    limits: tuple[str, ...]


# ---------------------------------------------------------------------------
# Derivation
# ---------------------------------------------------------------------------

def _format_m(value: float) -> str:
    """Honest precision: one decimal of meters, never more."""
    return f"{round(value, 1):.1f}"


def _hex_to_rgb(value: str) -> tuple[float, float, float] | None:
    text = str(value or "").strip().lstrip("#")
    if len(text) != 6:
        return None
    try:
        return tuple(int(text[i:i + 2], 16) / 255.0 for i in (0, 2, 4))  # type: ignore[return-value]
    except ValueError:
        return None


def _color_word(rgb: tuple[float, float, float]) -> str:
    """One coarse family word for a measured colour.

    Coarse on purpose: the families are what measured stable across views
    (decision 0184), and a tone qualifier would be a second claim resting on
    the value alone — exactly where the cross-view disagreements sit.
    """
    hue, sat, value = colorsys.rgb_to_hsv(*rgb)
    degrees = hue * 360.0
    if value < _COLOR_BLACK_MAX_VALUE:
        return "black"
    if sat < _COLOR_GREY_MAX_SAT:
        return "white" if value >= _COLOR_WHITE_MIN_VALUE else "grey"
    if degrees < 50.0 or degrees >= 345.0:
        # The warm band holds most furniture, and VALUE separates it: a dark
        # warm colour is brown whatever its hue and however saturated (a
        # wooden door reads #611c02, which "red" would badly misname), while
        # a weakly saturated light one is beige rather than orange.
        if value < 0.45:
            return "brown"
        if degrees < 15.0 or degrees >= 345.0:
            return "red"
        if sat < 0.40:
            return "beige"
        return "brown" if value < 0.62 else "orange"
    if degrees < 70.0:
        return "yellow" if sat >= 0.40 else "beige"
    if degrees < 165.0:
        return "green"
    if degrees < 200.0:
        return "teal"
    if degrees < 255.0:
        return "blue"
    if degrees < 290.0:
        return "purple"
    return "pink"


def _color_reading(obj: dict) -> tuple[str, bool] | None:
    """(word, may_name) for one object's measured colour, or None.

    `may_name` is the stricter claim: this word is far enough from every
    family boundary, and specific enough, to tell this piece from a sibling
    sharing its label. A mid grey describes without pointing.
    """
    block = obj.get("color")
    if not isinstance(block, dict):
        return None
    rgb = _hex_to_rgb(block.get("hex"))
    if rgb is None:
        return None
    word = _color_word(rgb)
    _hue, sat, value = colorsys.rgb_to_hsv(*rgb)
    if word in _COLOR_NOT_A_HANDLE:
        may_name = False
    elif word == "black":
        may_name = value <= _COLOR_NAMEABLE_BLACK_MAX_VALUE
    elif word == "white":
        may_name = value >= _COLOR_NAMEABLE_WHITE_MIN_VALUE
    else:
        may_name = sat >= _COLOR_NAMEABLE_MIN_SAT
    return word, may_name


def _spoken_names(
    objects: list[dict], colors: list[tuple[str, bool] | None]
) -> tuple[list[str], list[bool]]:
    """Names in object order, plus a flag per name marking the ones that are
    bookkeeping rather than something a person could say.

    A unique label is its own name. Duplicate labels are told apart by colour
    where a colour word is distinctive AND unique within that label's group —
    "the red chair" is how the person asked for it in the first place. What
    survives both is an ordinal, and the caller reports those as bookkeeping.
    """
    _ORDINALS = ["first", "second", "third", "fourth", "fifth", "sixth",
                 "seventh", "eighth", "ninth", "tenth"]
    labels = [obj.get("label") or "unidentified object" for obj in objects]
    label_counts: dict[str, int] = {}
    for label in labels:
        label_counts[label] = label_counts.get(label, 0) + 1

    # A colour only names a piece if no sibling under the same label shares it.
    handle_counts: dict[tuple[str, str], int] = {}
    for label, color in zip(labels, colors, strict=True):
        if color is not None and color[1]:
            key = (label, color[0])
            handle_counts[key] = handle_counts.get(key, 0) + 1

    names: list[str] = []
    bookkeeping: list[bool] = []
    seen: dict[str, int] = {}
    for label, color in zip(labels, colors, strict=True):
        if label_counts[label] == 1:
            names.append(label)
            bookkeeping.append(False)
            continue
        if color is not None and color[1] and handle_counts[(label, color[0])] == 1:
            names.append(f"{color[0]} {label}")
            bookkeeping.append(False)
            continue
        idx = seen.get(label, 0)
        seen[label] = idx + 1
        ordinal = _ORDINALS[idx] if idx < len(_ORDINALS) else f"{idx + 1}th"
        names.append(f"{ordinal} {label}")
        bookkeeping.append(True)
    return names, bookkeeping


def _confidence(obj: dict) -> str:
    if not obj.get("placed"):
        return "glimpsed"
    quality = obj.get("quality") or {}
    frames = quality.get("frames_observed")
    spread = quality.get("cluster_spread_m")
    well = (
        isinstance(frames, (int, float))
        and frames >= _WELL_OBSERVED_MIN_FRAMES
        and (spread is None or spread <= _WELL_OBSERVED_MAX_SPREAD_M)
    )
    return "well_observed" if well else "provisional"


def _trusted_box_dims(obj: dict) -> tuple[float, float, float] | None:
    """The object's RoomPlan box dimensions when they may be spoken as a size,
    else None. See SIZES in the module docstring for both gates."""
    box = obj.get("roomplan_box")
    if not isinstance(box, dict):
        return None
    if str(box.get("confidence") or "").lower() not in _SIZE_TRUSTED_BOX_CONFIDENCE:
        return None
    dims = box.get("dims")
    if not isinstance(dims, (list, tuple)) or len(dims) != 3:
        return None
    try:
        d = tuple(float(v) for v in dims)
    except (TypeError, ValueError):
        return None
    if any(math.isnan(v) or math.isinf(v) or v <= 0 for v in d):
        return None
    return d  # type: ignore[return-value]


def _trusted_extent_axes(obj: dict) -> tuple[float, tuple[float, float]] | None:
    """(height_m, (horizontal_a_m, horizontal_b_m)) when perception declared
    the box's up axis for this object, else None.

    Perception omits `extent_axes_m` when the box leans past its threshold
    (decision 0143) — a leaning box's vertical extent is not a height, so the
    caller falls back to the longest dimension rather than to silence.
    """
    if _trusted_box_dims(obj) is None:
        return None  # the confidence gate governs every size claim alike
    axes = (obj.get("roomplan_box") or {}).get("extent_axes_m")
    if not isinstance(axes, dict):
        return None
    horizontals = axes.get("horizontal_m")
    if not isinstance(horizontals, (list, tuple)) or len(horizontals) != 2:
        return None
    try:
        up = float(axes["up_m"])
        wide, deep = (float(v) for v in horizontals)
    except (KeyError, TypeError, ValueError):
        return None
    values = (up, wide, deep)
    if any(math.isnan(v) or math.isinf(v) or v <= 0 for v in values):
        return None
    return up, (wide, deep)


def _size_text(obj: dict, dims: tuple[float, float, float]) -> str:
    """The size claim for a measured piece.

    A declared up axis buys a height and a footprint; the two horizontals stay
    UNNAMED, because RoomPlan does not fix which of them is the width (0143).
    Without one, the honest claim is still only the longest dimension.
    """
    axes = _trusted_extent_axes(obj)
    if axes is None:
        return f"about {_format_m(max(dims))} m at its longest"
    up, (wide, deep) = axes
    return (
        f"about {_format_m(up)} m tall, and about {_format_m(wide)} m "
        f"by {_format_m(deep)} m across the floor"
    )


def _circumradius(dims: tuple[float, float, float]) -> float:
    """Half the box diagonal: no point of the box is farther than this from
    its center, under any rotation. The whole clearance bound rests on it."""
    return math.dist((0.0, 0.0, 0.0), dims) / 2.0


def _floor_to_tenth(value: float) -> str:
    """Round DOWN to 0.1 m. A clearance bound may only ever understate."""
    return f"{math.floor(value * 10) / 10:.1f}"


def _position(obj: dict) -> tuple[float, float, float] | None:
    wt = obj.get("world_transform")
    if not isinstance(wt, dict):
        return None
    pos = wt.get("position")
    if not isinstance(pos, (list, tuple)) or len(pos) != 3:
        return None
    try:
        x, y, z = (float(c) for c in pos)
    except (TypeError, ValueError):
        return None
    if any(math.isnan(c) or math.isinf(c) for c in (x, y, z)):
        return None
    return (x, y, z)


def derive_scene_facts(manifest: dict) -> SceneFacts:
    """Pure derivation: manifest (v2 dict) → SceneFacts. Deterministic —
    objects are processed in sorted-object_id order and nothing here reads
    a clock, environment, or random source."""
    scene_id = str(manifest.get("scene_id") or "")
    objects = sorted(
        (o for o in manifest.get("objects", []) if isinstance(o, dict)),
        key=lambda o: str(o.get("object_id") or ""),
    )
    colors = [_color_reading(obj) for obj in objects]
    names, bookkeeping = _spoken_names(objects, colors)

    box_dims = [_trusted_box_dims(obj) for obj in objects]

    inventory = tuple(
        InventoryItem(
            object_id=str(obj.get("object_id") or f"obj_{i}"),
            name=names[i],
            placed=bool(obj.get("placed")),
            confidence=_confidence(obj),
            size_text=(
                _size_text(obj, box_dims[i]) if box_dims[i] else None
            ),
            color_word=(colors[i][0] if colors[i] else None),
            named_by_bookkeeping=bookkeeping[i],
        )
        for i, obj in enumerate(objects)
    )

    # Placed objects with a usable position, in stable order.
    positioned: list[tuple[str, tuple[float, float, float]]] = []
    for i, obj in enumerate(objects):
        pos = _position(obj) if obj.get("placed") else None
        if pos is not None:
            positioned.append((names[i], pos))

    distances: list[DistanceFact] = []
    vertical: list[str] = []
    for a in range(len(positioned)):
        for b in range(a + 1, len(positioned)):
            (name_a, pos_a), (name_b, pos_b) = positioned[a], positioned[b]
            d = math.dist(pos_a, pos_b)
            if d < _MIN_QUOTABLE_DISTANCE_M:
                text = (
                    f"the {name_a}'s center and the {name_b}'s center are "
                    f"less than 0.1 m apart"
                )
            else:
                text = (
                    f"about {_format_m(d)} m between the {name_a}'s center "
                    f"and the {name_b}'s center"
                )
            distances.append(DistanceFact(kind="absolute", text=text))

            dy = pos_a[1] - pos_b[1]
            if abs(dy) < _SAME_HEIGHT_BAND_M:
                vertical.append(
                    f"the {name_a}'s center and the {name_b}'s center sit at "
                    f"about the same height"
                )
            else:
                higher, lower = (name_a, name_b) if dy > 0 else (name_b, name_a)
                vertical.append(
                    f"the {higher}'s center sits about {_format_m(abs(dy))} m "
                    f"higher than the {lower}'s center"
                )

    # Comparative (ordinal) facts: nearest placed neighbor per placed object.
    if len(positioned) >= 2:
        for name_a, pos_a in positioned:
            nearest = min(
                ((math.dist(pos_a, pos_b), name_b)
                 for name_b, pos_b in positioned if name_b != name_a),
                key=lambda t: (t[0], t[1]),
            )
            distances.append(DistanceFact(
                kind="comparative",
                text=f"of the placed pieces, the {name_a}'s nearest neighbor "
                     f"is the {nearest[1]}",
            ))

    # Size comparisons: ordinal, so freely speakable. Only over objects with a
    # trustworthy measurement — ranking a truncated splat against a measured
    # box would be a comparison between a fact and an artifact.
    sized = [(names[i], d) for i, d in enumerate(box_dims) if d]
    size_comparisons: list[str] = []
    if len(sized) >= 2:
        ranked = sorted(sized, key=lambda t: (-max(t[1]), t[0]))
        size_comparisons.append(
            f"of the measured pieces, the {ranked[0][0]} is the largest and "
            f"the {ranked[-1][0]} is the smallest"
        )
        size_comparisons.append(
            "largest to smallest, the measured pieces run: "
            + ", ".join(name for name, _ in ranked)
        )
    # Heights rank separately: the tallest piece is often not the largest one,
    # and comparing two spoken numbers is arithmetic the charter forbids the
    # guest — so the comparison is derived here or it cannot be made.
    tall = [
        (names[i], axes[0])
        for i, obj in enumerate(objects)
        if (axes := _trusted_extent_axes(obj)) is not None
    ]
    if len(tall) >= 2:
        by_height = sorted(tall, key=lambda t: (-t[1], t[0]))
        size_comparisons.append(
            f"of the pieces with a measured height, the {by_height[0][0]} is "
            f"the tallest and the {by_height[-1][0]} is the shortest"
        )

    # Clearance LOWER BOUNDS between measured boxes (module docstring).
    clearances: list[str] = []
    boxed_positioned = [
        (names[i], pos, d)
        for i, (obj, d) in enumerate(zip(objects, box_dims, strict=True))
        if d and obj.get("placed") and (pos := _position(obj)) is not None
    ]
    for a in range(len(boxed_positioned)):
        for b in range(a + 1, len(boxed_positioned)):
            (name_a, pos_a, dims_a) = boxed_positioned[a]
            (name_b, pos_b, dims_b) = boxed_positioned[b]
            bound = (
                math.dist(pos_a, pos_b)
                - _circumradius(dims_a)
                - _circumradius(dims_b)
            )
            if bound >= _MIN_QUOTABLE_CLEARANCE_M:
                clearances.append(
                    f"at least {_floor_to_tenth(bound)} m of clear space "
                    f"separates the {name_a} from the {name_b}"
                )

    placed_count = sum(1 for item in inventory if item.placed)
    glimpsed = [item for item in inventory if not item.placed]

    frame_count = manifest.get("frame_count")
    frames_part = (
        f"a scan of {int(frame_count)} frames"
        if isinstance(frame_count, (int, float)) and frame_count
        else "a scan"
    )
    provenance = (
        f"These facts were measured from {frames_part} of this one room. "
        f"{placed_count} piece{'s' if placed_count != 1 else ''} placed with "
        f"a measured position; {len(glimpsed)} seen but never placed."
    )

    limits: list[str] = []
    if glimpsed:
        limits.append(
            "seen but never placed, so with no position at all — no distance "
            "or height fact involves them, and not one of them can be moved, "
            "taken out, or turned: "
            + ", ".join(f"the {item.name}" for item in glimpsed)
        )
    if not inventory:
        limits.append(
            "the scan produced no recognizable objects — there is almost "
            "nothing about this room that can be answered"
        )
    elif placed_count == 0:
        limits.append(
            "nothing could be placed, so there are no distance or height "
            "facts at all"
        )
    elif placed_count == 1:
        limits.append(
            "only one piece was placed, so there are no between-things "
            "distances"
        )

    unsized = [item.name for item in inventory if item.size_text is None]
    if unsized and sized:
        limits.append(
            "nothing is measured for the size of: "
            + ", ".join(f"the {n}" for n in unsized)
            + " — no size, and no clearance involving them, can be given"
        )
    elif not sized:
        limits.append(
            "no piece in this room was measured well enough to give a size, "
            "so there are no sizes and no clearances at all"
        )
    longest_only = [
        item.name for item, obj in zip(inventory, objects, strict=True)
        if item.size_text is not None and _trusted_extent_axes(obj) is None
    ]
    if longest_only:
        limits.append(
            "for these, only the LONGEST dimension is known and which way it "
            "runs is not, so no height and no footprint: "
            + ", ".join(f"the {n}" for n in longest_only)
        )
    if sized:
        limits.append(
            "a measured piece's two across-the-floor figures are not labelled "
            "— nothing recorded which of them is the width and which the "
            "depth, so give them as they are written and never name one"
        )

    # Colour: what is measured, and what a colour reading is not.
    uncolored = [item.name for item in inventory if item.color_word is None]
    colored = [item for item in inventory if item.color_word is not None]
    if colored and uncolored:
        limits.append(
            "no colour could be read for: " + ", ".join(f"the {n}" for n in uncolored)
            + " — the scan saw them too unevenly to say, which is not the same "
            "as their being colourless"
        )
    elif not colored and inventory:
        limits.append(
            "no piece in this room read one clear colour, so there are no "
            "colours here at all — say that plainly rather than guessing"
        )

    # Bookkeeping names, and why they are not answers (decision 0184).
    unnamed: dict[str, list[str]] = {}
    for item, obj in zip(inventory, objects, strict=True):
        if item.named_by_bookkeeping:
            label = obj.get("label") or "unidentified object"
            unnamed.setdefault(label, []).append(item.name)
    if unnamed:
        limits.append(
            "these numbers are mine, not names — I keep same-named pieces "
            "apart that way: "
            + "; ".join(
                ", ".join(f'"{n}"' for n in group) for group in unnamed.values()
            )
            + ". The person cannot know which one is the third, so a number is "
            "never an answer to which of them they mean — describe the piece "
            "instead, by what it reads as, how big it is, or what it is "
            "nearest, and say plainly when none of that separates them"
        )

    return SceneFacts(
        facts_version=FACTS_VERSION,
        scene_id=scene_id,
        inventory=inventory,
        distances=tuple(distances),
        size_comparisons=tuple(size_comparisons),
        clearances=tuple(clearances),
        vertical_relations=tuple(vertical),
        provenance=provenance,
        limits=tuple(limits),
    )


# ---------------------------------------------------------------------------
# Rendering (the facts block the prompt embeds verbatim)
# ---------------------------------------------------------------------------

_CONFIDENCE_PHRASE = {
    "well_observed": "placed, well observed",
    "provisional": "placed, though observed only briefly — hold it a little loosely",
    "glimpsed": "seen, but never placed — no position exists for it",
}


def render_facts_block(facts: SceneFacts) -> str:
    """The exact text the guest reads. Deterministic; a stable byte string
    per (scene, FACTS_VERSION) so the prompt-cache breakpoint after it holds."""
    lines: list[str] = [
        f"THE FACTS (v{facts.facts_version}) — everything known about this room. "
        "Nothing outside this section exists.",
        "",
        "In this room:",
    ]
    if facts.inventory:
        lines += [
            f"- the {item.name} — {_CONFIDENCE_PHRASE[item.confidence]}"
            + (f"; {item.size_text}" if item.size_text else "")
            + (f"; reads {item.color_word}" if item.color_word else "")
            for item in facts.inventory
        ]
    else:
        lines.append("- nothing was recognized in this scan")

    absolutes = [d.text for d in facts.distances if d.kind == "absolute"]
    comparatives = [d.text for d in facts.distances if d.kind == "comparative"]
    if absolutes:
        lines += [
            "",
            "Distances between centers (speak these only in this exact wording; "
            "never restate one as a gap, clearance, or fit):",
        ]
        lines += [f"- {t}" for t in absolutes]
    if comparatives:
        lines += ["", "Which is nearest (safe to say freely):"]
        lines += [f"- {t}" for t in comparatives]
    if facts.size_comparisons:
        lines += ["", "Which is bigger (safe to say freely):"]
        lines += [f"- {t}" for t in facts.size_comparisons]
    if facts.clearances:
        lines += [
            "",
            "Clear space between pieces. These are floors, not measurements: "
            "say them only as 'at least', never as an exact gap, and never "
            "turn one into a width, a fit, or a walkway measurement:",
        ]
        lines += [f"- {t}" for t in facts.clearances]
    if facts.vertical_relations:
        lines += [
            "",
            "Height relations between centers (relative only — no floor exists "
            "in the data):",
        ]
        lines += [f"- {t}" for t in facts.vertical_relations]

    lines += ["", f"Where this came from: {facts.provenance}"]
    if facts.limits:
        lines += ["", "What this particular scan cannot answer:"]
        lines += [f"- {t}" for t in facts.limits]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Per-process cache
# ---------------------------------------------------------------------------

_CACHE_MAX_ENTRIES = 256
_cache: OrderedDict[tuple[str, int], SceneFacts] = OrderedDict()
_cache_lock = threading.Lock()


def cached_scene_facts(scene_id: str, load_manifest: Callable[[], dict]) -> SceneFacts:
    """Get-or-derive keyed (scene_id, FACTS_VERSION). `load_manifest` is only
    invoked on a miss, so a cache hit costs no GCS round-trip. Safe because a
    ready scene's manifest is immutable; bounded so a long-lived process
    can't grow without limit."""
    key = (scene_id, FACTS_VERSION)
    with _cache_lock:
        if key in _cache:
            _cache.move_to_end(key)
            return _cache[key]
    facts = derive_scene_facts(load_manifest())
    with _cache_lock:
        _cache[key] = facts
        _cache.move_to_end(key)
        while len(_cache) > _CACHE_MAX_ENTRIES:
            _cache.popitem(last=False)
    return facts
