# Punchlist — what is left before "finished"

One entry per remaining item, grouped into gates in dependency order. This file
is the working list; `CLAUDE.md` stays the statement of what is true now, and
`docs/decisions/` stays the record of why.

**Rules, which are the same as everywhere else in this repo:**

- **When an item is done or ruled, DELETE it.** Do not annotate it, do not strike
  it through, do not add "(done)". If it deserves a story, the story is a decision
  note. A punchlist that accumulates closed items becomes the retired 207-entry
  tracker again.
- **Add new items freely**, with the same shape: what, why it blocks, and how to
  check it.
- **Every item carries a `Check:` line where one is possible.** Run
  `python3 tools/punchlist_check.py` to have the checkable subset verified against
  the live system. Items whose state is a judgment or an external dependency say
  `Check: manual` and say who decides.

**Why the Check line exists.** This project's recurring failure is not forgetting
work — it is documents quietly going out of date. On 2026-08-26 CLAUDE.md
asserted CI was green while it had been red five days, named three different
serving revisions for one service, and said the phone held no captures when it
held five. An item that can be re-verified in one command cannot rot that way.

IDs are stable. Reusing a deleted ID is worse than skipping it.

---

## Gate 1 — nobody but the operator can use this

No route exists by which a second person obtains this app. Everything here was
gated on Apple Developer enrollment, which cleared 2026-08-23; the device build
verified 2026-08-25, so most of this is newly unblocked rather than newly found.

### G1-01 · No TestFlight build and no App Store submission
**State:** open · **Blocks:** literally every user other than the operator
TestFlight needs only an app record. Submission needs the rest of Gate 1.
**Check:** manual — operator, in App Store Connect.

### G1-02 · `PrivacyInfo.xcprivacy` does not exist
**State:** open · **Blocks:** App Store submission
It ships inside the bundle and submission requires it; the nutrition labels alone
are not sufficient. A complete draft plist is in
`docs/product/privacy-nutrition-labels.md` §9, so this is transcription and an
Xcode project reference, not design.
**Check:** automated — file must exist under `ios/`.

### G1-03 · The privacy nutrition labels cannot be filed
**State:** open · **Blocks:** App Store submission
Four blockers, listed in `privacy-nutrition-labels.md` §10: confirm both model
vendors' retention/training terms (open since 2026-08-08, and the one claim the
Privacy Policy makes on someone else's behalf), rule the two judgment calls
(conversation-surface scope, profile photo URL), rule the server-log question,
and land G1-02.
**Check:** manual — operator; three of the four are rulings.

### G1-04 · App Store collateral: screenshots, support URL, age rating
**State:** open · **Blocks:** App Store submission
Screenshots were waiting on a verified device build and are now unblocked. The
support URL is expensive to change once filed. The icon and privacy labels are
already done.
**Check:** manual — operator.

### G1-05 · The iOS app has no route to the web
**State:** open · **Blocks:** the product loop, and G1-01 in spirit
`NetworkConfig.webBaseURL` is `nil`, so every room row and CTA that would open a
room is correctly disabled. A person who captures a room **cannot reach it from
the app**. Needs associated domains plus universal links; the QR bridge encodes
nothing for the same reason. This is the largest hole in the loop and the only
Gate 1 item that is real engineering rather than a decision.
**Check:** automated — `webBaseURL` must stop being `nil`.

### G1-06 · Gate A — Apple sign-in link on device, UID unchanged
**State:** open · **Blocks:** trusting that a phone capture and a browser session
are the same person
The web half is live-verified; the on-device half has never run. Newly unblocked
by enrollment.
**Check:** manual — operator, on hardware.

### G1-07 · Decision 0115 is still unanswered
**State:** open · **Blocks:** TestFlight
The anonymous-UID churn was flagged as possibly enrollment-gated. Enrollment has
cleared and the Team ID never changed (`3HU2SP8346` across every build), so the
keychain access-group prefix was never a variable — meaning if the churn recurs
it is a real identity-destroying bug and must surface before other people have
rooms to lose. `IdentityContinuity` logs the classification via `os_log`, which
needs `sudo log collect`; the cheaper readout is the reaper's own per-bundle
status codes now that api-public is fixed.
**Check:** manual — operator, next launch.

---

## Gate 2 — what is deployed is behind what is built

