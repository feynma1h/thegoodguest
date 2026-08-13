"""The Design Specification: a proposal sitting BESIDE the measurement.

Decision 0131. The spec is a sibling of the manifest — the same relationship
the shell already has (0069: "a SIBLING of the manifest, read from
scenes/{id}/shell.json beside it") — holding a short list of proposed
placements. Every object it does not name is exactly where perception
measured it. It never rewrites a manifest, and a manifest re-drive never
invalidates it silently.

**Every entry carries the measurement it departs from.** That is the whole
answer to the honesty question, and it is the house pattern rather than a new
idea: 0069 ships `measured_quad` beside the rendered quad, 0082 refuses to
move an object to hide a splat artifact, 0104 declares a clip volume rather
than rescaling, placement ships `placed: false` with a reason rather than a
guessed transform. So a spec entry ships `measured_transform` beside
`proposed_transform`. The proposal is renderable and the truth is one field
away, at every layer, in the same object — not reconstructible from somewhere
else. That makes the lie structurally unavailable rather than prohibited by
discipline.

KEYING (0131), and it is the part that would fail silently if wrong:
`roomplan_box.identifier` where the object has a box, `object_id` otherwise.
See `room_geometry.spec_key` for the rule and for the measurement confirming
box identifiers survive re-drives. An entry whose key stops resolving becomes
ORPHANED and is surfaced — never dropped, never re-pointed. A spec pointing
at the wrong object after a re-drive would not error; it would move the wrong
piece of furniture and nothing in the system would notice, which is the same
class as 0080's version-blind shell fast-path that nooped silently for a week.

Firestore layout (server-only writes; the web client NEVER touches Firestore):

  design_specs/{scene_id}__{user_id}
    {scene_id, user_id, spec_version, updated_at, entries: [...]}

The same `{scene_id}__{user_id}` grain as conversations, in a SEPARATE
document so that clearing a conversation does not silently discard an
arrangement and vice versa.

ONE ARRANGEMENT PER SCENE+USER, ordered, linear (0133): revert drops the
named objects' entries or all of them, and "back to measured" is always one
action — not a versioning feature but the honesty invariant made operable. No
branches, no named alternatives; re-open when someone wants two side by side.
(0133 also describes a last-entry undo. It is not built: the repository
exposes get/put/clear, and the tools are propose and revert.)

F6 cascade note: identical to conversations — specs exist only for scenes
that reached `ready`, and the scenes TTL sweeps only terminal-failure scenes,
so a swept scene has no spec to orphan. If expiry ever extends to ready
scenes, this collection needs its own expire_at and TTL policy.

Consumers: public_server.py (spec routes + the conversation turn),
guest_tools.py (the tool runner writes through here).
"""
from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, replace
from datetime import datetime, timezone

# Bump when the entry SHAPE changes meaning. Entries written under an older
# version are read (the fields are additive so far); a future breaking change
# reads this to decide, rather than guessing from which keys are present.
SPEC_VERSION = 1

ACTIONS = frozenset({"move", "remove", "turn"})

# WHAT AN ENTRY DEPARTED FROM, and it is not decoration — three behaviours
# read it (decision 0157).
#
# A `move` departs from a MEASUREMENT: perception measured the piece here and
# the person is asking to see it there. Both are meaningful, one is true, and
# 0131's whole answer is that the true one stays beside it.
#
# A `turn` departs from an UNRESOLVED DEFAULT. The 180° sign of a splat inside
# its box is settled by no instrument — perception always ships the fixed
# (+,+) convention — so the value the person overruled was never a
# measurement, and treating it as one would put a guess in the field labelled
# `measured_transform` and call it truth. That is precisely the failure this
# document exists to make impossible.
#
# DERIVED, NEVER STORED: it is a function of `action`, and a second copy in
# Firestore could disagree with the first. It rides `client_dict` the way
# `orphaned` does — computed on the way out, never parsed back in.
DEPARTS_FROM_MEASUREMENT = "measurement"
DEPARTS_FROM_UNRESOLVED = "unresolved_default"


def departs_from(entry: "SpecEntry") -> str:
    """Which kind of claim this entry overruled. See the constants above."""
    return DEPARTS_FROM_UNRESOLVED if entry.action == "turn" else DEPARTS_FROM_MEASUREMENT

# A hard ceiling on one arrangement. Not a cost control — a product one: a
# spec is a short list of deliberate changes, and a hundred-entry document is
# a different feature (direct manipulation) wearing this one's schema.
MAX_ENTRIES = 24


