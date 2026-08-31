"""The facing-sign leaf against real rooms (decision 0170).

Fifteen box placements from three of the four preserved walk captures,
frozen at `fixtures/facing_sign/walk_rooms.json`: a box, the splat's axis
extents, and the layout rotation its source observation carried. That is
everything `resolve_facing_sign` reads, so these pins run with no GCS, no
splats and no capture bundles while still driving production's own
candidate enumeration.

What they hold:

  * the shipped rotation IS one of the enumerated candidates — the
    assumption the whole leaf rests on, and the one thing that would make
    every other number here meaningless;
  * achieved residuals and separations, per object, at the values measured;
  * the SEPARATION between deciding and abstaining. On these rooms the
    residual distribution is bimodal — nothing between 29 and 70 degrees —
    which is what a geometric relationship looks like and what the five
    refuted scorers never produced (0081, 0104, 0156). A change that fills
    that band in is the interesting failure, so it is pinned as a band and
    not as a threshold;
  * that the leaf prefers a flip on exactly three objects — two of them the
    ones the operator reported by eye, and one it gets WRONG — and that its
    own residual does not separate the miss from the hits, which is why it
    ships recording its preference rather than acting on it.

Row provenance is not uniform and the difference matters. Five rows carry
an operator's verdict on a room they have stood in. The rest carry mine,
read off renders of the splat from its own source camera against the
photograph that made it — the same task decision 0156 measured a vision
model at 2-right-2-wrong-1-unclear on, so those reads are only used where
the two signs differ grossly (a glass-fronted cabinet against a blank slab)
and are recorded as unreadable otherwise.

rp6g2 is deliberately absent: its manifest was assembled over four rounds
from frames the cache does not hold, so its rows would pin the offline
replica rather than production (decision 0163).
"""
from __future__ import annotations

import json
from pathlib import Path

import box_placement
import numpy as np
import pytest
from roomplan_room import RoomPlanBox
from thegoodguest_schemas.pose_math import quat_to_rotmat, rotation_angle_deg

FIXTURE = Path(__file__).parent / "fixtures" / "facing_sign" / "walk_rooms.json"

# The operator's own verdicts on the shipped rooms, from decision 0156's
# table (the 0080/0085 walks). These are eyes on a room, not geometry —
# the only rows here whose provenance is a person.
OPERATOR = {
    ("rp7", "obj_001"): "flip",   # "the cupboard is facing the opposite direction"
    ("rp7", "obj_004"): "flip",   # "the bed is facing the opposite direction"
    ("rp7", "obj_000"): "keep",   # facing_flag true, operator blessed
    ("rp6g1", "obj_001"): "keep",
    ("spike", "obj_006"): "keep",
}


@pytest.fixture(scope="module")
def rows():
    return json.loads(FIXTURE.read_text())


def _box_of(row) -> RoomPlanBox:
    T = np.asarray(row["box_transform"], dtype=float).reshape(4, 4)
    return RoomPlanBox(
        identifier=row["identifier"],
        category=row["category"],
        confidence="high",
        attributes={},
        dimensions=np.asarray(row["box_dims"], dtype=float),
        transform=T,
        center_world=T[:3, 3].copy(),
        up_y=float(T[1, 1]),
        yaw_rad=float(np.arctan2(T[2, 0], T[0, 0])),
    )


def _resolve(row):
    """(chosen index, candidates, leaf result) through production code."""
    R_layout = quat_to_rotmat(tuple(row["layout_rotation_xyzw"]))
    up_local = R_layout.T @ np.array([0.0, 1.0, 0.0])
    cands = box_placement.axis_mapping_candidates(
        _box_of(row), np.asarray(row["splat_extents"], dtype=float), up_local
    )
    shipped = quat_to_rotmat(tuple(row["shipped_rotation_xyzw"]))
    chosen = min(
        range(len(cands)),
        key=lambda i: rotation_angle_deg(
            quat_to_rotmat(cands[i].rotation_xyzw), shipped
        ),
    )
    return chosen, cands, box_placement.resolve_facing_sign(cands, chosen, R_layout)


class TestFixture:
    def test_shape(self, rows):
        assert len(rows) == 15
        assert {r["room"] for r in rows} == {"spike", "rp7", "rp6g1"}
        assert all(r["layout_rotation_xyzw"] for r in rows)

    def test_shipped_rotation_is_an_enumerated_candidate(self, rows):
        """If this fails the leaf has nothing to choose between: it picks
        the partner of the SHIPPED candidate, so that candidate must be in
        the set production enumerated."""
        for r in rows:
            chosen, cands, _ = _resolve(r)
            err = rotation_angle_deg(
                quat_to_rotmat(cands[chosen].rotation_xyzw),
                quat_to_rotmat(tuple(r["shipped_rotation_xyzw"])),
            )
            assert err < 1e-3, f"{r['room']} {r['object_id']}: {err} deg off"