### G2-01 · The live web app still carries the old product name
**State:** open · **Blocks:** the name being true anywhere a person can see it
`thegoodguest.web.app` serves `<title>thegoodguest</title>` while the repo has
"The Good Guest". The web has not been deployed since the name landed
2026-08-24. The name is settled (0245); only the deploy is missing.
**Check:** automated — live `<title>` must match the repo's.

### G2-02 · The calling card is built and undeployed
**State:** open
Rung 0 of the sharing ladder, complete, needing no new trust boundary, route,
storage, licence amendment or moderation surface. It ships when the web ships.
Its own remaining question is the operator's eyes on eight batched judgments.
**Check:** rides G2-01.

### G2-04 · The product is silent and the branded fonts are placeholders
**State:** open
`RSSound` is wired at three call sites with no cue files in the bundle; the web
has no sound at all; branded faces fall back to system. Asset-shaped, not
code-shaped.
**Check:** manual — asset delivery.

### G2-05 · The phone can send an FCM token and has never had one
**State:** open
The wire is finished on both sides: `/upload_session` accepts `fcm_token` and
threads it through to the notifiers, and `UploadSessionClient` carries an
`fcmToken` parameter. Nothing fills it — there is no `FirebaseMessaging` import
and no `registerForRemoteNotifications` call anywhere in `ios/`, so the parameter
defaults to nil on every call. Until the phone registers, a room that finishes
while the app is closed is announced to nobody, and the Live Activity's frozen
count (0114) has no remedy.
**Check:** automated — iOS registers for FCM and passes a non-nil token.

---

## Gate 3 — what users are told must be true

### G3-01 · The Privacy Policy overstates upload-bookkeeping retention
**State:** open · **Blocks:** shipping to anyone, independent of the App Store
The published page tells users the record is kept **7 days**. The Firestore TTL
is on `created_at`, so the record expires as it is written and is swept within
about a day. Wrong in three places: `web/src/app/privacy/page.tsx`,
`infra/eventarc_setup.sh`, `services/api-public/account_deletion.py`.
Sharper: `eventarc_setup.sh` contains its own refutation — its `scenes` section
warns never to point a TTL at `created_at`, twenty lines below the section that
does exactly that.
The user-facing wording is the operator's to approve; the two internal copies are
free.
**Check:** automated — the string "7 days" must leave all three files.

### G3-02 · Four further Privacy Policy corrections are drafted, not applied
**State:** open
From `privacy-nutrition-labels.md` §8: server request logs are undisclosed and
outlive "delete everything" (F2); both policy pages are stale on iOS Google
sign-in (F3); §5 describes push as live when it is not built (F4); and §3
understates what a linked provider hands over (F5).
F6 — the camera permission string — is done, and its guard moved into
`tools/test_gen_mark.py`, which now refuses ANY user-visible Info.plist value
carrying the dead name rather than watching that one key.
**Check:** manual.

### G3-03 · There is no per-room deletion
**State:** open · **Blocks:** every sharing rung above the card
The only deletion route is `DELETE /account` — all or nothing. Conspicuous on its
own for a product whose thesis is that rooms are identity, and a hard prerequisite
for any hosted share link: revoking a share and deleting a room are one mechanism
seen from two angles, so a link shipped first would outlive every means of
stopping it.
**Check:** automated — a per-room delete route must exist in `public_server.py`.

### G3-04 · Terms §9–§11 need an Indian lawyer
**State:** open
Consumer Protection Act 2019 §2(46) can void the §11 liability cap against a
consumer. Not engaged.
**Check:** manual — operator.

---

## Gate 4 — nothing reports failure

The cheapest gate here, and 2026-08-26 supplied two independent demonstrations of
why it matters: an api-public outage ran ~17 hours undetected, and CI had been
red five days while CLAUDE.md recorded it green.

### G4-01 · Zero alerting and zero uptime checks
**State:** open · **Blocks:** knowing about any of the above
No alert policies, no uptime configs, against three production services and a
scale-to-zero GPU. The deferral has never been recorded either, which makes it
indistinguishable from an oversight.
**Check:** automated — at least one alert policy or uptime check must exist.

### G4-02 · Python CI has been red since 2026-08-21 — fix applied, unproven
**State:** open · the CAUSE is fixed; the entry closes on a green run
The root suite died at collection with `ModuleNotFoundError: No module named
'PIL'`. `tools/test_gen_mark.py` imports Pillow, which was declared only in the
two perception pyprojects and so was absent from what the root job installs via
`tools/ci_deps.py`. The other three jobs passed, so the root suite had not
executed on Linux since.