@dataclass(frozen=True)
class Transform:
    """Position + rotation + scale, the manifest's own `world_transform`
    shape, so a spec entry and a manifest object are directly comparable."""
    position: tuple[float, float, float]
    rotation_xyzw: tuple[float, float, float, float]
    scale: float

    def to_doc(self) -> dict:
        return {
            "position": list(self.position),
            "rotation_xyzw": list(self.rotation_xyzw),
            "scale": self.scale,
        }

    @staticmethod
    def from_doc(doc: dict) -> "Transform | None":
        try:
            pos = tuple(float(v) for v in doc["position"])
            rot = tuple(float(v) for v in doc["rotation_xyzw"])
            scale = float(doc["scale"])
        except (KeyError, TypeError, ValueError):
            return None
        if len(pos) != 3 or len(rot) != 4:
            return None
        return Transform(position=pos, rotation_xyzw=rot, scale=scale)  # type: ignore[arg-type]


@dataclass(frozen=True)
class Footprint:
    """The measured box's floor rectangle. Additive to 0131's listed shape,
    and here for one reason: 0131 says the measurement survives on screen as
    its outline, and the client cannot derive that outline on its own —
    `PositionedSplat` carries no box, and `splat_clip` exists only on the
    objects whose splat overshoots. Shipping it with the entry keeps the
    client a reader (0131) instead of a second place that computes geometry.
    """
    center_world: tuple[float, float, float]
    half_extents_m: tuple[float, float, float]
    yaw_rad: float

    def to_doc(self) -> dict:
        return {
            "center_world": list(self.center_world),
            "half_extents_m": list(self.half_extents_m),
            "yaw_rad": self.yaw_rad,
        }

    @staticmethod
    def from_doc(doc: dict) -> "Footprint | None":
        try:
            c = tuple(float(v) for v in doc["center_world"])
            h = tuple(float(v) for v in doc["half_extents_m"])
            yaw = float(doc["yaw_rad"])
        except (KeyError, TypeError, ValueError):
            return None
        if len(c) != 3 or len(h) != 3:
            return None
        return Footprint(center_world=c, half_extents_m=h, yaw_rad=yaw)  # type: ignore[arg-type]


@dataclass(frozen=True)
class SolverTrace:
    """The reasoning trace 0055 lists as durable architecture — produced by
    the solver, never by the model. A spec entry that arrived some other way
    (direct manipulation) would have none, and the UI must then not imply
    one (0131's own re-open note)."""
    relation: str
    anchor_resolved_to: str
    constraints_applied: tuple[str, ...]
    reasoning: str

    def to_doc(self) -> dict:
        return {
            "relation": self.relation,
            "anchor_resolved_to": self.anchor_resolved_to,
            "constraints_applied": list(self.constraints_applied),
            "reasoning": self.reasoning,
        }

    @staticmethod
    def from_doc(doc: dict) -> "SolverTrace | None":
        if not isinstance(doc, dict):
            return None
        return SolverTrace(
            relation=str(doc.get("relation") or ""),
            anchor_resolved_to=str(doc.get("anchor_resolved_to") or ""),
            constraints_applied=tuple(
                str(c) for c in (doc.get("constraints_applied") or [])
            ),
            reasoning=str(doc.get("reasoning") or ""),
        )


