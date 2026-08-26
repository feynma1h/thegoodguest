# 0262 — the overlap sort is flat, and its tie-break is capture order

**Date:** 2026-08-27
**Status:** Decided (measured; no behaviour change)

## Context

0261 found the per-box shortlist taking the shorter of two `desk` masks and
named the cause as a metric with no recall term. It left three checks open.
0263 answers them. This note records what running them turned up underneath —
a defect with nothing to do with duplicate masks, and one that nothing in the
pipeline reports because it does not look like a failure.

## What we tried

`box_placement.associate_observations` and `mask_overlap_with_hull` are GPU-free,
so production's association runs offline. Two corpora, and the second is the one
that matters:

- **`90eebfc4`**, the new room, over the 19 preserved probe frames
  (`outputs/capture-90eebfc4/segment_probe/`). The replica reproduces 0261's
  desk overlaps to four decimals, which is the trust gate.
- **The four preserved captures**, over production's OWN per-frame `masks.npz`
  and `objects.json` under `outputs/room-quality/cache/` — real pipeline masks,
  not probe ones, on 48 frames across rp7, rp6g1, rp6g2 and spike.

The shortlist sorts `(-overlap, frame_index, mask_index)`. When the first key
ties, the second decides — and the second is **the order the frames came off the
phone.**

| pool | candidates | per box | overlap **exactly 1.0000** | boxes with a tie at the top | boxes where ALL candidates tie |
|---|---|---|---|---|---|
| four preserved captures | 66 | 2.5 | **18 (27%)** | 5 of 26 | 2 |
| `90eebfc4`, its sampled frames | 16 | 3.2 | **10 (62%)** | 3 of 5 | 2 |
| `90eebfc4`, all 19 probed | 52 | 10.4 | **31 (60%)** | 4 of 5 | 1 |

Per room the saturation rate is **rp7 39%, rp6g1 42%, spike 19%, rp6g2 0%,
`90eebfc4` 62%** — so it is real across the corpus and varies enormously by
room. `90eebfc4` is the extreme, not the typical case, and its 62% on its own
sampled frames rules out the probe's frame choice as the explanation.

**Candidates per box is the confound** and is why only the saturation RATE is
comparable between rows: a box with two candidates cannot show the tie rate of
one with ten.

What it costs is concrete. In `90eebfc4`, frame 24 won `box_05` on index with
**17.6% of that box inside the image**, while frame 45 at **87.5%** tied with it
at 1.0000 and lost on being sampled later. `box_03`'s chair is the same shape:
frames 0, 24, 45 and 109 all score exactly 1.0000, and
`outputs/segment-quality/flat-metric.png` puts a hard-cropped seat beside a whole
chair with both armrests at the same score.

**Three explanations for WHICH candidates saturate were tested and none
generalises.** They are recorded so nobody re-runs them:

1. **Border contact** — a mask running off the image edge has no pixels left
   outside the hull to be penalised with. Strong on `90eebfc4` (median in-frame
   fraction 0.720 for saturated candidates against 0.978 for the rest) and
   **absent corpus-wide** (0.847 against 0.901).
2. **Hull slack** — the projected box being much larger than the mask.
   **Refuted, in the wrong direction:** saturated candidates have LOWER median
   slack than the rest, 2.68 against 3.79 corpus-wide.
3. **"Nothing is wrong with this candidate"** — clean candidates (no border
   contact, no nested sibling) at 53% against 62% for the rest. No separation.

## What we chose

Nothing. This note records the measurement; the only rule proposed anywhere is
0263's, which is about a different failure.

Two things a fix must not be. **Not a threshold re-tune** —
`PLACEMENT_BOX_MATCH_MIN` gates admission and no value of it un-flattens a score
that reads 1.0000 for a quarter of all candidates. **And not a new sort key that
predicts reconstruction quality**, which is what 0146/0152/0162/0197 retired
eleven times.

## Why

**A tie-break is not a decision, and this one is invisible.** Every artifact the
pipeline emits records which frame it used; none records that the choice was
arbitrary. A manifest reading `source: {frame_index: 24}` looks identical whether
the metric preferred that frame or whether ten candidates tied and 24 sorted
first. That is why this survived: nothing lies, and nothing says.

**It reframes 0261 by size.** That note read the desk pair as the metric
preferring truncation. Nested pairs are real (0263) but they are 21 pairs across
five captures; the flat tie-break decides a fifth of all boxes, every room, every
run. The rare case was visible because two masks of one object are conspicuous;
the common one was invisible because a tie looks like a choice.

**And it puts the two selection stages in the same hole.** 0259 refused a frame
whose object runs off the image. The shortlist is a second selection stage, over
the frames the sampler already chose, and it asks nothing about whether the
object is in the picture. Fixing one and not the other leaves a room whose
sampler picked well and whose shortlist then picked arbitrarily among what it was
handed.

**That no mechanism was found is itself worth knowing.** The obvious story —
cut masks score 1.0 because they are cut — is true of the one room that prompted
this and false of the four that did not. Anyone proposing a targeted fix should
be able to say which candidates it fires on; three attempts to characterise them
have failed.

## What would change this decision

**A mechanism.** Any measure that separates saturated candidates from the rest
across all five captures makes a targeted fix possible; without one, the honest
options are to change the tie-break to something meaningful or to accept that a
quarter of box views are chosen by capture order.

**The cheapest unclosed measurement is `90eebfc4`'s other seven sampled frames.**
Only 5 of its 12 were ever segmented (0, 24, 45, 95, 109), so every claim about
what its full shortlist ranked is over a subset — frames 11, 59, 86, 124, 136,
158 and 175 could hold a candidate that changes a box's order. ~30 s on the
0%-traffic `/segment` candidate, no reconstruction:

    python3 tools/segment_frames.py 03e1d3ff-f561-46b7-b264-def786a14e26 \
        --frames 11,59,86,124,136,158,175 --candidate

**rp6g2's 0% is not evidence of health.** That room's last 28 keyframes are
black (0235/0240) and only 13 candidates associate at all across 12 frames. Read
it as a room with too little to rank rather than as a room the metric ranks well.
