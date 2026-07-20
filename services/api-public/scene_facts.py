"""Derived facts layer for conversation stage 1 (decision 0058).

`derive_scene_facts(manifest)` turns a perception manifest (manifest_version 2,
see services/perception-obj/fusion.py) into `SceneFacts` — the guest model's
ENTIRE world. The raw manifest never enters the prompt: no quaternions, no
float triples, nothing the model could do 3D arithmetic on. Grounding is
enforced by construction, not discipline.

Five fact classes (decision 0058 "Grounding"):
  - inventory with confidence tiers (from quality.frames_observed /
    cluster_spread_m)
  - pairwise center-to-center distances. Epistemics live INSIDE the strings:
    comparative/ordinal claims are freely speakable; absolute quantities are
    speakable only as server-formatted strings carrying their own framing
    ("about 1.3 m between their centers"), pre-rounded to honest precision.
    No gap/clearance phrasing exists anywhere — extents are not in the data.
  - vertical relations between centers (relative only — no floor exists)
  - provenance (where the facts came from)
  - a machine-generated limits list (what THIS scene's data cannot answer;
    capability-level truths live in guest_prompt's static charter instead)

NO orientation-derived facts: SAM 3D layout conventions are runtime-unverified
(CLAUDE.md); position-derived facts don't share that exposure.

Everything here is pure and deterministic — same manifest, same facts, byte
for byte (this also keeps the rendered facts block prompt-cacheable). The
in-memory cache is keyed (scene_id, FACTS_VERSION): manifests are immutable
once a scene is ready, and bumping FACTS_VERSION invalidates naturally.

Consumers: public_server.py (conversation routes), guest_prompt.py
(build_system_prompt renders `render_facts_block`).
"""
from __future__ import annotations

import math
import threading
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass

# Bump when the derivation or rendering logic changes meaning — recorded per
# turn (reproducibility triple: facts_version, prompt_version, model).
FACTS_VERSION = 1

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


@dataclass(frozen=True)
class InventoryItem:
    """One physical object, as the guest may speak of it.

    `name` is the disambiguated spoken name ("sofa", "first chair") —
    duplicate labels get ordinal prefixes so distance strings are unambiguous.
    """
    object_id: str
    name: str
    placed: bool
    confidence: str  # "well_observed" | "provisional" | "glimpsed"


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
    vertical_relations: tuple[str, ...]
    provenance: str
    limits: tuple[str, ...]


# ---------------------------------------------------------------------------
# Derivation
# ---------------------------------------------------------------------------

def _format_m(value: float) -> str:
    """Honest precision: one decimal of meters, never more."""
    return f"{round(value, 1):.1f}"


def _spoken_names(objects: list[dict]) -> list[str]:
    """Disambiguated names in object order: duplicate labels become
    "first chair", "second chair", … (deterministic by sorted object_id)."""
    _ORDINALS = ["first", "second", "third", "fourth", "fifth", "sixth",
                 "seventh", "eighth", "ninth", "tenth"]
    label_counts: dict[str, int] = {}
    for obj in objects:
        label = obj.get("label") or "unidentified object"
        label_counts[label] = label_counts.get(label, 0) + 1
    seen: dict[str, int] = {}
    names = []
    for obj in objects:
        label = obj.get("label") or "unidentified object"
        if label_counts[label] == 1:
            names.append(label)
        else:
            idx = seen.get(label, 0)
            seen[label] = idx + 1
            ordinal = _ORDINALS[idx] if idx < len(_ORDINALS) else f"{idx + 1}th"
            names.append(f"{ordinal} {label}")
    return names


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
    names = _spoken_names(objects)

    inventory = tuple(
        InventoryItem(
            object_id=str(obj.get("object_id") or f"obj_{i}"),
            name=names[i],
            placed=bool(obj.get("placed")),
            confidence=_confidence(obj),
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
    for item in glimpsed:
        limits.append(
            f"the {item.name} was seen but never placed — it has no position, "
            f"so no distance or height facts involve it"
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

    return SceneFacts(
        facts_version=FACTS_VERSION,
        scene_id=scene_id,
        inventory=inventory,
        distances=tuple(distances),
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