@dataclass(frozen=True)
class SpecEntry:
    """One proposed placement, carrying the measurement it departs from."""
    key: str
    action: str                      # "move" | "remove" | "turn"
    label: str                       # the spoken name at authoring time
    measured_transform: Transform
    proposed_transform: Transform | None   # None for "remove"
    measured_footprint: Footprint | None
    solver: SolverTrace | None
    description: str                 # the server's sentence for this change
    turn_index: int | None
    client_msg_id: str | None
    # Whether the person corrected which way round this piece sits. Stored
    # rather than derived: it is provenance — the person ASSERTED this — and
    # recovering it by comparing two quaternions for equality would make a
    # record of what someone said depend on a float comparison. It rides
    # independently of `action` because a piece can be both moved and turned,
    # and losing one when the other changes would silently discard something
    # the person told us.
    facing_flipped: bool = False

    def to_doc(self) -> dict:
        return {
            "key": self.key,
            "action": self.action,
            "label": self.label,
            "facing_flipped": self.facing_flipped,
            "measured_transform": self.measured_transform.to_doc(),
            "proposed_transform": (
                self.proposed_transform.to_doc() if self.proposed_transform else None
            ),
            "measured_footprint": (
                self.measured_footprint.to_doc() if self.measured_footprint else None
            ),
            "solver": self.solver.to_doc() if self.solver else None,
            "description": self.description,
            "origin": {
                "turn_index": self.turn_index,
                "client_msg_id": self.client_msg_id,
            },
        }

    @staticmethod
    def from_doc(doc: dict) -> "SpecEntry | None":
        """Strict enough that a malformed entry is DROPPED rather than
        half-read. An entry with no measured transform is exactly the shape
        this document exists to make impossible, so it never loads."""
        if not isinstance(doc, dict):
            return None
        key = str(doc.get("key") or "")
        action = str(doc.get("action") or "")
        if not key or action not in ACTIONS:
            return None
        measured = Transform.from_doc(doc.get("measured_transform") or {})
        if measured is None:
            return None
        proposed = (
            Transform.from_doc(doc["proposed_transform"])
            if isinstance(doc.get("proposed_transform"), dict)
            else None
        )
        if action in ("move", "turn") and proposed is None:
            return None
        origin = doc.get("origin") or {}
        turn_index = origin.get("turn_index")
        return SpecEntry(
            key=key,
            action=action,
            label=str(doc.get("label") or ""),
            measured_transform=measured,
            proposed_transform=proposed,
            measured_footprint=(
                Footprint.from_doc(doc["measured_footprint"])
                if isinstance(doc.get("measured_footprint"), dict)
                else None
            ),
            solver=SolverTrace.from_doc(doc.get("solver") or {}) if doc.get("solver") else None,
            description=str(doc.get("description") or ""),
            turn_index=int(turn_index) if isinstance(turn_index, (int, float)) else None,
            client_msg_id=(
                str(origin["client_msg_id"])
                if isinstance(origin.get("client_msg_id"), str)
                else None
            ),
            # An entry written before facing corrections existed carries no
            # flag and is read as unflipped, which is what it was.
            facing_flipped=bool(doc.get("facing_flipped")),
        )


@dataclass(frozen=True)
class DesignSpec:
    """One arrangement. `entries` is ordered oldest-first; at most one entry
    per key (a second proposal for the same piece REPLACES the first, which
    is what "move it a bit further" means and keeps the arrangement linear)."""
    scene_id: str
    user_id: str
    entries: tuple[SpecEntry, ...] = ()
    updated_at: datetime | None = None

    def by_key(self, key: str) -> SpecEntry | None:
        for e in self.entries:
            if e.key == key:
                return e
        return None

    def with_entry(self, entry: SpecEntry) -> "DesignSpec":
        kept = [e for e in self.entries if e.key != entry.key]
        return replace(self, entries=tuple(kept) + (entry,))

    def without(self, keys: set[str]) -> "DesignSpec":
        return replace(self, entries=tuple(e for e in self.entries if e.key not in keys))


def client_dict(spec: DesignSpec, live_keys: set[str]) -> dict:
    """The wire projection.

    `orphaned` is the load-bearing field: an entry whose key no longer
    resolves in the current manifest is reported, not dropped and never
    re-pointed. The client shows it and offers to clear it; silence would be
    the failure mode 0131 names.
    """
    entries = []
    for e in spec.entries:
        doc = e.to_doc()
        doc["orphaned"] = e.key not in live_keys
        # Computed on the way out, never stored and never read back — the
        # client needs it to pick a treatment, and one implementation cannot
        # drift from itself. See `departs_from`.
        doc["departs_from"] = departs_from(e)
        entries.append(doc)
    return {
        "spec_version": SPEC_VERSION,
        "scene_id": spec.scene_id,
        "entries": entries,
        "updated_at": spec.updated_at.isoformat() if spec.updated_at else None,
    }


# ---------------------------------------------------------------------------
# Applying a spec (pure)
# ---------------------------------------------------------------------------

