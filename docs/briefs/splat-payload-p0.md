# P0 — a room takes 6–7 minutes to appear

**Status:** BUILT 2026-08-09 on branch `splat-compressed-tier`, not deployed.
Decisions **0123** (network-bound), **0124** (serial signing, measured and
left), **0125** (SPZ is a transcode, not a re-bake), **0126** (the tier sits
beside the PLY), **0127** (the reveal waits for bytes). 0128 unused.

**Outcome:** 275.8 MB → 47.2 MB (5.84×) with Gaussian counts preserved
exactly; 87–93 s → 14–19 s measured on the live bucket. All 12 scene dirs converted
(2,695 MB → 463.8 MB, 5.81×) — the table below lists nine, but there are 12. The reveal now plays its first two movements before any splat
exists and gates the object wave per piece. **Remaining: deploy api-public**
(the tier is inert until `asset_urls_compressed` serves) and **wire the
converter into the pipeline** so new captures are not born slow.

The scoping text below is kept as written, for the reasoning that led here.

**Why this is P0 and above App Store collateral:** this is the core product
experience — the thesis of the whole project is the moment a person sees their
own room — and it had never once been measured over a real network. Every
`/viewer` walk read local fixtures over localhost. Gate B fetched exactly one
34 MB splat with curl, which sends no `Origin` and waits for no renderer.
A curl 200 was never evidence about a browser, and a local fixture is not a
network. This is the third launch-blocking defect to hide behind that same
blind spot (decision 0102 records the other two).

---

## What is measured, and what is assumed

Measured by the coordinator against the live outputs bucket, 2026-08-08.
These are byte-exact `Content-Length` sums over the splats each manifest
references. **Trust these numbers; re-derive nothing here.**

### What the browser actually fetches today (placed objects only)

| scene | splats | total | median splat | largest splat |
|---|---:|---:|---:|---:|
| `b12538fa` | 3 | 106.0 MB | 36.3 MB | 39.4 MB |
| `e2bbc1b2` | 6 | 109.6 MB | 17.0 MB | 25.6 MB |
| `972fc0a8` | 8 | 153.4 MB | 17.7 MB | 40.0 MB |
| `09684dde` | 11 | 212.3 MB | 14.8 MB | 49.7 MB |
| `a71d125f` | 10 | 214.1 MB | 18.2 MB | 46.1 MB |
| `a7e073ae` | 10 | 263.0 MB | 27.6 MB | 49.4 MB |
| `ce68e24f` | 12 | 290.4 MB | 19.0 MB | 50.7 MB |
| `b667f891` | 16 | 350.4 MB | 19.7 MB | 41.3 MB |
| `247003de` | 16 | 390.3 MB | 20.9 MB | 47.0 MB |

**Note the discrepancy with the number the operator reported (684.5 MB across
31 splats): no scene in the bucket matches it.** The magnitude is real and the
problem is real, but the exact figure needs re-measuring against the room the
operator actually opened — get that from them. `b667f891` read across *all*
its signed URLs is 816 MB / 40, which brackets it from above; several scenes
have been re-driven since, which changes object counts. Do not carry 684.5/31
forward as fact.

**The dominant term is per-splat size, not splat count.** A single cabinet in
`a7e073ae` is 44 MB. Rooms are 3–16 objects; that is not the problem.

### Two hypotheses already killed — do not spend a session re-testing them

1. **"We're downloading the unplaced inventory too."** False.
   `assembleScene` (`web/src/lib/api/types.ts:360–385`) builds a
   `PositionedSplat` only when `obj.placed && obj.world_transform && url`;
   everything else goes to `unrenderable`, which is a text list. The client
   fetches the rendered set and nothing more.

2. **"The landing page is affected."** False. The hero is shell geometry only
   — `web/public/hero/room.json`, 3,557 bytes, zero splats (decision 0122).
   `/` is fine. This is `/room` and `/viewer`.

### One real finding, adjacent and cheap

`GET /scenes/{id}/assets` signs **every** splat URI in the manifest, placed or
not, in a **serial** loop (`services/api-public/public_server.py:1294–1311`).
Each `generate_signed_url` under `IamV4UrlSigner` is an IAM signBlob network
round-trip. Wasted signatures per scene: `b667f891` 24 of 40, `e2bbc1b2` 16 of
22, `a7e073ae` 12 of 22, `09684dde` 9 of 20.

That is time-to-first-byte the user waits through before a single splat
starts. **Measured 2026-08-09 from production logs: 0.9–2.6 s**, scaling with
signed-URI count. Real, but under 1% of the wait — recorded and deliberately
not fixed in decision 0124, with the trigger for revisiting it.
There is precedent for the fix shape if it turns out to matter: decision 0074
found the same serial-round-trip pattern in `_mint_all` and cured it with a
bounded order-preserving pool (`UPLOAD_SESSION_MINT_CONCURRENCY`). Filtering
to placed-only is a separate, smaller, and independently correct change —
but check first whether anything else consumes `asset_urls` for unplaced
objects before narrowing the contract.

---

## The question that decides everything else — ANSWERED 2026-08-09

**It is network-bound, decisively. Decision 0123 carries the measurements;
this section is kept for the reasoning that led to them.** Parse plus GPU
upload is 0.6–3 s for a 275.8 MB room in the shipped renderer — under 1% of
the wait — so the "fewer Gaussians" branch below is NOT the lever for this
symptom. Bytes on the wire are. Two further measured results bound the fix:
generic gzip buys only 1.36× (float32 is high-entropy, so serving the
existing PLYs compressed is not the cheap win it looks like), while
quantization to an SPZ-class layout buys ~4.3× at 0.006 mm position error.
About 10% of the payload is downloaded and then discarded outright.

