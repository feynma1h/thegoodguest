"""The shapes of Claude's answers, over the closed vocabularies, and the code
that validates them (decision 0351).

Structured outputs require closed objects (no free-keyed maps), so two places
that the spec file allows free keys in are arrays here and are folded back into
the spec shape by `spec_from_answer`: material names (`materials` is a list of
named materials) and a texture's pattern numbers (`p` is a list of {k, v}). An
answer is never trusted because the API shaped it: every answer is validated in
code (types, enums, ranges, the package's own validators), and a value outside
the vocabulary or range is rejected, not clamped.
"""
from __future__ import annotations

import numpy as np
from thegoodguest_room_look.finish_hints import HintsError, parse_hints
from thegoodguest_room_look.furniture_geometry import corners, part_obb
from thegoodguest_room_look.furniture_models import PART_KINDS, validate_spec

from . import constants as C

TEX_KINDS = ("quilt", "wood", "weave", "lattice", "ribbon", "stripe", "grid")
PLACE_RULES = ("floor", "wall", "on", "over")
MAX_PARTS = 60

_num = {"type": "number"}
_str = {"type": "string"}
_hex = {"type": "string", "pattern": "^#[0-9a-fA-F]{6}$"}
_vec3 = {"type": "array", "items": _num}
_pairs = {"type": "array", "items": {"type": "array", "items": _num}}


def _obj(props: dict, required: list[str]) -> dict:
    return {"type": "object", "properties": props, "required": required, "additionalProperties": False}


_PART = _obj({
    "kind": {"type": "string", "enum": list(PART_KINDS)}, "mat": _str, "name": _str,
    "at": _vec3, "rot": _vec3, "size": _vec3, "bevel": _num, "r": _num, "r3": _vec3, "rTop": _num, "h": _num,
    "seg": _num, "profile": _pairs, "path": {"type": "array", "items": _vec3}, "closed": {"type": "boolean"},
    "outline": _pairs, "depth": _num, "w": _num, "hmin": _num, "hmax": _num, "tmin": _num, "tmax": _num,
    "mats": {"type": "array", "items": _str}, "seed": _num, "folds": _num, "amp": _num, "hemH": _num, "hemOff": _num,
    "uvSwap": {"type": "boolean"}, "noShadow": {"type": "boolean"},
}, ["kind", "mat", "name"])

_MATERIAL = _obj({
    "name": _str, "color": _hex, "rough": _num, "metal": _num, "clearcoat": _num, "opacity": _num,
    "double": {"type": "boolean"}, "emissive": _hex, "emissive_intensity": _num, "bump": _num,
    "tex": _obj({
        "kind": {"type": "string", "enum": list(TEX_KINDS)}, "tile_m": _num, "palette": {"type": "array", "items": _hex},
        "seed": _num, "p": {"type": "array", "items": _obj({"k": _str, "v": _num}, ["k", "v"])},
    }, ["kind"]),
}, ["name", "color"])

SPEC_PROPS = {
    "label": _str, "note": _str,
    "materials": {"type": "array", "items": _MATERIAL},
    "parts": {"type": "array", "items": _PART},
    "place": _obj({"rule": {"type": "string", "enum": list(PLACE_RULES)}, "target": _str}, ["rule"]),
}
SPEC_SCHEMA = _obj(SPEC_PROPS, ["label", "materials", "parts"])
CRITIQUE_SCHEMA = _obj({
    "done": {"type": "boolean"}, "reason": _str, "differences": {"type": "array", "items": _str},
    "spec": SPEC_SCHEMA,
}, ["done", "reason"])

FINISH_SCHEMA = _obj({
    "baseboard": _obj({"present": {"type": "boolean"}, "hex": _hex, "height_m": _num}, ["present"]),
    "wainscot": _obj({"height_m": _num, "tile_u_m": _num, "tile_v_m": _num, "joint": {"type": "string", "enum": ["light", "dark"]}}, ["height_m"]),
    "floor": _obj({"slab_u_m": _num, "slab_v_m": _num}, ["slab_u_m", "slab_v_m"]),
    "door": _obj({"casing": _str, "panels": _pairs}, []),
    "window": _obj({"casing": _str, "glass_hex": _hex}, []),
    "evidence": {"type": "array", "items": _obj({"claim": _str, "seen": {"type": "string", "maxLength": 200}}, ["claim", "seen"])},
}, ["evidence"])


class AnswerError(ValueError):
    """An answer that does not fit the vocabulary; the message is shown back to Claude."""


def _drop_none(d: dict) -> dict:
    return {k: v for k, v in d.items() if v is not None}


