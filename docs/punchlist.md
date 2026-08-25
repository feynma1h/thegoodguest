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
`roomstudio.web.app` serves `<title>roomstudio</title>` while the repo has
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

### G4-02 · Python CI has been red since 2026-08-21
**State:** open
The root suite dies at collection with `ModuleNotFoundError: No module named
'PIL'`. `tools/test_gen_mark.py` landed that day importing Pillow, which is
declared only in the two perception pyprojects and so is absent from what the
root job installs via `tools/ci_deps.py`. The other three jobs pass. The root
suite has therefore not executed on Linux since. The fix is one declared
dependency, not a test change.
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

### G4-06 · `web/public/dev-fixtures` is 4.0 GB of real homes inside `public/`
**State:** open
`next build` copies `public/` into `out/`. `firebase.json` ignores
`dev-fixtures/**` on deploy, which is one config line between real captured homes
and a public origin. Moving the directory outside `public/` removes the hazard
rather than guarding it.
**Check:** automated — the path must not live under `web/public/`.

### G4-07 · Registry and device housekeeping
**State:** open
The `serving-rollback-00062-hum` tag still pins `faa005c8…` in Artifact Registry
and is owed back once `00074-var` is trusted. Three captures — `1805949c`,
`8c05fa72`, `f47ca8b7` — are still on the phone and preserved nowhere; a launch
will reap them now that api-public answers properly.
**Check:** automated — the rollback tag; the captures are manual.

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

---

## Gate 6 — room quality, open and measured

G6-04 and G6-05 DO block calling the 3D representation finished; the rest are
quality ceilings that do not block shipping. All are measured, and all shape how
good the product looks when it ships. **Read `CLAUDE.md`'s measured-dead-ends section
before touching any of them** — re-running a refuted experiment is the most
expensive mistake available in this repo.

### G6-04 · No room has ever been reconstructed by the serving pipeline
**State:** open · **Blocks:** G6-05, and any claim about current room quality
`perception-obj-00074-var` carries 100% of traffic and has served **zero**
`/process` requests. The refine + arm-select flip landed 2026-08-25 changing what
SAM 3D is shown and which arm ships; the last room made anywhere was 2026-08-23
on `00062-hum`. Every room anyone has looked at was produced by older code, and
the bench evidence behind the flip came from 0%-traffic candidates on preserved
captures rather than from a room the pipeline made end to end.
A candidate deploy is smoked on `/health` and route registration, which does not
exercise reconstruction at all — so this is a deploy that has never been proven
by use.
**Check:** automated — the serving revision must have served `/process` at least once.

### G6-05 · No whole room has been judged good enough to ship
**State:** open · **Blocks:** calling "finished" on the 3D representation
Gate 6's other entries are component defects measured in isolation — a truncated
splat, an OOM'd detection, a skewed window. **Nothing asks the product question:
does a room, rendered in the viewer and seen by a person, look good enough to put
in front of a stranger?** That judgment is the operator's eyes and has never been
recorded as an acceptance; the walks that exist (0085, the 2026-08-12 second walk,
the sittings) each answered narrower questions on older pipelines.
It needs a room captured, reconstructed on the serving revision, and walked in the
real viewer rather than an offline render — the viewer is the product, and the
reveal is the moment the founding vision calls defining.
**Check:** manual — operator. Nothing else can answer it.

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