class TestAchievedValues:
    def test_residuals_reproduce(self, rows):
        for r in rows:
            _chosen, _cands, (_idx, resolved, resid, sep) = _resolve(r)
            assert resid == pytest.approx(r["residual_deg"], abs=0.01), r["object_id"]
            assert resolved is r["facing_sign_resolved"], r["object_id"]
            if sep is not None:
                assert sep == pytest.approx(r["separation_deg"], abs=0.01)

    def test_the_distribution_is_bimodal(self, rows):
        """Deciding and abstaining are separated by an empty band. The
        refuted scorers all lived inside their own gate's noise; this does
        not, and that gap is the evidence the gate's value rests on."""
        resid = np.array([r["residual_deg"] for r in rows])
        decided, abstained = resid[resid < 45.0], resid[resid >= 45.0]
        assert len(decided) == 8 and len(abstained) == 7
        assert decided.max() == pytest.approx(28.85, abs=0.01)
        assert abstained.min() == pytest.approx(70.03, abs=0.01)
        assert not ((resid > 29.0) & (resid < 70.0)).any()

    def test_a_decided_object_is_decided_by_a_wide_margin(self, rows):
        """Every resolved row prefers its sign by more than 140 degrees.
        There is no resolved row that is nearly a coin flip."""
        for r in rows:
            if r["facing_sign_resolved"]:
                assert r["separation_deg"] > 140.0, r["object_id"]


class TestVerdicts:
    def test_prefers_a_flip_on_exactly_three(self, rows):
        flipped = []
        for r in rows:
            chosen, cands, (idx, resolved, _d, _s) = _resolve(r)
            if resolved and idx != chosen:
                assert cands[idx].assignment == cands[chosen].assignment
                assert rotation_angle_deg(
                    quat_to_rotmat(cands[idx].rotation_xyzw),
                    quat_to_rotmat(cands[chosen].rotation_xyzw),
                ) == pytest.approx(180.0, abs=1e-3)
                flipped.append((r["room"], r["object_id"]))
        assert flipped == [
            ("rp7", "obj_001"),    # the cupboard the operator reported
            ("rp7", "obj_004"),    # the bed the operator reported
            ("rp6g1", "obj_003"),  # and one it gets WRONG — see below
        ]

    def test_the_confidence_does_not_separate_the_miss(self, rows):
        """The reason this leaf does not apply its own answer.

        Of the three flips it prefers, two are the objects the operator
        reported facing backwards and the third was already correct: the
        nightstand's drawer faces its source camera in the photograph and
        in the shipped rotation, and faces away under the flip. That is one
        wrong turn in three, and the leaf's own residual cannot find it —
        the miss sits BETWEEN the two hits. A future gate that claims to
        separate them has to beat this pin, not argue past it.
        """
        by_id = {(r["room"], r["object_id"]): r["residual_deg"] for r in rows}
        hit_a = by_id[("rp7", "obj_001")]
        miss = by_id[("rp6g1", "obj_003")]
        hit_b = by_id[("rp7", "obj_004")]
        assert hit_a == pytest.approx(2.91, abs=0.01)
        assert miss == pytest.approx(15.41, abs=0.01)
        assert hit_b == pytest.approx(28.85, abs=0.01)
        assert hit_a < miss < hit_b

    def test_agrees_with_every_operator_verdict_it_speaks_to(self, rows):
        """Five rows carry a person's judgement. The leaf decides two of
        them and abstains on three; it contradicts none. An abstention is
        not a hit — it is counted separately, because a leaf that abstained
        everywhere would otherwise look perfect."""
        decided = abstained = 0
        for r in rows:
            want = OPERATOR.get((r["room"], r["object_id"]))
            if want is None:
                continue
            chosen, _cands, (idx, resolved, _d, _s) = _resolve(r)
            if not resolved:
                abstained += 1
                continue
            decided += 1
            got = "flip" if idx != chosen else "keep"
            assert got == want, f"{r['room']} {r['object_id']}: {got} != {want}"
        assert (decided, abstained) == (2, 3)


class TestDegradeLock:
    def test_without_a_layout_nothing_is_claimed(self, rows):
        """The observation that carries no layout rotation is the common
        case on a swept capture and on any object whose splat came from a
        cache hit without a sidecar. It must cost nothing."""
        for r in rows:
            chosen, cands, _ = _resolve(r)
            assert box_placement.resolve_facing_sign(cands, chosen, None) == (
                chosen, False, None, None
            )

    def test_the_gate_is_the_only_thing_that_decides(self, rows, monkeypatch):
        """At a gate of zero every row abstains and the shipped rotation
        stands — the rollback, reproduced through the real geometry."""
        monkeypatch.setattr(box_placement, "_FACING_SIGN_MAX_RESIDUAL_DEG", 0.0)
        for r in rows:
            chosen, _cands, (idx, resolved, _d, _s) = _resolve(r)
            assert (idx, resolved) == (chosen, False)
