# roomstudio

A spatial intelligence platform: capture a room with an iPhone, get a per-object 3D-Gaussian-splat scene you can edit in a browser.

This file is the always-current state of the project. Both Claude Code (reads it automatically) and Claude Chat (you upload it) consume it at the start of every session. If something in here is wrong, fix it before doing anything else.

## What we're building

A premium consumer product with three surfaces:

- **iOS capture app** (Swift + ARKit + RoomPlan) — capture-only, no viewer. The app's only job is producing a high-quality capture bundle and uploading it. Users come to the web for everything else.
- **Backend perception pipeline** (FastAPI on Cloud Run, `asia-southeast1`) — ingests bundles, runs SAM 3 segmentation + SAM 3D Objects reconstruction, places objects in the room's gravity-aligned metric frame using ARKit data, generates inpainted scene-3DGS for walls/floor.
- **Web app** (Next.js + WebGPU splat rendering) — the actual product. Browse, edit, replace, share scenes. Capture path is one screen: "Open the iOS app."

Photo-upload (Android, no-iPhone users) is a deferred concern. Until the iOS path is solid we don't build the web-fallback capture.

## Capture bundle — the central contract

Everything between iOS and the backend flows through `packages/schemas/capture_bundle.proto`. The bundle is metadata; pixel data (frames, depth) lives in GCS by reference.

