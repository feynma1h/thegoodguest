# Next work directions — carried out of the 2026-08-13 coordinator session

Written because both items below existed only in a conversation, which is the
failure mode this project corrects everywhere else. Neither is started.

---

## 1. The room-quality session — the operator's stated direction, and a
##    correction to how the coordinator has been scoping work

**The operator's instruction (2026-08-13):** stop spreading effort across the
existing rooms. Take **ONE** fresh capture and work until it reads as real.

**Why they are right, and it is a process critique worth keeping.** The
coordinator has been scoping sessions by MECHANISM — "fix class 2 duplicates",
"ship the up-axis field", "close 0049" — and every prompt carried a *do NOT
touch X* clause. That discipline is why four lanes merged in a day without
collisions. It is also why nobody ever owned the whole picture. The evidence:
the 0085 walk found six defect classes; 0104 fixed four and refuted one;
**class 6 — the one it named "the bottleneck" — has never been attacked by
anyone.** The item-7 walk then added contact tilt on four objects, an
undersized rp7 monitor, an rp6g1 monitor with no generated base, and a still-
hovering monitor. All open. And the clip-sign defect — the most visible defect
in the product — was found *incidentally* by the stage-2 session and sat
unfixed until the operator looked at renders themselves. No session was ever
tasked with "make the room right", so none of them were wrong to leave it.

**The reframe: scope by OUTCOME, not by mechanism.** Not "fix defect N" but
"iterate until this room reads as real, with the operator's eyes as the
acceptance test". A mechanism-scoped session correctly refuses adjacent
problems; an outcome-scoped one chases whatever the room needs.

**Shape of the session:**
- ONE freshly captured room. Post-switch the phone is the Google account, so a
  new capture lands under one identity with nothing orphaned.
- Broad authority across perception, placement, and rendering — whatever the
  defect actually needs — bounded by ONE room and ONE acceptance test rather
  than by a file domain.
- Iterative with the operator, not a single report at the end. Their walk
  verdicts (0080, 0085, the item-7 walk) are the standard for "reads right".
- Capture quality is in scope. The operator's two suggestions are NOT vague
  design inputs — each has a mechanism, and §1a below states them as the
  defects they are. Start there: both attack class-6 truncation at its CAUSE,
  and the upstream one is strictly better, because no selection algorithm can
  pick a view that was never captured.

### §1a — the two capture-side defects, stated with their mechanisms

**(i) The reconstruction view is chosen by CORRESPONDENCE, never by view
quality.** Two selection layers exist and neither asks the question that
matters. `census_sampling.py` picks which frames get processed at all — greedy
set-cover whose gain is box-visibility area over still-uncovered boxes, gated
on the view being "scoreable". That optimizes ROOM COVERAGE. Then
`box_placement.py:798` picks which view's splat BECOMES the object: it walks
the associations and takes the first one whose splat file exists
(`if candidate_splat is not None: break`).

Verified against the code 2026-08-13, with one refinement that matters. The
list is not unordered: `associate_observations` returns it sorted
`(-overlap, frame_index, mask_index)`. But `overlap` is the projected box
footprint against the SAM mask — it answers *is this mask the same object as
this box*, a correspondence question. It does not answer *does this view show
the object well*. There is no occlusion test, no sharpness test, and no measure
of how much of the object's surface a view actually sees.

The actionable part: `BoxAssociation` already carries `in_frame_fraction`, the
one computed field that speaks directly to truncation. It gates scoring
admissibility at `box_placement.py:873` and it is part of the census layer's
own quality gate — and it plays no part in the ranking at line 798. So a view
with the object half out of frame can outrank a fully visible one and become
the shipped splat. An already-measured signal, deliberately used elsewhere,
absent exactly where the defect lands.

Decide what "cleanest" means, and measure it against the walk's known-bad
objects (the undersized rp7 monitor, the rp6g1 monitor with no generated base).

**(ii) Nothing tells the user an object has been sufficiently OBSERVED.**
RP-7 ships a live floor plan — walls stroking in, furniture as labeled rects, a
camera cone, coverage ticks, and a guidance relay that has never fired live
because RoomPlan issues instructions sparsely. All of it proves an object was
DETECTED. None of it proves the object was seen from enough angles to
reconstruct. The operator's idea is per-object capture-sufficiency feedback —
e.g. furniture that reads as "captured" only once it has been observed from
enough angles, and visibly still wanting otherwise. **Design constraint to
argue, not skip:** RP-7 deliberately REPLACED the camera preview with the floor
plan, and CLAUDE.md flags revisiting that as "a design question, not a patch".
A camera view with boxes over furniture therefore re-opens a considered
decision — legitimate, but it must be argued explicitly, and the floor plan is
an equally valid host for the same signal.

**Why these are one idea:** an object is half-rendered because SAM 3D saw it
from one partial view. (i) fixes that downstream by choosing better among the
views you happen to hold; (ii) fixes it upstream by ensuring a good view gets
taken at all. Same lever, two ends.

