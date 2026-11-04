# 0295 — the detector stays out of git, and this is how to rebuild it

**Date:** 2026-09-15
**Status:** Decided — Debug builds only; no Release, TestFlight or App Store build carries the model

## Context

RoomPlan boxes sixteen categories, and the operator wants live 3D boxes during
capture for everything else a home holds — lamps, plants, rugs, mirrors, artwork.
The approach was settled before this note (a licensing and feasibility search on
2026-09-14): Ultralytics **YOLOE-26 in prompt-free mode**, the only
open-vocabulary detector with published real-time iPhone speed, lifted into 3D by
our own depth code and shown as boxes in Debug builds only.

Three facts constrain where the model may live:

- **YOLOE's code and weights are AGPL-3.0.** This repository is public and its
  LICENSE is all rights reserved. A build installed from Xcode onto the operator's
  own phone is private use; anything distributed needs Ultralytics' Enterprise
  License, whose price is unpublished.
- **Prompt-free only.** Setting our own text classes runs Apple's MobileCLIP, whose
  weights are research-only.
- **YOLOE trained on Objects365**, which is academic-use only. That question belongs
  to the Enterprise License, not to any build here.

## What we tried

All measured on the Mac (Apple M4, Core ML, `computeUnits = .all`) on 2026-09-14/15,
against a PyTorch reference run of the same head in export mode on the same
letterboxed input.

**The full built-in vocabulary (4,585 names).** `yoloe-26n-seg-pf` at 640 px, FP16:
p50 **23.5 ms** — and it returns the WRONG NAMES. The end-to-end head emits the
class index as a float, and an FP16 graph represents integers exactly only up to
2048; above that, odd indices round to their even neighbours. On the Ultralytics
bus image PyTorch reports three people at 0.91, 0.90 and 0.86; Core ML reports three
**humidifiers** at the same boxes and scores — `person` is index 2163, `humidifier`
2164. For live boxes that is worse than a wrong label: a person misnamed is a
person not excluded, boxed and logged as furniture (0089).

**The class-wise top-k** the export uses by default packs anchor × class into one
index — up to 300 × 4,585 — through the same arithmetic, and fills its 300 rows
with synonyms of the largest objects ("recreational vehicle", "bus", "city bus",
"ambulance" on one box).

**A 235-name vocabulary, class-agnostic.** The prompt-free head scores anchors
against its vocabulary with plain linear layers, one per detection level, whose
rows ARE the vocabulary: keeping only the rows for the names we want restricts the
model to them exactly, with the checkpoint's own embeddings and no text encoder.
With class-agnostic top-k:

| export | Core ML p50 (M4) | agreement with PyTorch |
|---|---|---|
| n, 640 px | **5.7 ms** | same labels and boxes; mask IoU 0.986–0.995 |
| s, 640 px | **9.0 ms** | same labels and boxes; mask IoU 0.988–0.997 |
| s, 512 px | **5.4 ms** | same labels and boxes; mask IoU 0.994–1.000 |

No MobileCLIP file was fetched at any step: after every export the home directory
was searched and holds none.

## What we chose

**The export lives outside git.** It is dropped into
`ios/TheGoodGuest/TheGoodGuest/LiveBoxes/Model/`, which is gitignored; Xcode
compiles whatever is there into a Debug bundle, generates no class for it
(`COREML_CODEGEN_LANGUAGE = None`), and excludes model packages from Release builds
(`EXCLUDED_SOURCE_FILE_NAMES`). The app finds exports by file name and loads them by
URL, so a checkout without one builds and passes its tests (the model tests skip); the feature runs with the
detector reported missing.
`tools/test_live_boxes_boundaries.py` pins the boundary against the tree.

**The vocabulary is the app's table.** `DetectorVocabulary.entries` lists every
exported name, in export order, with what it means to live boxes; the model's own
metadata carries its names, and `LiveBoxesModelTests` fails if the two disagree.

**Three exports are bundled** so size and resolution can be chosen on the phone
from measurements: `yoloe26s_pf_app_640` (opened first), `yoloe26n_pf_app_640`
and `yoloe26s_pf_app_512`.

## How to rebuild it, exactly

1. **An environment outside the repository.** Python 3.12 (the shared `.venv` is
   3.14, which coremltools does not support): `uv venv ~/.venvs/tgg-live-boxes
   --python 3.12`, then install `ultralytics==8.4.152`, `coremltools==9.0` and
   `numpy==2.3.5` (the exporter refuses newer numpy). torch 2.14.0 arrives with
   ultralytics; coremltools warns that version is untested, and conversion succeeds.
2. **The official checkpoints**, from Ultralytics' `v8.4.0` assets release:
   `yoloe-26n-seg-pf.pt`, sha256
   `2829871406fcdb7f36b44af4e534960402626b7c27b3f8b9b42dee6a05fbff6e`, and
   `yoloe-26s-seg-pf.pt`, sha256
   `9f0cefea64c48103a917dbc8ea4baf581aaf6ffa286675861dafd6fd04826f50`.
3. **The names**: those in `DetectorVocabulary.entries`, in that order (235).
4. **Restrict the head.** The prompt-free head keeps one vocabulary layer per
   detection level (`lrpc[i].vocab` on the model's last module — a `Linear` for the
   first two levels, a 1×1 `Conv2d` for the third). For each, keep only the weight
   and bias rows at the chosen names' indices in the checkpoint's own `names`, in
   the table's order. Set the head's `nc` to 235 and `no` to `nc + 4·reg_max`, and
   the model's `names` to the list. Nothing is derived from text.
5. **Export to Core ML** with `imgsz` 640 (or 512), `nms=False`, `quantize=16`,
   `max_det=300`, `agnostic_nms=True`, `batch=1`, `dynamic=False`. `nms=False` is
   load-bearing: the default (`None`) disables the end-to-end head, and the app
   reads only that head's output.
6. **Name and drop.** `yoloe26{n|s}_pf_app_{640|512}.mlpackage` into
   `LiveBoxes/Model/`. The app recognises exports by the `yoloe` prefix.
7. **Check** by running `LiveBoxesModelTests`: the export loads, is the end-to-end
   head, every name is in the table, and a pass runs on a synthetic frame.

The package's bytes differ between runs — its metadata carries the export time —
so the checkpoint hashes and these parameters are its reproducible identity, not a
package hash. The scripts that did the above import ultralytics and are kept
untracked under the operator's `outputs/live-boxes/export/`; they must never be
committed.

## Why

**Git is distribution.** The branch is pushed to a public remote, and a model file
in history cannot be taken back. Live boxes in a Debug build is private use on the operator's
phone; what a distributed build would need is the Enterprise License, and that
negotiation is not a build setting.

**The vocabulary is a correctness requirement before it is a speed one.** The FP16
index arithmetic is silent — the model loads, runs and returns plausible rows — and
the first casualty is the exclusion of people. Below 2048 names with class-agnostic
top-k, every index the graph emits is an exact integer; the decoder additionally
drops any row whose class is not one.

**Restricting rows is still prompt-free.** No name is written and no text is
encoded; the model scores exactly as before against the names it keeps.

## What would change this decision

- **An Ultralytics Enterprise License** makes a distributed build possible. The
  model still stays out of git; the Release exclusion becomes a build choice rather
  than a boundary.
- **An export that emits integer class indices**, or keeps the index arithmetic in
  FP32, makes the full vocabulary exact again — though still four times slower.
- **A commercially licensed detector** with comparable measured speed replaces
  YOLOE, and this note with it.
