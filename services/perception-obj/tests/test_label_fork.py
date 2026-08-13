"""Decision 0149 — one physical object, one cluster, even when SAM cannot
keep its mind on a label.

The same-frame cross-label collapse keeps whichever of two near-identical
detections scored higher IN THAT FRAME. Its docstring says a collapsed
group "never seeds objects under several labels", which is true inside a
frame and false across them: rp7's monitor is detected as both `monitor`
and `tv` in all three frames that see it, `monitor` wins at f7 and `tv`
wins at f114 and f385, and the label split then made three views of one
monitor into a one-view `monitor` and a two-view `tv`.

So the refined pass groups by confusable GROUP rather than raw label. The
vocabulary is the one the 3D duplicate gate already uses — the same
question, asked earlier and more cheaply.
"""
from __future__ import annotations

import fusion
import numpy as np


class Ctx:
    budget = None
    min_remaining_s = 0.0

    def __init__(self, splats=None, masks=None):
        self.splats = splats or {}
        self.masks = masks or {}
        self.get_appearance = None
        self.get_rgb = None
        self.get_depth = None

    def get_roomplan(self):
        return None

    def get_room_planes(self):
        return None

    def get_splat(self, uri):
        return self.splats.get(uri)

    def get_camera(self, frame_index):
        return None

    def mask_for(self, frame_index, mask_index):
        return self.masks.get((frame_index, mask_index))

    def evidence_for(self, *a):
        return None


def _frame(frame_index, entries):
    return {"frame_index": frame_index, "objects": entries}


def _entry(label, mask_index, score, position, uri):
    return {
        "ok": True, "label": label, "score": score, "mask_index": mask_index,
        "splat_gcs_uri": uri,
        "placement": {
            "placed": True, "method": "depth_fit",
            "world_transform": {
                "position": list(position), "rotation_xyzw": [0.0, 0.0, 0.0, 1.0],
                "scale": 1.0,
            },
            "quality": {},
        },
        "view_ray": None,
    }


class TestGroupingKey:
    def test_confusable_labels_share_a_key(self):
        assert fusion._grouping_key("monitor") == fusion._grouping_key("tv")
        assert fusion._grouping_key("artwork") == fusion._grouping_key("painting")
        assert fusion._grouping_key("desk") == fusion._grouping_key("nightstand")

    def test_unrelated_labels_do_not(self):
        assert fusion._grouping_key("curtain") != fusion._grouping_key("monitor")
        assert fusion._grouping_key("plant") != fusion._grouping_key("chair")

    def test_an_unknown_label_is_its_own_key(self):
        assert fusion._grouping_key("kettle") == "kettle"
        assert fusion._grouping_key(None) == ""


class TestTheForkIsClosed:
    """The rp7 monitor, in miniature: one object, three frames, a label
    that changes between them."""

    def _scene(self):
        pts = np.random.default_rng(0).uniform(-0.2, 0.2, size=(300, 3))
        uris = {f"gs://o/{i}.ply": pts for i in (7, 114, 385)}
        frames = [
            _frame(7, [_entry("monitor", 0, 0.90, (1.0, 0.5, 1.0), "gs://o/7.ply")]),
            _frame(114, [_entry("tv", 0, 0.88, (1.05, 0.52, 1.05), "gs://o/114.ply")]),
            _frame(385, [_entry("tv", 0, 0.95, (0.98, 0.49, 0.97), "gs://o/385.ply")]),
        ]
        return frames, Ctx(splats=uris)

    def test_the_three_views_become_one_object(self):
        frames, ctx = self._scene()
        objs = fusion.fuse_scene_objects(frames, ctx)
        placed = [o for o in objs if o["placed"]]
        assert len(placed) == 1
        assert placed[0]["quality"]["frames_observed"] == 3

    def test_the_object_keeps_a_real_label(self):
        """Grouping is internal. The fused object is still named by its
        best-scoring member, so nothing is renamed to a group key."""
        frames, ctx = self._scene()
        placed = [o for o in fusion.fuse_scene_objects(frames, ctx) if o["placed"]]
        assert placed[0]["label"] in ("monitor", "tv")
        assert not placed[0]["label"].startswith("grp:")

    def test_two_distinct_objects_of_confusable_labels_stay_apart(self):
        """Sharing a key is not merging: the proximity clustering
        separates them exactly as it always has."""
        pts = np.random.default_rng(0).uniform(-0.2, 0.2, size=(300, 3))
        ctx = Ctx(splats={"gs://o/a.ply": pts, "gs://o/b.ply": pts})
        frames = [_frame(1, [
            _entry("monitor", 0, 0.9, (0.0, 1.0, 0.0), "gs://o/a.ply"),
            _entry("tv", 1, 0.9, (3.0, 1.0, 0.0), "gs://o/b.ply"),
        ])]
        placed = [o for o in fusion.fuse_scene_objects(frames, ctx) if o["placed"]]
        assert len(placed) == 2


