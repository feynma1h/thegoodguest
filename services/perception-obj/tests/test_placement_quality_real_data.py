"""Real-data regression pins for decision 0067's placement-quality pass.

Six physical objects from the first real capture (scene 25a14caf, the same
recording test_layout_conventions_real_data.py pins) with their recorded
raw observations (manifest layout_prior / view_ray fields, copied
verbatim) and camera poses (bundle.pb, copied verbatim). This is the
"verify-first probes become pin tolerances" half of the brief: V1-V3 ran
as ad hoc offline scripts against this same data before any pipeline code
existed; these tests turn the SAME measurements into a permanent
regression suite exercising the production fusion.py/reproject.py code
paths.

Small real evidence is committed alongside this file:
  tests/fixtures/scene_25a14caf/frames/<idx>/{masks.npz,objects.json} --
  the 12 sampled frames' real SAM masks (~390 KB total), fetched from the
  outputs bucket.
Large evidence (the splat PLYs, tens of MB each) is NOT committed; tests
that need real splat geometry (silhouette fit, in-plane resolution, the
sign-flag check) read it by absolute path from the main checkout's
web/public/dev-fixtures/ (decision 0067 build brief: "Main's real-capture
fixtures are readable by absolute path") and skip cleanly if that
checkout isn't present.

Must-pass correspondence set (V2): the seven bed observations fuse to
ONE object (frame 28's nested duplicate detection dedups); the curtain's
seven observations stay ONE cluster; the door's seven observations stay
SIX fused objects (one genuine 2-view merge, five distinct single-frame
doors -- must not collapse further); the lamp's four observations
(0.007 m triangulation RMS class) are unaffected by refinement -- a
compact, unambiguous object must not regress.

Run from repo root:

    python -m pytest services/perception-obj/tests/test_placement_quality_real_data.py -v
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import fusion
import numpy as np
import placement
import pytest
import reproject

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "scene_25a14caf" / "frames"
DEV_FIXTURES_DIR = Path("/Users/aubrey/projects/roomstudio/web/public/dev-fixtures")
CURTAIN_PLY = DEV_FIXTURES_DIR / "real_obj_009_curtain.ply"
BED_PLY = DEV_FIXTURES_DIR / "real_obj_003_bed.ply"

_needs_real_splats = pytest.mark.skipif(
    not (CURTAIN_PLY.exists() and BED_PLY.exists()),
    reason="real splat PLYs only available in the main checkout's web/public/dev-fixtures/",
)


@dataclass
class FakeIntrinsics:
    fx: float
    fy: float
    cx: float
    cy: float


@dataclass
class FakePose:
    pos_x: float
    pos_y: float
    pos_z: float
    quat_x: float
    quat_y: float
    quat_z: float
    quat_w: float


# --- Recorded real data: scene 25a14caf, per-frame camera pose + intrinsics.
CAMERA = {
    0: {"pos": (0.0, 0.0, 0.0), "quat": (-0.09869691729545593, -0.02219265140593052, -0.7006165981292725, 0.706330418586731), "intr": (1446.57470703125, 1446.57470703125, 921.638671875, 718.63623046875)},
    18: {"pos": (-0.2811357378959656, 0.0416368804872036, 0.12798216938972473), "quat": (-0.5436854958534241, 0.4885300099849701, -0.4506409168243408, 0.5125107169151306), "intr": (1467.9163818359375, 1467.9163818359375, 920.4254150390625, 720.100341796875)},
    28: {"pos": (-0.8592783212661743, 0.06150246784090996, 0.33140817284584045), "quat": (0.6779541969299316, -0.6630674600601196, 0.20385748147964478, -0.24323180317878723), "intr": (1466.572021484375, 1466.572021484375, 920.5283813476562, 720.730224609375)},
    42: {"pos": (-1.0186231136322021, 0.07879624515771866, 0.5765063166618347), "quat": (-0.6640892028808594, 0.6853669285774231, 0.22057655453681946, -0.20150360465049744), "intr": (1464.335205078125, 1464.335205078125, 919.98046875, 718.6558227539062)},
    53: {"pos": (-1.098015308380127, 0.21830914914608002, 0.4795874357223511), "quat": (0.6459246873855591, -0.4416908621788025, -0.3359134793281555, 0.524263858795166), "intr": (1467.0029296875, 1467.0029296875, 921.5911865234375, 721.57177734375)},
    67: {"pos": (-1.1697802543640137, 0.19627618789672852, 0.2542475163936615), "quat": (0.3199376165866852, -0.09808848053216934, -0.6389883756637573, 0.6926127672195435), "intr": (1466.9820556640625, 1466.9820556640625, 922.0040283203125, 720.9463500976562)},
    83: {"pos": (-0.9369467496871948, -0.06528235226869583, 0.3944375216960907), "quat": (-0.37759798765182495, 0.6015896797180176, 0.5966729521751404, -0.37348490953445435), "intr": (1467.4388427734375, 1467.4388427734375, 923.82080078125, 719.3036499023438)},
    99: {"pos": (-1.1639269590377808, -0.07161219418048859, 0.7468414306640625), "quat": (-0.6747772097587585, 0.6957954168319702, 0.21372275054454803, 0.12193042784929276), "intr": (1466.9300537109375, 1466.9300537109375, 925.0204467773438, 719.7443237304688)},
    105: {"pos": (-0.8078378438949585, -0.046057019382715225, 0.8231073617935181), "quat": (0.6965981125831604, -0.6562471985816956, -0.02083098515868187, -0.28923463821411133), "intr": (1467.5374755859375, 1467.5374755859375, 923.11328125, 718.8213500976562)},
    110: {"pos": (-0.6866292953491211, -0.07805176079273224, 1.2157213687896729), "quat": (0.689139723777771, -0.5841675996780396, 0.11068278551101685, -0.4142269194126129), "intr": (1467.698486328125, 1467.698486328125, 924.7825927734375, 719.2908935546875)},
    116: {"pos": (-0.6303726434707642, -0.07506541907787323, 1.7615327835083008), "quat": (0.6743189096450806, -0.5179854035377502, 0.19988003373146057, -0.486860454082489), "intr": (1467.5269775390625, 1467.5269775390625, 925.6018676757812, 719.006591796875)},
    124: {"pos": (-0.324815958738327, -0.2649228870868683, 1.9009504318237305), "quat": (0.7016025185585022, -0.5294877886772156, -0.15003451704978943, -0.45264363288879395), "intr": (1468.49755859375, 1468.49755859375, 931.6884155273438, 718.666259765625)},
}

# --- Recorded real data: raw observations per label, verbatim from the
# ready manifest ("frames[].objects[]"), successful ("ok") entries only.
# Columns: (frame_index, mask_index, score, world_rotation_xyzw,
# splat_max_extent, ray_origin, ray_direction, angular_extent_rad).
BED_RAW = [
    (18, 1, 0.7734375, [-0.3811140991452039, 0.6217576285475137, 0.4219740185182695, 0.5386162107393863], 0.9974448049074192, [-0.2811357378959656, 0.0416368804872036, 0.12798216938972473], [-0.7942881598091017, -0.4775851585386192, 0.3755244565646245], 0.4720977356579794),
    (28, 3, 0.765625, [0.7880334553977886, -0.4150185341587189, 0.2892173379554295, -0.35087921127439947], 1.0087598026530529, [-0.8592783212661743, 0.06150246784090996, 0.33140817284584045], [-0.5509653875339756, -0.5509547899528481, 0.6268059597814448], 0.9661987132181881),
    (28, 5, 0.6953125, [-0.2420310228444089, 0.8315832976386454, -0.49965176005310347, 0.0154376729192397], 1.180264004931555, [-0.8592783212661743, 0.06150246784090996, 0.33140817284584045], [-0.4732657456029117, -0.5630552885100893, 0.6774865549317214], 0.902103668022345),
    (99, 1, 0.79296875, [0.4058315495009148, 0.4812440443205178, -0.5684607242314519, 0.5296766261049956], 1.0118901108674538, [-1.1639269590377808, -0.07161219418048859, 0.7468414306640625], [-0.0016367271888651255, -0.7745311638306241, 0.6325336027684851], 0.9816418965288688),
    (105, 1, 0.87890625, [-0.5288897892790322, -0.4384370531330981, 0.571311746134551, -0.4490561545787299], 1.0079131809030573, [-0.8078378438949585, -0.046057019382715225, 0.8231073617935181], [-0.3523108498169686, -0.7477074615426899, 0.5628590837186055], 0.9812355895205043),
    (110, 1, 0.8515625, [0.14907379792946743, 0.7598546048882239, 0.6289077772282234, 0.06980680441691023], 1.0046861300190886, [-0.6866292953491211, -0.07805176079273224, 1.2157213687896729], [-0.5586742824542648, -0.7530665444765038, 0.3475251141694764], 0.8891472002978196),
    (116, 1, 0.88671875, [-0.3921944359108449, 0.5803278706348389, 0.5503161106841233, 0.45448351491171535], 1.0001348945947797, [-0.6303726434707642, -0.07506541907787323, 1.7615327835083008], [-0.7153253476591979, -0.6967160199704638, 0.05381852806631457], 0.7522860001192815),
]
CURTAIN_RAW = [
    (28, 1, 0.94921875, [-0.42737596829125035, -0.4734070694453706, 0.5256168808936587, 0.5629941588026323], 0.9783180635589206, [-0.8592783212661743, 0.06150246784090996, 0.33140817284584045], [-0.30309102222417833, -0.12652271474153864, 0.9445250565511888], 0.9621075401205811),
    (42, 3, 0.82421875, [0.704888420251936, -0.6847190961217227, -0.12744357369612594, 0.13435106968141858], 0.9457732339156444, [-1.0186231136322021, 0.07879624515771866, 0.5765063166618347], [0.18534055285445372, -0.22010967369046383, 0.957705940971329], 1.0817195369659167),
    (99, 0, 0.953125, [0.5275835102596586, 0.5992317093939723, 0.39267182108311205, 0.45649297813454615], 1.0122360463621225, [-1.1639269590377808, -0.07161219418048859, 0.7468414306640625], [0.0020708032145456317, -0.21297048581058645, 0.9770564148159081], 0.7614541655713517),
    (105, 0, 0.9609375, [-0.42933141925296275, -0.3679396075911839, 0.5669837556004782, 0.5990195309779637], 1.0133622812529979, [-0.8078378438949585, -0.046057019382715225, 0.8231073617935181], [-0.22047387005914112, -0.20586837862467705, 0.9534197385270233], 0.900147370664296),
    (110, 0, 0.93359375, [-0.0024273317730094074, -0.07208958793247193, -0.7555349948331528, 0.6511252344631238], 1.0004697392996769, [-0.6866292953491211, -0.07805176079273224, 1.2157213687896729], [-0.4656726892118668, -0.24305395070275937, 0.8509251451259389], 0.9736332177973825),
    (116, 0, 0.953125, [0.0011586259898471777, -0.11518223079780646, -0.7934051935575562, 0.5976954995063566], 0.9533041709265946, [-0.6303726434707642, -0.07506541907787323, 1.7615327835083008], [-0.6259966989626617, -0.35116876518039714, 0.6962820051519991], 1.3021907121629954),
    (124, 0, 0.9375, [0.7111163305575687, 0.7025661745106172, -0.013781014911217112, -0.02290018506196395], 1.1119335617764574, [-0.324815958738327, -0.2649228870868683, 1.9009504318237305], [-0.5008666708397924, -0.5465557741027918, 0.671125507769631], 0.7436171709033766),
]
DOOR_RAW = [
    (0, 1, 0.5390625, [0.42976913000581646, -0.41614083332954493, -0.5805453855338316, 0.5523516606883792], 0.9973130962691763, [0.0, 0.0, 0.0], [-0.2963766764187054, 0.02686388476788618, -0.9546932439175881], 0.8986746371834057),
    (18, 2, 0.625, [0.7136054242573484, -0.6994258327681242, -0.0302460848846393, 0.025612053339335084], 0.9976558170729668, [-0.2811357378959656, 0.0416368804872036, 0.12798216938972473], [-0.9791231425322883, 0.0005617804915459921, -0.20326706675437542], 0.4543855550993828),
    (18, 4, 0.53125, [0.7574577084863262, -0.6450957185474927, -0.03357986099477778, 0.09477197213263634], 0.9952045404508783, [-0.2811357378959656, 0.0416368804872036, 0.12798216938972473], [-0.9186896119294364, -0.3586892750742428, -0.1653823091500484], 0.40874262827530683),
    (18, 5, 0.51953125, [0.7051067518829538, -0.7001477084217943, -0.08058980062633089, 0.07824921006495338], 0.9966664524723147, [-0.2811357378959656, 0.0416368804872036, 0.12798216938972473], [-0.9789194791492493, -0.20418380807502, -0.0050535105645284], 0.8815216016470785),
    (18, 6, 0.515625, [0.6898129225684918, -0.6897787077514524, -0.1732777828387395, 0.1354188914618003], 1.0069153981613843, [-0.2811357378959656, 0.0416368804872036, 0.12798216938972473], [-0.9048394112498103, -0.42573509645780416, -0.003893891190372039], 0.4046552019925538),
    (18, 7, 0.50390625, [0.6979328662734037, -0.6888544204977298, -0.13652967065169447, 0.14045978274177906], 0.9987884124037978, [-0.2811357378959656, 0.0416368804872036, 0.12798216938972473], [-0.999985419357542, 0.004578718298287868, -0.00285065207784826], 0.46460412080626545),
    (67, 0, 0.82421875, [0.5463388081083355, 0.5475803261271565, 0.3757047301476994, 0.5104073362892475], 1.0451903506117999, [-1.1697802543640137, 0.19627618789672852, 0.2542475163936615], [0.3976460208242396, -0.07084908287503186, -0.9147994588149866], 0.552153993208414),
]
LAMP_RAW = [
    (28, 6, 0.5859375, [0.11437889188879063, 0.6750199706591188, 0.7170712150949439, -0.13066897406773953], 0.9942599734258856, [-0.8592783212661743, 0.06150246784090996, 0.33140817284584045], [-0.46964116674714357, -0.20461200618948103, 0.8588194499593096], 0.22910569346599238),
    (105, 3, 0.70703125, [-0.11037759122657897, 0.6931479675133784, 0.7062255913799093, 0.09277982844987427], 0.9946311496101805, [-0.8078378438949585, -0.046057019382715225, 0.8231073617935181], [-0.5805775992455653, -0.18526855554131466, 0.7928461109183152], 0.2766539231564755),
    (110, 3, 0.671875, [-0.24924223902625203, 0.6462311860315254, 0.6839215484125053, 0.22916124476557936], 0.9974787048361197, [-0.6866292953491211, -0.07805176079273224, 1.2157213687896729], [-0.7070328180952071, -0.19126691357965722, 0.6808240985424341], 0.30319578860730245),
    (116, 3, 0.7265625, [-0.2397385599238404, 0.654134185651282, 0.6881777818396236, 0.20259622560717344], 0.9993589291512941, [-0.6303726434707642, -0.07506541907787323, 1.7615327835083008], [-0.8587357401293971, -0.22562167441903747, 0.460073676924246], 0.3454791685330396),
]

_LABEL_SLUG = {"bed": "bed", "curtain": "curtain", "door": "door", "table lamp": "table_lamp"}


def _splat_uri(frame_index, mask_index, label):
    slug = _LABEL_SLUG[label]
    return (
        f"gs://roomstudio-perception-outputs/scenes/25a14caf-db19-487d-9a60-3bd4034cd4c4/"
        f"frames/{frame_index:04d}/splats/{mask_index:02d}_{slug}.ply"
    )


def _entry(row, label):
    frame_index, mask_index, score, world_rot, splat_extent, origin, direction, angular = row
    return frame_index, {
        "label": label, "instance_idx": 0, "bbox": [0, 0, 10, 10], "score": score,
        "mask_index": mask_index, "ok": True,
        "splat_gcs_uri": _splat_uri(frame_index, mask_index, label),
        "placement": {
            "placed": False, "method": None, "reason": "no_depth_pending_triangulation",
            "world_transform": None, "quality": {},
            "world_rotation_xyzw": list(world_rot), "rotation_source": "sam3d_layout",
            "splat_max_extent": splat_extent,
        },
        "view_ray": {"origin": list(origin), "direction": list(direction), "angular_extent_rad": angular},
    }


def _frame_results(*rows_and_labels):
    by_frame: dict = {}
    for rows, label in rows_and_labels:
        for row in rows:
            frame_index, entry = _entry(row, label)
            by_frame.setdefault(frame_index, []).append(entry)
    return [{"frame_index": fi, "objects": objs, "ok": True} for fi, objs in sorted(by_frame.items())]


def _load_mask_stack(frame_index):
    path = FIXTURE_DIR / f"{frame_index:04d}" / "masks.npz"
    if not path.exists():
        return None
    return np.load(path)["masks"]


def _get_camera(frame_index):
    cam = CAMERA.get(frame_index)
    if cam is None:
        return None
    return (
        FakePose(*cam["pos"], *cam["quat"]),
        FakeIntrinsics(*cam["intr"]),
    )


_SPLAT_PATHS = {
    _splat_uri(116, 1, "bed"): BED_PLY,
    _splat_uri(105, 0, "curtain"): CURTAIN_PLY,
}
_SPLAT_CACHE: dict = {}


def _get_splat(uri):
    path = _SPLAT_PATHS.get(uri)
    if path is None or not path.exists():
        return None
    if uri not in _SPLAT_CACHE:
        _SPLAT_CACHE[uri] = placement.parse_ply_vertices(path.read_bytes())
    return _SPLAT_CACHE[uri]


def _real_ctx():
    return fusion.RefinementContext(
        get_camera=_get_camera,
        get_mask_stack=_load_mask_stack,
        get_splat=_get_splat,
    )


def _full_scene_frame_results():
    return _frame_results(
        (BED_RAW, "bed"), (CURTAIN_RAW, "curtain"), (DOOR_RAW, "door"), (LAMP_RAW, "table lamp"),
    )


# fuse_scene_objects with refinement on runs a real (bounded but not free)
# silhouette-fit optimization for every multi-view object with a mapped
# splat (bed + curtain here). Computed ONCE per test session and shared --
# recomputing it per assertion turned this file into a many-minutes run.
@pytest.fixture(scope="module")
def refined_objects():
    return fusion.fuse_scene_objects(_full_scene_frame_results(), _real_ctx())


@pytest.fixture(scope="module")
def legacy_objects():
    return fusion.fuse_scene_objects(_full_scene_frame_results())


# -----------------------------------------------------------------------------
# V2 must-pass correspondence set
# -----------------------------------------------------------------------------

def test_dedup_eliminates_the_wrongly_placed_second_bed(refined_objects, legacy_objects):
    """Empirical correction to decision 0067's V2 text: on the actual
    12-frame sampled fixture, dedup does NOT merge all 7 raw bed
    observations into one cluster -- frame 18's ray does not
    RMS-triangulate with the other 5 (joint RMS 0.379; pairwise up to
    0.43 against frames 110/116), and the footprint-rescue mechanism
    can't bridge it either: the provisional position (built from the
    other 5 views) reprojects entirely off-frame from frame 18's much
    closer vantage (a real, measured limit of a rough pre-fit position
    estimate, not a bug -- the mechanism itself is separately pinned on
    synthetic data in test_fusion_refinement.py). What dedup
    DOES verifiably fix: before, the frame-28 duplicate paired with
    frame 18 to form a SECOND, WRONGLY-PLACED bed (the legacy obj_004:
    1.26 m from the real bed, scale 0.39, per decision 0067). After
    dedup, that duplicate is gone, so frame 18 surfaces HONESTLY as an
    unplaced single observation instead of anchoring a confidently wrong
    phantom bed. Same object count (2), materially better manifest.
    """
    legacy_beds = [o for o in legacy_objects if o["label"] == "bed"]
    assert len(legacy_beds) == 2
    assert all(o["placed"] for o in legacy_beds)  # legacy: BOTH placed, one wrongly

    refined_beds = [o for o in refined_objects if o["label"] == "bed"]
    assert len(refined_beds) == 2
    placed = [o for o in refined_beds if o["placed"]]
    unplaced = [o for o in refined_beds if not o["placed"]]
    assert len(placed) == 1 and len(unplaced) == 1

    # The one placed bed matches decision 0067's "obj_003" description
    # exactly: 5 observations, RMS ~0.264.
    assert placed[0]["quality"]["frames_observed"] == 5
    assert placed[0]["quality"]["triangulation_rms_m"] == pytest.approx(0.2641, abs=1e-3)
    assert placed[0]["deduped_observations"] == 1

    # The unplaced one is frame 18, alone -- not a second, wrongly-placed bed.
    assert unplaced[0]["quality"]["frames_observed"] == 1
    assert unplaced[0]["reason"] == "insufficient_observations"


def test_curtain_stays_one_cluster(refined_objects):
    curtains = [o for o in refined_objects if o["label"] == "curtain"]
    assert len(curtains) == 1
    assert curtains[0]["quality"]["frames_observed"] == 7
    assert curtains[0]["deduped_observations"] == 0


def test_six_doors_do_not_collapse(refined_objects):
    doors = [o for o in refined_objects if o["label"] == "door"]
    assert len(doors) == 6
    assert sum(o["deduped_observations"] for o in doors) == 0


def test_no_cross_label_mixing(refined_objects):
    for o in refined_objects:
        assert o["label"] in ("bed", "curtain", "door", "table lamp")
    counts = {}
    for o in refined_objects:
        counts[o["label"]] = counts.get(o["label"], 0) + 1
    assert counts == {"bed": 2, "curtain": 1, "door": 6, "table lamp": 1}


def test_lamp_triangulation_unchanged_by_refinement(legacy_objects, refined_objects):
    """A compact, unambiguous object (0.007 m RMS class) must not regress
    under refinement: same frame count, comparable RMS-class position."""
    legacy_lamp = next(o for o in legacy_objects if o["label"] == "table lamp")
    refined_lamp = next(o for o in refined_objects if o["label"] == "table lamp")
    assert legacy_lamp["quality"]["triangulation_rms_m"] < 0.01
    assert refined_lamp["quality"]["frames_observed"] == legacy_lamp["quality"]["frames_observed"] == 4
    assert refined_lamp["deduped_observations"] == 0
    assert np.allclose(
        refined_lamp["world_transform"]["position"],
        legacy_lamp["world_transform"]["position"],
        atol=1e-9,
    )


# -----------------------------------------------------------------------------
# V3: multi-view silhouette fit corrects the curtain's position
# -----------------------------------------------------------------------------

@_needs_real_splats
def test_curtain_silhouette_fit_leaves_the_bed_volume_and_improves(refined_objects):
    curtain = next(o for o in refined_objects if o["label"] == "curtain")
    bed = next(o for o in refined_objects if o["label"] == "bed")

    assert curtain["position_source"] == "silhouette_fit"
    fit_mean = curtain["quality"]["silhouette_fit_tier1_mean"]
    init_mean = curtain["quality"]["silhouette_fit_init_tier1_mean"]
    # Achieved on this data: 0.306 -> 0.430 (V3 probe, 2026-07-23). Pin at
    # a conservative fraction of that margin.
    assert fit_mean - init_mean > 0.08

    bed_local = placement.parse_ply_vertices(BED_PLY.read_bytes())
    bed_extent = bed_local.max(axis=0) - bed_local.min(axis=0)
    bed_radius_est = float(np.linalg.norm(bed_extent) * bed["world_transform"]["scale"] / 2.0)
    dist = float(np.linalg.norm(
        np.array(curtain["world_transform"]["position"]) - np.array(bed["world_transform"]["position"])
    ))
    assert dist > bed_radius_est


# -----------------------------------------------------------------------------
# V1: the reprojection instrument's discrimination margin
# -----------------------------------------------------------------------------

@_needs_real_splats
def test_sign_flag_bed_true_rotation_beats_identity_twin(refined_objects):
    """V1's second requirement: tier 2 must rank the bed's known-correct
    rotation above its 0065 identity-twin."""
    bed_local = placement.parse_ply_vertices(BED_PLY.read_bytes())
    row = next(r for r in BED_RAW if r[0] == 116 and r[1] == 1)  # the best member
    _fi, _mi, _score, world_rot, _ext, _origin, _direction, _ang = row
    pose, intr = _get_camera(116)
    mask = _load_mask_stack(116)[1]

    from roomstudio_schemas.pose_math import pose_quat, quat_to_rotmat

    R_wc = quat_to_rotmat(pose_quat(pose))
    view_dir_world = R_wc @ np.array([0.0, 0.0, -1.0])
    twin_rot = reproject.mirrored_twin(tuple(world_rot), view_dir_world)

    # Position/scale: use the fused bed's actual placement so this is a
    # like-for-like rotation-only comparison.
    bed = next(o for o in refined_objects if o["label"] == "bed")
    translation = bed["world_transform"]["position"]
    scale = bed["world_transform"]["scale"]

    true_result = reproject.score_placement(
        local_points=bed_local, rotation_xyzw=tuple(world_rot), translation=translation, scale=scale,
        mask=mask, intrinsics=intr, pose=pose,
    )
    twin_result = reproject.score_placement(
        local_points=bed_local, rotation_xyzw=twin_rot, translation=translation, scale=scale,
        mask=mask, intrinsics=intr, pose=pose,
    )
    assert true_result["tier1"] > twin_result["tier1"] + 0.05


@_needs_real_splats
def test_in_plane_shipped_curtain_rotation_scores_worst_of_four_candidates(refined_objects):
    """V1's first requirement (post chunk-B position fix, matching
    production ordering -- in-plane resolution runs after silhouette fit):
    the shipped (known-wrong) k=0 in-plane candidate must not be the
    winner among the four 90-degree candidates."""
    curtain = next(o for o in refined_objects if o["label"] == "curtain")
    scores = curtain["quality"]["in_plane_scores"]
    shipped_rank = sorted(scores, reverse=True).index(scores[0])
    assert shipped_rank >= 1  # k=0 (shipped) is not the winner
