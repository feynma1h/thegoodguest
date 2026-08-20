# 0199 — the inline cache destroys itself by being used

**Date:** 2026-08-20
**Status:** Decided; fixed and measured

## Context

Decision 0182 left one question open: `perception-obj` builds sometimes cost
10 minutes and sometimes 60, and "why it missed was not determined". It named
the first place to look — `BUILDKIT_INLINE_CACHE=1` exports only what a build
itself produced — and it stopped there, because the session that found it was
buying a candidate image for a bench, not characterising a cache.

That open question has a bill attached. This session needed one perception
build to ship the colour work, and needed to know in advance whether it was
buying 10 minutes or 60.

## What we tried

**First, the production record, which nobody had lined up.** Seven
`perception-obj` builds since the cache was introduced, with durations from
`gcloud builds list`:

| build | date | duration | cache |
|---|---|---|---|
| `ec0b1280` | 08-09 | 57m48s | miss (seeding) |
| `5ab7cb34` | 08-09 | 58m38s | miss |
| `ca372cd8` | 08-13 | 10m35s | **hit** |
| `57c8fe26` | 08-15 | 62m47s | miss |
| `05372f5f` | 08-20 | 8m08s | **hit** |
| `72615550` | 08-20 | 59m48s | miss |
| `abc949ec` | 08-20 | 8m13s | **hit** |

**It alternates, without a single exception.** Every build that missed
published a cache the next build hit; every build that hit published a cache
the next build missed. Five transitions, five agreements. The pattern also
explains 0182's own two data points, which were read at the time as an
unexplained anomaly: `57c8fe26` missed because `ca372cd8` had hit, and the
cancelled `18dbff02` before it missed for the same reason. Both were
source-only changes, which is exactly the case that should hit everything up
to the source `COPY` at Dockerfile line 187.

**Then the mechanism, causally, on a three-layer probe.** Production evidence
of an alternation is consistent with the inline-export hypothesis but does not
establish it — a confound in what those particular branches changed would look
the same. So the same cycle was run on a throwaway image small enough to
iterate in seconds: `alpine` plus three `RUN sleep 8` layers plus a final layer
keyed on a build arg that changes every run, which is the production shape
(expensive stable prefix, cheap changing tail). Six Cloud Build runs, each on
its own fresh VM so no local daemon cache could leak between them.

| run | inline (`--cache-from` + `BUILDKIT_INLINE_CACHE=1`) | registry (`--cache-to type=registry,mode=max`) |
|---|---|---|
| 1, cold | 27 s | 35 s |
| 2, off run 1's cache | **2 s** — hit, layers `CACHED` | **12 s** — hit |
| 3, off run 2's cache | **28 s** — miss, cold again | **10 s** — hit |

The inline arm reproduces the production alternation exactly, in 57 seconds of
build time. The registry arm does not degrade.

**buildx availability was probed before anything was committed to it.**
`gcr.io/cloud-builders/docker` carries `docker-buildx v0.23.0` at
`/usr/libexec/docker/cli-plugins`, and a second probe confirmed the part that
actually had risk: the `docker-container` driver authenticates to Artifact
Registry for `--push` and for `--cache-to type=registry` without any extra
credential wiring. Both probes cost under 30 seconds, against a 60-minute
build that would otherwise have discovered a credential problem at the end.

## What we chose

Build `perception-obj` with `docker buildx` on the `docker-container` driver,
importing and exporting a **registry** cache at the same stable `:buildcache`
ref, `mode=max`. buildx pushes the image itself, so the separate push step and
the `images:` list are gone — the docker-container driver leaves nothing in the
local daemon for Cloud Build to push.

`:buildcache` now holds a cache manifest rather than a runnable image. Nothing
ever deployed it, and decision 0190's cleanup policy keeps it by TAG, so it
stays protected exactly as before.

## Why

**The inline exporter writes cache records only for layers the build actually
executed.** A build that reused fifteen layers and rebuilt three publishes a
cache describing three layers. The next build finds nothing for the expensive
prefix and rebuilds from `apt-get` down — and, being a full build, republishes
a complete cache, which is why the third build is fast again. The cache is not
merely lossy; it is *anti-correlated with its own success*, and the better it
works on one build the worse the next one is. The registry exporter
re-publishes records it imported as well as ones it produced, which is the half
inline structurally cannot do.

**The economics decided the timing.** The steady state was one 60-minute build
in every two, so the mean was roughly 34 minutes and the variance was the part
that actually hurt: nobody could tell in advance which build they were buying.
Against that, this session's build was going to miss regardless —
`abc949ec` hit, so its cache was already degraded before this session started —
so switching cost **nothing** in wall time here. The fix is free precisely
once, on a build that was already going to be slow, and this was that build.

**It also removes a trap 0182 flagged as structural.** That note's real worry
was that "the cache is the only thing keeping this build reproducible", with
three unpinned upstream references behind it. A cache that reliably works is
not a fix for the unpinned references, but a cache that fails every other build
was actively hiding how often the build reaches outside itself.

## What would change this decision

If a perception build misses the cache when the previous build succeeded, the
alternation is back and this note is wrong about the mechanism — check whether
`--cache-to` actually ran (a build that fails after the export step still
publishes; one that fails during it does not).

If the Dockerfile ever grows real multi-stage structure, `mode=max` is already
the correct setting and nothing changes. If the cache ref is ever moved off the
`buildcache` tag, decision 0190's Keep rule must move with it — that tag is the
only thing standing between the cache and the delete rule.

## Outcome

**The prediction was registered before the build and it held.** `abc949ec` had
hit, so `:buildcache` was already degraded and this session's build was
forecast to miss at roughly 58-63 minutes. Build `e13c8a70` **missed and took
53 m 58 s** (54 m 51 s wall) — the right side of the prediction, a few minutes
under the band.

**The fix then measured on the real Dockerfile, not just the probe.** A second
build of the same tree, importing the registry cache the first one published,
came back **49 of 49 steps `CACHED` in 0 m 40 s**. Every layer imported,
including the `apt-get`/`git clone`/`mamba env create` prefix that the inline
cache had been dropping.

**Read that 40 s correctly.** It is a no-change build: identical source, so
even the source `COPY` layers hit and the push found every layer already in the
registry. A normal build changing `services/perception-obj/*.py` still has to
rebuild and push from Dockerfile line 187 down, which is the historical 8-10
minute figure. What the fix buys is not a faster hit — it is that **the hit is
now repeatable instead of alternating**. The steady state goes from
`8 min, 60 min, 8 min, 60 min` to `8 min` every time, and the 60-minute build
returns only when something genuinely invalidates an early layer.

So the number for the next person: **expect ~8-10 minutes for a source change,
and treat a 60-minute build as a signal that an early layer really did change**
— no longer as the coin-flip it used to be.