class TestTheTwoSameFrameTestsStaySeparate:
    """Sharing a grouping key must not let the same-frame NESTED-pair
    dedup reach across labels. It absorbs on containment of the SMALLER,
    so a small object genuinely sitting inside a larger different-label
    one would vanish — which is exactly what the same-frame cross-label
    collapse refuses by testing containment of the LARGER instead.
    Found by this change breaking the gate's own test."""

    def test_a_nested_different_label_object_survives(self):
        big = np.zeros((64, 64), dtype=bool)
        big[10:50, 10:50] = True
        small = np.zeros((64, 64), dtype=bool)
        small[20:28, 20:28] = True
        pts = np.random.default_rng(0).uniform(-0.2, 0.2, size=(300, 3))
        ctx = Ctx(
            splats={"gs://o/a.ply": pts, "gs://o/b.ply": pts},
            masks={(0, 0): big, (0, 1): small},
        )
        frames = [_frame(0, [
            _entry("mirror", 0, 0.9, (0.0, 1.0, 0.0), "gs://o/a.ply"),
            _entry("painting", 1, 0.8, (0.0, 1.0, 0.0), "gs://o/b.ply"),
        ])]
        kept, _recs = fusion._dedup_same_frame_per_label(
            fusion._collect_observations(frames), ctx
        )
        assert len(kept) == 2

    def test_a_nested_same_label_duplicate_is_still_absorbed(self):
        """The matched half: the pass must keep doing its own job."""
        big = np.zeros((64, 64), dtype=bool)
        big[10:50, 10:50] = True
        inner = np.zeros((64, 64), dtype=bool)
        inner[12:48, 12:48] = True
        pts = np.random.default_rng(0).uniform(-0.2, 0.2, size=(300, 3))
        ctx = Ctx(
            splats={"gs://o/a.ply": pts, "gs://o/b.ply": pts},
            masks={(0, 0): big, (0, 1): inner},
        )
        frames = [_frame(0, [
            _entry("bed", 0, 0.9, (0.0, 1.0, 0.0), "gs://o/a.ply"),
            _entry("bed", 1, 0.8, (0.0, 1.0, 0.0), "gs://o/b.ply"),
        ])]
        kept, recs = fusion._dedup_same_frame_per_label(
            fusion._collect_observations(frames), ctx
        )
        assert len(kept) == 1 and len(recs) == 1


class TestDegradeLock:
    def test_the_legacy_pass_still_groups_by_raw_label(self):
        """PLACEMENT_REFINE=0 is the rollback lever and its output is a
        bit-parity target: it must not learn about confusable groups."""
        import inspect
        src = inspect.getsource(fusion._fuse_scene_objects_legacy)
        assert "_grouping_key" not in src
        assert 'by_label.setdefault(o["label"] or ""' in src

    def test_no_context_reproduces_the_legacy_split(self):
        frames = [
            _frame(7, [_entry("monitor", 0, 0.90, (1.0, 0.5, 1.0), "gs://o/7.ply")]),
            _frame(114, [_entry("tv", 0, 0.88, (1.05, 0.52, 1.05), "gs://o/114.ply")]),
        ]
        objs = fusion.fuse_scene_objects(frames, None)
        assert len({o["label"] for o in objs}) == 2
        assert all(o["quality"]["frames_observed"] == 1 for o in objs)