**The known work-list it inherits** (do not re-derive): class-6 splat
truncation (the named bottleneck — it causes BOTH the overflow the clip papers
over AND the rotation ceiling); the splat-axis rotation ceiling, where THREE
instrument families are measured dead (0081, 0104 — do not re-attempt without
a genuinely new evidence source); residual contact tilt on four objects (right
height, point contact, because the support snap is height-only while the
splat's rotation residue tilts the body); the rp7 monitor undersized and
hovering; the rp6g1 monitor with no generated base. Decision 0052's re-open
trigger is live and relevant: a reconstruction model exposing calibrated
metric scale or pose would let measurement graduate from prior to authority —
i.e. a geometry-conditioned successor to SAM 3D that can take the LiDAR in.

**One correction to "discard all previous rooms":** discard them as the
QUALITY TARGET, yes. Do NOT delete the data — they are load-bearing regression
fixtures pinning real-data accuracy claims that are among the strongest
evidence in the project, and they are named in production source, not only in
tests: `f3d70236` in 8 files (`contact_priors.py`, `room_planes.py`,
`shell_geometry.py`, `privacy.py` + 4 test modules), `247003de` in 6
(`shell_envelope.py`, `fusion.py`, `make_shell_v3_fixtures.py` + 3 tests),
`a7e073ae` in 4 (the stage-2 solver and geometry suites).

---

## 2. The 0115 churn investigation — STEP 1 IS DONE (decision 0138). What
##    follows is superseded except where noted.

**Answered 2026-08-13 and it took the alarming branch.** `device_id` is
byte-identical across BOTH churns — one UUID over 13 scenes, 19 days and three
Firebase identities — so the Keychain partition was never lost. That kills the
entitlements drop, a signing-team change and an App-ID-prefix change together.
The mechanism is DIFFERENTIAL: something took Firebase's Keychain item and
spared ours. The remaining explanations are all things that can happen to a
real user with no workaround to blame, which promotes this to a launch
blocker. Step 2's device measurement is MOOT — do not run it. Next leads are
source-level (Firebase's own Keychain handling, its accessibility attribute,
error paths that clear the credential), and belong to a fresh investigation.

The original scoping is kept below for the reasoning that produced the test.


The most serious open defect: the phone's Firebase anon UID changed TWICE on
real hardware, orphaning each period's rooms. Decision 0036 makes "never churns
the UID" a hard invariant. Cause UNKNOWN.

**Measured, do not re-derive:** three uid eras on the 16 Pro — `cHfMlUL`
(07-26→08-05, later the Google/Gate-B account), `j9UJyV6s` (08-08, 3 rooms
incl. the hero source), `u4AmDs2Vd` (08-12/13). `j7gxP0HM` is the 16e, a
different physical device — exclude it from within-device reasoning. The app
container SURVIVED throughout (June-era records still on disk), so the app was
never deleted: **the keychain went without the container.**

**Refine the recorded hypothesis before testing it.** 0115 suspects "the
entitlements-drop workaround altered the keychain access group". Check that
premise: `RoomStudioCapture.entitlements` declares ONLY
`com.apple.developer.applesignin` — no `keychain-access-groups` key — and no
Swift code passes `kSecAttrAccessGroup`. An app with no explicit group defaults
to its App ID (TEAM PREFIX + bundle id). So dropping `CODE_SIGN_ENTITLEMENTS`
does not itself move the group; a change of signing TEAM or App ID prefix
would.

**Step 1 — the free decisive test, before touching any device.** `device_id` is
a Keychain UUID (`kSecClassGenericPassword`, `AfterFirstUnlockThisDeviceOnly`)
and the Firebase UID is Keychain-backed too; both sit under the SAME default
access group, so a group change loses BOTH. `Scene.device_id` is persisted at
ingest and survives the 1-day captures sweep. Sweep Firestore scenes for the
16 Pro's three eras and tabulate `(user_id, device_id, created_at)`:
- `device_id` changed IN LOCKSTEP with each uid change → the whole keychain
  partition was lost → access-group / App-ID-prefix change confirmed as the
  mechanism; only the culprit remains to be named.
- `device_id` CONSTANT across a uid change → the group did NOT change, the
  keychain was reachable, and Firebase's credential was lost some other way.
  That KILLS the entitlements/team hypothesis and redirects the investigation.

**Step 2 — the device measurement, only if step 1 leaves it open.** Read from
the INSTALLED app (not the project): the embedded provisioning profile's
`application-identifier` and team, and the entitlements the binary carries
(`codesign -d --entitlements`). Rebuild + reinstall the operator's way, read
again, diff, and correlate any prefix/team change against the churn dates.

**Constraints:** do not break the working install (the 16 Pro carries the
operator's live identity and 6 retained records; re-sign expires
**2026-08-19 07:15 UTC**); never commit the entitlements workaround
(`project.pbxproj` must end pristine); diagnosis is the deliverable — do not
"fix" identity storage on a guess.

**Why the outcome matters either way:** if the workaround/team change is the
cause, every device build destroys user identity, and the stuck Apple
enrollment becomes an active source of data loss. If it is NOT the cause, then
something in ORDINARY operation can orphan a real user's rooms — a launch
blocker, since no real user has a workaround to blame.

---

## 3. Process change the coordinator proposed and the operator has not yet ruled on

**Ready reports should be written to `outputs/reports/<lane>.md` and committed,
not pasted into chat.** Reports currently live only in a conversation — the
exact fragility this project corrects everywhere else, and it already cost us
once: decision 0130's cross-lane handback never reached the session it was
written for, because the coordinator is a manual relay. With reports in git,
the operator says "lane done" and the coordinator reads it; sessions can also
hand off to each other without a human bus.

Related, recorded for whoever runs orchestration next: use subagents for
BOUNDED verification the coordinator would otherwise hand out as a prompt (a
Firestore sweep, a code audit) — they report back directly, no relay. Keep
SEPARATE top-level sessions for builds: a subagent shares the coordinator's
context and returns a summary, while a build session gets its own full window,
which is what multi-hour measure-build-verify work needs.