Pillow is now declared where it belongs — the ROOT pyproject's `dev` extra, the
root project being the one that owns `tools/` — and `python.yml` passes that
pyproject to `ci_deps.py` alongside the other four. That is the one declared
dependency, not a test change.

**This is unproven and must not be assumed done.** Nothing here has run on
Linux; the checker reads the latest GitHub run, which still predates the fix.
Do not delete this entry on the strength of the diff.
**Check:** automated — latest `python.yml` run must conclude success.

### G4-03 · Nothing gates on CI
**State:** open
Separate from G4-02 and the reason it survived five days. Even green, no branch
protection or required check makes a red run stop anything.
**Check:** manual — operator, repo settings.

### G4-04 · Service builds are unpinned, with no lockfiles
**State:** open
Two builds of identical source can install different code, which is exactly what
took api-public down (0246). The incident's own cure was a rebuild rather than a
pin, and a scattering of hand-added pins is the wrong fix — the right one, if it
is worth it, is a lockfile per service.
**Check:** manual — a design decision, not a defect.

### G4-05 · A second Firebase browser key allows 27 APIs
**State:** open
No referrer restriction, against the shipped key's 4 origins and 2 APIs. Closing
it breaks the live-authed-check path recent api-public deploys use, so a
replacement ships first.
**Check:** automated — no unrestricted browser key should remain.

### G4-08 · The scene lease is shorter than the job it protects
**State:** open · **Blocks:** the re-drive tool's safety guard being sound
`SCENE_LEASE_TTL_SECONDS` defaults to 300 s, is unset in the deploy script, and
is claimed after model load, while a request may run to 900 s. Measured over 66
production runs: median lease held **613.5 s**, max **899.8 s**, **46 of 66 past
the TTL** (0286). Nothing has double-processed only because two unrelated things
prevent it — api-internal's 930 s dispatch deadline and `--max-instances=1`.
`tools/reenqueue_scene.py` DOES read the lease to decide whether a worker is
active, so on a live scene it proceeds without `--force` and dispatches a second
task.

The fix is one number: **TTL 960 s**, above the 900 s request ceiling, which
makes "lease live" mean "a worker may be running" — what the tool already
assumes. Also unfixed and part of this entry: `lease_expires_at` is never passed
to `_log_lease_action`, so the field 0011 added for exactly this logs `none`
everywhere.
**Check:** manual — read `SCENE_LEASE_TTL_SECONDS` in `process_receiver.py` and
the deploy script's env; it must exceed the Cloud Run request timeout.

### G4-09 · Non-terminal scenes strand and nothing sweeps them
**State:** open · **Blocks:** a user ever being told their room failed
A scene can sit in `queued` or `processing` forever: no terminal state, no
`expire_at` (only failure statuses are stamped), no FCM. At the last measurement
before the parking wipe, **12 scenes were stranded** — 4 `queued`, 8
`processing` with cleared leases — none of them from the SIGTERM path, which has
never fired (0286). Cloud Tasks caps retries at 3 and then simply stops.

The wanted mechanism is a sweep for non-terminal scenes older than some bound
with no live task, transitioning them to a terminal state so the phone hears
something. Explicitly NOT the `shutdown_release_count` gate, which 0286 refuses.
**Check:** manual — no sweep exists to check for yet.

### G4-10 · The lease-expiration branch has never run in production
**State:** open · verification debt, not a defect
Crash recovery has two paths. The tidy one — the worker clears its own lease on
a caught error — is the only one production has ever exercised: three
`reclaim_stale` events in a month of logs, each preceded by a `release_error`
from the same worker. The load-bearing one, where an abandoned lease is reclaimed
because it expired, is unit-tested only (0286).

The reference scene for it, `f077e9ed`, was deleted with everything else at
parking, and `reenqueue_scene.py` could not have tested it regardless — it resets
to `queued` first, erasing the expired lease that is the subject. Testing it now
means writing the state deliberately on a fresh capture and dispatching without
the reset. Success is `reclaim_stale` with no preceding `release_error`, then a
clean `ready` or `failed`.
**Check:** manual — needs a fresh capture and a `--no-reset` dispatch path.