def spec_from_answer(ans: dict, box_id: str, box_size: list[float]) -> dict:
    """Fold a schema-shaped answer into the spec file shape the package reads."""
    mats = {}
    names = [m.get("name") for m in ans.get("materials", [])]
    if len(set(names)) != len(names):
        raise AnswerError("material names must be unique")
    for m in ans.get("materials", []):
        m = _drop_none(dict(m))
        name = m.pop("name")
        tex = m.get("tex")
        if tex:
            tex = _drop_none(dict(tex))
            if "p" in tex:
                tex["p"] = {e["k"]: e["v"] for e in tex["p"]}
            m["tex"] = tex
        mats[name] = m
    parts = []
    for p in ans.get("parts", []):
        p = _drop_none(dict(p))
        if "r3" in p:
            r3 = p.pop("r3")
            if p.get("kind") == "sphere":
                p["r"] = r3
        parts.append(p)
    spec = {"key": box_id, "object": box_id, "label": ans.get("label", box_id), "revision": 1,
            "box_dims": [round(float(x), 4) for x in box_size], "materials": mats, "parts": parts}
    if ans.get("note"):
        spec["note"] = ans["note"][:600]
    if ans.get("place"):
        spec["place"] = _drop_none(dict(ans["place"]))
    return spec


def spec_extent(spec: dict) -> tuple[np.ndarray, np.ndarray]:
    """Axis-aligned bounds of all parts in the piece frame, rotations included."""
    pts = np.vstack([corners(part_obb(p, np.zeros(3), 0.0)) for p in spec["parts"]])
    return pts.min(0), pts.max(0)


def check_spec(spec: dict, box_size: list[float], other_ids: set[str]) -> list[str]:
    """Everything wrong with a spec: the package's validator plus our guards."""
    problems = []
    if len(spec["parts"]) > MAX_PARTS:
        problems.append(f"at most {MAX_PARTS} parts, got {len(spec['parts'])}")
    for name, m in spec["materials"].items():
        tex = m.get("tex")
        if tex and tex.get("kind") not in TEX_KINDS:
            problems.append(f"material {name}: texture kind {tex.get('kind')!r} is not in {list(TEX_KINDS)}")
    pl = spec.get("place") or {}
    if pl.get("rule") in ("on", "over") and pl.get("target") not in other_ids:
        problems.append(f"place.target {pl.get('target')!r} must be one of the other pieces {sorted(other_ids)}")
    problems += validate_spec(spec)
    if problems:
        return problems
    dims = np.array(box_size, float)
    lo, hi = spec_extent(spec)
    half = dims / 2
    slack = dims * C.SPEC_OUTSIDE_BOX + 0.02
    if lo[1] < -C.FLOOR_TOLERANCE_M:
        problems.append(f"a part goes below the floor (y {lo[1]:.2f}); y=0 is the floor")
    if (lo[[0, 2]] < -half[[0, 2]] - slack[[0, 2]]).any() or (hi[[0, 2]] > half[[0, 2]] + slack[[0, 2]]).any() or hi[1] > dims[1] + slack[1]:
        problems.append(f"the model spans x {lo[0]:.2f}..{hi[0]:.2f}, y {lo[1]:.2f}..{hi[1]:.2f}, z {lo[2]:.2f}..{hi[2]:.2f} m; "
                        f"it must stay within the box {dims.round(3).tolist()} (x and z centred on 0, y from 0) by at most 10%")
    return problems


def validate_spec_answer(box_id: str, box_size: list[float], other_ids: set[str]):
    def validate(ans: dict) -> dict:
        try:
            spec = spec_from_answer(ans, box_id, box_size)
        except (KeyError, TypeError, AnswerError) as exc:
            raise AnswerError(f"malformed spec: {exc!r}") from exc
        problems = check_spec(spec, box_size, other_ids)
        if problems:
            raise AnswerError("\n".join(problems[:12]))
        return spec
    return validate


def validate_critique_answer(box_id: str, box_size: list[float], other_ids: set[str]):
    """-> ("done", reason) or ("edit", spec)."""
    inner = validate_spec_answer(box_id, box_size, other_ids)

    def validate(ans: dict):
        if ans.get("done"):
            return "done", ans.get("reason", "")
        if "spec" not in ans:
            raise AnswerError("not done, so `spec` (the revised model) is required")
        return "edit", inner(ans["spec"])
    return validate


def hints_from_answer(ans: dict) -> tuple[dict, dict[str, str]]:
    """Split an answer into accepted hint sections and {section: why rejected}.

    Each section is validated on its own by the package's parse_hints, so one
    out-of-range value costs only its section. Accepted sections are stamped
    source "review": somebody looked and decided.
    """
    candidates: dict[str, dict] = {}
    for name in ("baseboard", "wainscot", "floor"):
        if ans.get(name):
            candidates[name] = {name: {"source": "review", **_drop_none(ans[name])}}
    for kind in ("door", "window"):
        if ans.get(kind):
            candidates[f"openings.{kind}"] = {"openings": {kind: {"source": "review", **_drop_none(ans[kind])}}}
    accepted: dict[str, dict] = {}
    rejected: dict[str, str] = {}
    for name, doc in candidates.items():
        try:
            for sec, val in parse_hints(doc).items():
                if sec == "openings":
                    accepted.setdefault("openings", {}).update(val)
                else:
                    accepted[sec] = val
        except HintsError as exc:
            rejected[name] = "; ".join(exc.problems)[:300]
    return accepted, rejected