Frame of reference is **ARKit-native** end-to-end: right-handed, +Y up, camera looks down -Z in its local frame. The iOS client does NOT transform; the backend converts to downstream model frames (e.g. SAM 3D's per-object frame) when it has to.

Pose is **position + unit quaternion (x, y, z, w)**, not a 4×4 matrix. ARKit-native, ARCore-native, glTF-native. 7 floats instead of 16. The proto file's docstring carries the full reasoning.

Quaternion math is centralized in `packages/schemas/roomstudio_schemas/pose_math.py`. Any Python that touches a Pose imports from there. Do not re-implement.

## Repo layout

```
packages/schemas/                 capture bundle proto + generated Python + pose math
  capture_bundle.proto              source of truth
  roomstudio_schemas/
    capture_bundle_pb2.py            generated; regen with ./tools/gen_proto.sh
    pose_math.py                     quaternion ops; one place to change
  tests/                              25 invariant tests, all green

tools/                            local scripts (run from repo root)
  gen_proto.sh                      regenerate Python (and Swift, when iOS exists)
  build_test_bundle.py              synthesize a bundle from test_data/photos
  inspect_bundle.py                 verify a bundle parses + smoke-checks

services/
  api/                            (planned) bundle ingester orchestrator
  perception-obj/                 SAM 3 + SAM 3D Objects (deployed)
  perception-geom/                VGGT for the photo-upload path (deployed, photo-path only)

infra/                            Cloud Build configs, deploy scripts
docs/decisions/                   short notes on dead-ends — see "When to write a decision note"
test_data/photos/                 9 HEIC photos of a real room, for synthesis testing
outputs/                          gitignored; generated artifacts
```

## What works right now

- The capture-bundle contract is defined, generated, and tested. `python tools/build_test_bundle.py && python tools/inspect_bundle.py outputs/test_bundle/bundle.pb` runs clean end-to-end.
- The photo-upload pipeline (`perception-obj`, `perception-geom`) is deployed and produces per-object splats from photo uploads. It's the old path; we're keeping it alive but not iterating on it.
- 25 schema + math tests, all passing. Don't break them.

## What does NOT work / what we're deliberately not doing

- **No iOS app exists yet.** The bundle synthesizer is the only thing that writes bundles.
- **No backend bundle ingester exists yet.** Nothing reads bundles in production. `tools/inspect_bundle.py` is the closest thing.
- **No web app yet.**
- The photo-upload composition path (`_compose_scene` in `perception-obj`) has unsolved per-object orientation issues. We are NOT fixing them. The iOS path replaces all of it.
- The pre-VGGT pydantic schemas (`packages/schemas/room_perception.py`, `spatial_graph.py`) are old Layer 1/2 work. Don't touch.

## Conventions

- Python 3.11+. Ruff for lint/format (config at `pyproject.toml`).
- Frame of reference: ARKit-native everywhere on the wire. Convert at the boundary, not in transit.
- Coordinates: right-handed, +Y up, meters.
- Quaternions: `(x, y, z, w)`, unit norm within 1e-3.
- GCS paths in the bundle are RELATIVE to the bundle prefix, not full `gs://` URIs.
- File creation: every long-lived file gets a docstring explaining what it's for and who reads it. No "test code anyway" justifications for shortcuts.
- Tests pin invariants, not implementation. They should still pass after a refactor.

## Tooling conventions

Default model for routine work: **Sonnet 4.6**. Switch to **Opus 4.7** for hard reasoning (coordinate-frame conversions, perception-pipeline architecture, anything where a wrong answer propagates). Haiku 4.5 is not in use yet.

Default tool for code work: **Claude Code**. Default for strategy / architecture decisions: **Claude Chat**. See `.claude/WORKFLOW.md` for the full rubric and prompt templates.

Insert this section into CLAUDE.md, immediately after the "Tooling conventions" section and before "When to write a decision note":

## Git conventions

This repo is tracked with git. Local-only as of now; no remote yet.

**Claude Code's role with git:**

- Commit as part of normal work. One commit per logical unit (a feature, a fix, a refactor — not "end of session"). If a session produces multiple distinct changes, that's multiple commits.
- Write descriptive commit messages: what changed and why, not just what. Subject line under 72 chars; add a body if the why isn't obvious from the subject.
- Run `git status` and `git diff` before committing, and surface anything unexpected (e.g. a file changed that wasn't part of the task). Don't `git add -A` blindly.
- Do NOT push to remotes. The user pushes manually after reviewing. (As of now there is no remote anyway, but this rule pre-applies for when one is added.)
- Do NOT rewrite history (`git rebase`, `git commit --amend` on already-committed work, `git reset --hard` on commits you didn't make this session) without asking.
- Do NOT delete branches or force-anything.

**Session-end housekeeping commits:** the CLAUDE.md updates and any decision-note additions from session-end housekeeping should land in their own commit, separate from the code changes that prompted them. Message convention: `docs: session housekeeping — <one-line summary of what changed>`.

**What's gitignored:** see `.gitignore`. Notably: `outputs/`, virtualenvs, `.env`, `.claude/cache/` and `.claude/projects/` (Code's session state). Note that `CLAUDE.md`, `.claude/WORKFLOW.md`, and everything under `docs/decisions/` ARE tracked — they're project documentation, not local state.

## When to write a decision note

`docs/decisions/` holds the *why* behind decisions that aren't obvious from the code. One file per decision, filename `NNNN-short-slug.md` (zero-padded). Template at `docs/decisions/0000-template.md`.

The criteria for "is this worth a note?" live in the session-end housekeeping section below.

## Next on the board

When this section gets stale, the project's drifting. Keep it current.

Three options live as of end of last session (May 2026):

1. **iOS capture app prototype** — Swift + ARKit, emits the bundle. Highest-value because it's the half of the contract that doesn't exist.
2. **Backend bundle ingester** — FastAPI route that ingests bundles, validates, dispatches to perception services. Unblocks option 3.
3. **Adapt `_compose_scene` to consume CaptureBundle** — with ARKit poses/gravity/intrinsics in hand, most of the gravity/up-axis machinery deletes. Depends on option 2.

Recommended order: 2 → (1 in parallel) → 3. Option 2 is testable here against the existing `outputs/test_bundle/bundle.pb`. Option 1 derisks the contract from the side the backend can't verify. Option 3 is where the photo-upload pain actually goes away.

## Session-end housekeeping (Claude Code: do this before ending any session)

Before the session ends — when the user indicates they're wrapping up, when tests are green and the task is done, or when the conversation is winding down — propose the following without being asked:

**1. CLAUDE.md updates.** Show a proposed diff for:
- **"What works right now"** — add anything that started working this session.
- **"What does NOT work / what we're deliberately not doing"** — add anything broken, half-done, or explicitly deferred. Be honest. Half-done is half-done, not "in progress."
- **"Next on the board"** — replace, don't append. This section reflects the present, not history.

Show the diff and ask for approval before writing. Don't write speculatively.

**2. Decision note candidates.** Identify whether anything this session is worth a `docs/decisions/NNNN-slug.md` note. The bar:

- A path was explored and rejected — write one.
- A non-obvious convention was chosen — write one.
- A workaround was applied that looks wrong without context — write one.
- Routine implementation that's self-evident from the code — skip.
- Strategy already captured in CLAUDE.md — skip.

If the bar isn't met, say so explicitly ("nothing this session rises to a decision note") and move on. Don't write notes just to seem thorough. If the bar IS met, draft using `docs/decisions/0000-template.md`, pick the next number, propose, wait for approval.

**3. If neither applies**, say so and end the session cleanly. Not every session changes the state.

The user can short-circuit this with "skip housekeeping" if the session was trivial (e.g. a one-line fix). Otherwise, run through it.

## How history is preserved

CLAUDE.md is the present. Anything historical — abandoned approaches, the reasoning behind a current convention, "we tried X and it didn't work" — goes in `docs/decisions/`, not here. If you find yourself wanting to add "we used to do Y" to CLAUDE.md, that's a signal to write a decision note instead and keep CLAUDE.md focused on what's true now.