### G4-11 · A stale re-mint is fatal where one forced re-mint would do
**State:** open
`remint_returned_stale_uris` is a fatal for the upload, and it predates
`force_remint` (0116), which is now serving and vends fresh URIs for a consumed
session. The fix is to convert the fatal into ONE forced re-mint before giving
up. This is smaller than and separate from the `.recoverable` coordinator, and
is easy to assume that work already covers. (0049, item 1)
**Check:** manual — `grep -rn remint_returned_stale_uris ios/` should show one
forced re-mint before the fatal, not a bare fatal.

### G4-12 · Two IAM leftovers from the launch-hardening audit
**State:** open · operator's, both one-liners
The audit flagged a `firebase-adminsdk-fbsvc` tokenCreator grant and recommended
revoke plus re-grant-per-walk; it has not been actioned. Separately the
pre-split `api-runtime@` service account and its captures binding still exist
and are unused — perception-obj runs as `perception-obj-runtime@` (0090). The
commands are in the note. (0088)
**Check:** manual — `gcloud iam service-accounts get-iam-policy` on
`firebase-adminsdk-fbsvc@`, and `gcloud iam service-accounts list` for
`api-runtime@`.

---

## Gate 5 — finished against the thesis, not against the backlog

Gates 1–4 produce a shippable product. This gate is where "finished" becomes a
judgment. **The ruling in G5-03 is the one that decides the size of this gate.**

### G5-01 · The spatial relationship graph is unbuilt
**State:** open
The AI layer's own substrate — object relationships, traffic flow, light,
proportion. The perception pipeline beneath it works and the guest above it
talks; the reasoning layer between them is what would make the product's central
claim true rather than approximated.
**Check:** manual.

### G5-02 · Sharing rungs 1–3
**State:** blocked on G3-03
Shell, shell-plus-inventory, splats. Designed in `docs/product/social-layer.md`;
all behind per-room deletion. Six rulings in its §10 are the operator's.
**Check:** manual.

### G5-03 · RULING WANTED — which of the direction items are commitments?
**State:** open · **Decides the size of Gate 5**
Room health scoring, taste graph, lighting simulation, budget-aware shopping, and
DAG version history are recorded as direction rather than commitment. None is
required for "finished" unless it is ruled so. Leaving this unruled is how the
conversational-redesign layer quietly became a sub-clause once already.
**Check:** manual — operator.

### G5-04 · The photo-upload path does not exist
**State:** open
Android and no-iPhone users have no route in. Deliberately deferred until the iOS
path was solid — which, after the 2026-08-25 device verification, it now is, so
the stated precondition has been met and this is a live choice again.
**Check:** manual.

### G5-05 · The guest is restricted to a longest dimension
**State:** open
`scene_facts` lets the guest state only an object's longest dimension. The
reason originally given — that the extent triple is descending-sorted and its
axis semantics unrecoverable — was refuted by measurement, and `extent_axes_m`
now declares the up axis per box (0143). The RESTRICTION still stands anyway,
because changing what the guest may SAY is 0096's call and needs a
`FACTS_VERSION` bump and its own voice evals. Sizes, comparisons and clearance
lower bounds already ship; this is the remaining half.
**Check:** manual — needs a ruling, then evals.

### G5-06 · The furniture catalog's re-open trigger has fired
**State:** open · direction, not commitment
0133 deferred the catalog and named the `i_up` chain as its re-open trigger.
That chain is closed end to end: perception declares the up axis (0143) and the
guest speaks a measured height and footprint from it (0178, 0184). Nothing has
scheduled the catalog since, which is the same way the conversational-redesign
layer became a sub-clause. Belongs under G5-03's ruling.
**Check:** manual — operator.

---

## Gate 6 — room quality, open and measured

G6-05 is ANSWERED and negative (0247), and G6-01 is its cause — together they
block calling the 3D representation finished. The rest are quality ceilings that
do not block shipping. All are measured, and all shape how
good the product looks when it ships. **Read `CLAUDE.md`'s measured-dead-ends section
before touching any of them** — re-running a refuted experiment is the most
expensive mistake available in this repo.