Also refuted along the way, so nobody re-tests them: signed-URL churn does
**not** remount the viewer (the shell-grace refetch completes before mount),
and a browser's single HTTP/2 connection to `storage.googleapis.com` is not
a throttle — it was the *fastest* client measured.

**The original question, for the record:**

~300 MB in ~6.5 minutes is ~6 Mbps effective. That is slow for a download on
a decent connection and entirely plausible for PLY→Gaussian parsing and GPU
upload. Nobody has separated the two terms.

- If **network-bound**: a compressed tier is the big lever. SOG/SPZ/quantized
  formats are typically 10–20× smaller than uncompressed PLY, which would put
  a 290 MB room at 15–30 MB.
- If **parse-bound**: a smaller wire format that still decodes to the same
  Gaussian count buys much less than it looks like, and the real lever is
  **fewer Gaussians** — decimation and LOD. Building compression first would
  be weeks spent on the wrong term.

Get this measurement before proposing a fix. Per-splat: time to first byte,
time to last byte, and time from bytes-complete to on-screen, separated.

**Also get the operator's console errors.** They saw errors and nobody has
captured them. They may be the whole story or unrelated; either way, guessing
is not allowed here.

### Getting a real measurement without a sign-in

Loading a real room on production needs sign-in, and sign-in is a popup flow
that the Browser pane blocks (this is recorded in memory and confirmed — it is
an automation artifact, not a product defect). Three routes, in preference
order:

1. **Ask the operator for a HAR** from their own browser on
   `https://roomstudio.web.app`, plus the console log. They are already signed
   in. This is the highest-fidelity option and the smallest ask.
2. **Separate the terms without a browser session**: mint signed URLs
   server-side, then (a) `curl` them to get the pure network term over this
   machine's connection, and (b) load the same real URLs into a local page
   that runs the actual `SplatViewer` to get the parse/upload term. The
   download leg is genuinely real — same bytes, same GCS, same signatures —
   even though the page is served locally. State plainly in the report which
   legs were real and which were not.
3. A throwaway UID with a re-drive is available but expensive; do not reach
   for it before 1 and 2.

---

## The reveal is coupled to this, and it is an honesty problem

The 0097 choreography runs ~11.7 s for the spike room and has never been
walked by the operator. At 290 MB it needs ~200 Mbps sustained to play as
designed; at the operator's reported room, ~470 Mbps. **It cannot honestly
play today** — it would narrate a room assembling itself while the room is
still arriving, which is precisely the class of dishonesty this project
refuses everywhere else (a reveal that shows a piece landing before its bytes
exist is a guessed transform in a different costume).

The elegant resolution is already latent in the design: **the reveal's score
is largest-first, and so is the ideal load order.** Progressive loading driven
by `web/src/lib/reveal.ts`'s existing ordering makes load order and narrative
order the same thing, and the reveal becomes the honest surface for waiting
rather than a lie told over it. That is a direction, not an instruction —
if the measurement says otherwise, say so.

---

## Decisions that are the operator's, not the session's

**Two of the three are now DECIDED (operator, 2026-08-09):**

- **The compressed tier SITS BESIDE the PLY — additive.** The viewer prefers
  the compressed file when present and falls back to the PLY, so no existing
  scene needs a re-bake to stay correct; the nine real rooms keep their
  byte-identical originals, and decision 0070's re-adjudication rule is not
  triggered for rooms nobody re-bakes. Costs roughly 25% more storage. Old
  rooms stay slow until converted — that is accepted, not overlooked.
- **Rooms keep every placed object.** No cap, no dropping the large pieces.
  The room stays complete; compression carries the fix. A 16-object room
  lands near 90 MB rather than 390 MB.

Still open, and NOT decided here — it was offered and not chosen, so treat it
as live rather than rejected:

- **Progressive loading.** Orthogonal to both decisions above: ship everything,
  but drive load order from `lib/reveal`'s existing largest-first score. This
  is the change that makes "time to first object" the number that matters
  instead of time to last byte, and decision 0123 notes it reorders the terms.

Still the operator's, unchanged:
- **Re-baking existing scenes.** Nine real rooms exist, several of them
  regression fixtures and one the hero. Decision 0070's rule — re-adjudicate
  on the reference room before changing what ships — applies to any bake
  change.

## Constraints that are not negotiable

- The splat is a **possession**. Anything staged into `web/public/` must stay
  gitignored *and* in `firebase.json`'s hosting ignore list; `next build`
  copies `public/` into `out/` gitignore and all. This was caught once with a
  44 MB bed one deploy from a public origin (decision 0122).
- Pre-0089 scenes may carry a person in their measurement. Any new bake
  inherits decision 0089's suppression only if the frames are re-segmented.
- `web/AGENTS.md`'s JSX-entity quirk is invisible to eslint, tsc, and the
  build. Verify copy in a **rendered DOM**, not in source.
- Do not `git add -A` without a pathspec.

## Ready report

Per-item outcome with evidence, suite counts, commits, what was descoped and
its re-open trigger, and — separately and explicitly — **what was measured
versus what was reasoned about**, and what was not verified at all.