def apply_to_manifest(manifest: dict, spec: DesignSpec) -> dict:
    """A shallow copy of the manifest with the proposal's transforms in place.

    Used ONLY to re-derive facts for the proposed room (0132: "the solver can
    re-derive facts for the proposed room with the same code and the same
    epistemics"). It is never persisted and never served as the manifest —
    the manifest is perception's output and this is not perception.

    A `remove` entry drops the object from the derived facts entirely, which
    is the honest reading: the guest should not speak about where a piece is
    when the room it is looking at does not contain it.

    A `turn` changes the rotation and NOTHING else — not the position, not the
    box's dims, and above all not the box's yaw. The box is the measurement;
    the correction is about which way round the piece sits inside it. Nothing
    `scene_facts` derives reads a rotation, so a turn leaves every fact the
    guest can speak exactly as measured, which is why rule 10's conditional
    grammar does not apply to one.
    """
    from room_geometry import spec_key  # local: keeps the import graph a DAG

    if not spec.entries:
        return manifest
    out = dict(manifest)
    objects = []
    for obj in manifest.get("objects", []):
        if not isinstance(obj, dict):
            objects.append(obj)
            continue
        entry = spec.by_key(spec_key(obj))
        if entry is None:
            objects.append(obj)
            continue
        if entry.action == "remove":
            continue
        moved = dict(obj)
        wt = dict(obj.get("world_transform") or {})
        assert entry.proposed_transform is not None
        wt["position"] = list(entry.proposed_transform.position)
        wt["rotation_xyzw"] = list(entry.proposed_transform.rotation_xyzw)
        moved["world_transform"] = wt
        box = obj.get("roomplan_box")
        if isinstance(box, dict):
            # The box travels with the piece: dims and yaw are the
            # measurement and never change, but a box left at the measured
            # centre would make every derived distance describe a room
            # nobody is looking at.
            moved_box = dict(box)
            moved_box["center_world"] = list(entry.proposed_transform.position)
            moved["roomplan_box"] = moved_box
        objects.append(moved)
    out["objects"] = objects
    return out


# ---------------------------------------------------------------------------
# Repository
# ---------------------------------------------------------------------------

class DesignSpecRepository(ABC):
    """Read/replace, not read/modify/write: every mutation here is a whole-
    document write of an entries list the caller already reconciled. One
    arrangement per scene+user and at most ~24 entries, so the document is
    small and last-write-wins is the right concurrency story — the same
    posture 0087 took for same-UID upload session overlap."""

    @abstractmethod
    def get(self, scene_id: str, user_id: str) -> DesignSpec: ...

    @abstractmethod
    def put(self, spec: DesignSpec, *, now: datetime) -> DesignSpec: ...

    @abstractmethod
    def clear(self, scene_id: str, user_id: str) -> None: ...


class InMemoryDesignSpecRepository(DesignSpecRepository):
    """Tests and dev; the semantics oracle the Firestore impl mirrors."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._specs: dict[tuple[str, str], DesignSpec] = {}

    def get(self, scene_id: str, user_id: str) -> DesignSpec:
        with self._lock:
            return self._specs.get(
                (scene_id, user_id), DesignSpec(scene_id=scene_id, user_id=user_id)
            )

    def put(self, spec: DesignSpec, *, now: datetime) -> DesignSpec:
        stored = replace(
            spec, entries=spec.entries[-MAX_ENTRIES:], updated_at=now
        )
        with self._lock:
            self._specs[(spec.scene_id, spec.user_id)] = stored
        return stored

    def clear(self, scene_id: str, user_id: str) -> None:
        with self._lock:
            self._specs.pop((scene_id, user_id), None)


class FirestoreDesignSpecRepository(DesignSpecRepository):
    """Production. google.cloud.firestore imports lazily, per service
    convention."""

    COLLECTION = "design_specs"

    def __init__(self, project: str | None = None) -> None:
        from google.cloud import firestore  # deferred

        self._db = firestore.Client(project=project) if project else firestore.Client()

    def _ref(self, scene_id: str, user_id: str):
        return self._db.collection(self.COLLECTION).document(f"{scene_id}__{user_id}")

    def get(self, scene_id: str, user_id: str) -> DesignSpec:
        snap = self._ref(scene_id, user_id).get()
        empty = DesignSpec(scene_id=scene_id, user_id=user_id)
        if not snap.exists:
            return empty
        doc = snap.to_dict() or {}
        entries = [
            e for e in (SpecEntry.from_doc(d) for d in doc.get("entries") or [])
            if e is not None
        ]
        return DesignSpec(
            scene_id=scene_id,
            user_id=user_id,
            entries=tuple(entries),
            updated_at=doc.get("updated_at"),
        )

    def put(self, spec: DesignSpec, *, now: datetime) -> DesignSpec:
        stored = replace(spec, entries=spec.entries[-MAX_ENTRIES:], updated_at=now)
        self._ref(spec.scene_id, spec.user_id).set({
            "scene_id": spec.scene_id,
            "user_id": spec.user_id,
            "spec_version": SPEC_VERSION,
            "entries": [e.to_doc() for e in stored.entries],
            "updated_at": now,
        })
        return stored

    def clear(self, scene_id: str, user_id: str) -> None:
        self._ref(scene_id, user_id).delete()


def utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)