### G6-05 · The 3D representation is NOT good enough to ship
**State:** ANSWERED 2026-08-26, negative · **Blocks:** calling the product finished
Gate 6's other entries are component defects measured in isolation — a truncated
splat, an OOM'd detection, a skewed window. **Nothing asks the product question:
does a room, rendered in the viewer and seen by a person, look good enough to put
in front of a stranger?** That judgment is the operator's eyes and has never been
recorded as an acceptance; the walks that exist (0085, the 2026-08-12 second walk,
the sittings) each answered narrower questions on older pipelines.
**Asked and answered (0247).** A fresh 189-frame room was captured, reconstructed
end to end on `perception-obj-00074-var`, and walked. The verdict: the objects
are not whole. A warm re-drive that reconstructed **80% more object views**
(15 → 27, 8 → 12 placed) changed how many things were in the room and changed
nothing about how any of them looked — confirming a prediction registered before
it ran, and costing every colour block to a skipped refinement pass.
So this entry stays open not as a question but as **the defect**: it is G6-01
wearing the product's clothes, and it is the reason the 3D representation cannot
be called finished. It closes when G6-01 closes, and G6-01 has no live route.
**Check:** manual — operator, on a pipeline that has changed since 0247.

### G6-06 · The mask shortlist ships the truncated reading of an object
**State:** open · **Blocks:** part of G6-05, and it is the only truncation cause
that survives a perfect photograph
SAM 3 returns two `desk` masks in the same frame — the same desk at two extents,
99.7% mutual containment — and the per-box shortlist reconstructs the SHORTER one
in all three frames that see it, by 9-12 points of `overlap` every time. The
operator confirms it is a single desk, so the longer mask is correct and the
shipped one is partial.
`mask_overlap_with_hull` is "fraction of a mask's pixels inside the hull" —
precision with no recall term — so a mask that stops short scores near 1.0 while
a complete one is penalised for every pixel past the box's edge. The RoomPlan box
is a BOUND, not a silhouette, so a mask correctly covering an object bigger than
its box is marked down for being right (0261).
0261's three checks RAN, and the answer is systemic (0262/0263). The score is
FLAT before it is wrong: **31 of 52 candidates in `90eebfc4` score exactly
1.0000**, 27% across the four older captures, after which `frame_index` —
capture order — decides. Across the ten nested pairs that associate to a box the
sort takes the shorter in **9 of 10**.
**The ruling is 0266: when SAM 3 returns one object at two nested extents, keep
the longer.** Right **9 of 9** against the operator's verdicts, and it needs no
gate, no score and no box — which is why it supersedes 0263's grown-box
precision gate at 8 of 9. Detection needs no tuning: across 121 same-label pairs
in five captures containment is bimodal, 21 at >= 0.989 and 99 at <= 0.003, with
exactly one in between.
**Decided and NOT built** — `box_placement` is untouched, so the shipped sort is
still the flat one.
**Check:** manual — implement 0266, then re-run the offline association replica
over the five captures and confirm the nine verdicts still hold.

### G6-01 · Class-6 splat truncation
**State:** open, no live route
Objects ship missing legs, bases and backs. Three attacks are measured dead:
better frame selection (0162), a measured depth pointmap (0181), and unioning two
reconstructions (0166). The shared cause is that a single-view reconstruction's
unseen half is fabricated. It waits on decision 0052's standing trigger — a model
that consumes several views itself, or exposes calibrated metric scale or pose.
**Check:** manual — external dependency.

### G6-02 · 22 of 163 detections are lost to CUDA out-of-memory
**State:** chartered, unstarted
13% of the corpus, twelve of them box views; two boxes ship as empty inventory.
It is headroom rather than object size — median shortfall 133 MiB, three cases
missing by 16 MiB. `docs/briefs/throughput-charter.md` owns it and names what is
already refused.
**Check:** manual.

### G6-03 · One room budget-stops; a window ships skewed; three flags stay parked
**State:** open
`b667f891`'s 53-item tail exceeds one request, so its post-passes never run — and
note that room is not representative (a quarter of it is dark, 0235). Near-square
planar objects are ~90°-ambiguous and no instrument scores in-plane orientation.
The parked flags — object-aware residue, conditional second arm, visibility veto —
are measured and deliberately off.
**Check:** manual.

### G6-07 · Frame coverage is one-capture-calibrated and its trigger has fired
**State:** open
0062 chose a deterministic pose-diverse sampler with the budget as the
guarantee, and named its own re-open condition: real rooms under-covering at the
default frame count means raise the default or make it adaptive. That evidence
now exists — `b667f891` carries a 53-item census tail and 17 of 22 objects came
back `insufficient_observations`. The knobs are still described as
"one-capture-calibrated", which reads as posture rather than as a fired trigger.
Entangled with GPU cost, so it is a sizing decision rather than a code change.
**Check:** manual — needs a cost estimate per room before a number.
