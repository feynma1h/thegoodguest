# Privacy nutrition labels — The Good Guest

**Status:** filled in and traced, ready to transcribe into App Store Connect.
Not yet filed. Every answer below cites the file, live config, or decision that
makes it true; an uncited answer would be a guess, and this is a legal
disclosure rather than a form.

**Product name is "The Good Guest" (0245).** The repo, the GCP project, the
buckets and the `roomstudio:` localStorage keys deliberately keep the
`roomstudio` stand-in. Those are infrastructure and must not appear in a
filing. One exception is a real defect, not a naming convention — see F6.

**What this document is for.** Apple's App Privacy questionnaire is answered
once and then read by every user who opens the App Store listing. This product
has a specific disclosure most apps do not: **photographic image data from the
inside of the user's home is transmitted to a third-party model** (§4a). The
labels have to say so. Getting it wrong is not a rejected build; it is a false
statement to people about their homes.

**How to use it.** §3 is the transcription sheet — every Apple category, with
its answer. §4–§7 are the evidence behind the answers that are not obvious.
§8 lists the places where the shipped Privacy Policy and these labels would
disagree; those are flagged, not silently reconciled. §10 is the re-check list,
because these answers go stale when the pipeline changes.

Verification date for every live claim: **2026-08-24**. Serving revisions at
that date: `api-public-00042-ruq`, `perception-obj-00062-hum`.

---

## 1. What Apple is actually asking

Apple's definition of **collect** is the one that decides most of the answers
below: *transmitting data off the device in a way that allows you and/or your
third-party partners to access it for a period longer than what is necessary to
service the transmitted request in real time.*

Two consequences this system runs straight into:

- **Deleting it later does not make it uncollected.** The raw capture is deleted
  at 24 hours (§5) and that is a real and creditable retention fact, but the
  photographs are collected. They are transmitted, stored, and read.
- **Server logs count.** Cloud Run's request log is retained 30 days, longer
  than the request it services. That makes the client IP, the user agent and
  the request URL collected data, and it is the one judgment call in this
  filing that decides four categories at once. It gets its own section (§7).

Apple's separate **tracking** question — linking user data with third-party
data for advertising, or sharing it with a data broker — is answered **No**
throughout, and that answer is structural rather than a promise: there is no
advertising identifier, no ATT prompt, and no analytics or advertising SDK
anywhere in the app.

```
$ grep -rniE "ASIdentifierManager|AdSupport|AppTrackingTransparency|advertisingIdentifier|identifierForVendor" ios
(no matches)
```

The linked SPM products are exactly `FirebaseCore`, `FirebaseAuth`,
`GoogleSignIn`, `GoogleSignInSwift`, `SwiftProtobuf`
(`ios/RoomStudioCapture/RoomStudioCapture.xcodeproj/project.pbxproj`,
`XCSwiftPackageProductDependency` section). `GoogleAppMeasurement` and
`google-ads-on-device-conversion-ios-sdk` appear in `Package.resolved` because
they are in the Firebase package graph's transitive closure; **neither is linked
into the app target.** No `FirebaseAnalytics`, no Crashlytics, no
`FirebasePerformance`, no `FirebaseMessaging`.

The web app carries no analytics either: no `gtag`, Google Analytics, GTM,
Plausible, PostHog, Sentry, Mixpanel, Segment, Hotjar or Clarity appears
anywhere under `web/src` or `web/public`.

---

## 2. Threshold answers

| Apple's question | Answer | Basis |
|---|---|---|
| Do you or your third-party partners collect data from this app? | **Yes** | §3 |
| Is any data used to track users? | **No** | No IDFA/ATT/ad SDK; no data broker; no third-party ad partner |
| Are any data types used for Third-Party Advertising? | **No** | same |
| Are any data types used for Developer's Advertising or Marketing? | **No** | Terms §5: rooms are not used in marketing without asking |
| Are any data types used for Analytics? | **No** | No analytics SDK on either surface |
| Are any data types used for Product Personalization? | **No** | Nothing profiles across users; the guest reads only the room in front of it (`scene_facts.py`) |

Every collected type below is therefore **App Functionality** only, with the
single exception discussed in §7.

---

## 3. Every category, answered

"Not collected" entries are answers, not omissions — Apple asks about each one.

### 3.1 Collected

| Apple type | Collected | Linked to user | Tracking | Purpose |
|---|---|---|---|---|
| **User Content → Photos or Videos** | Yes | Yes | No | App Functionality |
| **Surroundings → Environment Scanning** | Yes | Yes | No | App Functionality |
| **Identifiers → User ID** | Yes | Yes | No | App Functionality |
| **Identifiers → Device ID** | Yes | Yes | No | App Functionality |
| **Contact Info → Name** | Yes, only on provider link | Yes | No | App Functionality |
| **Contact Info → Email Address** | Yes, only on provider link | Yes | No | App Functionality |
| **User Content → Other User Content** | Yes — see the scoping note | Yes | No | App Functionality |
| **Diagnostics → Other Diagnostic Data** | Yes | Yes | No | App Functionality |
| **Other Data → Other Data Types** | Yes — judgment call, see 3.1h | Yes | No | App Functionality |

**a. User Content → Photos or Videos — the central one.**
A capture is a few hundred JPEG stills of the inside of a home, one accumulated
roughly every 10 cm or 5° of camera movement, written to
`<bundle>/frames/NNNNNN.jpg` (`Capture/CaptureManager.swift:132`) and uploaded
to Google Cloud Storage. The bundle carries them by reference —
`Frame.rgb_gcs_path` (`packages/schemas/capture_bundle.proto`, `Frame` field 3)
— because the proto is metadata and the pixels live in GCS.

These are ordinary photographs of the user's home and are the most sensitive
thing the system holds. They are deleted at 24 hours (§5) — which does not make
them uncollected.

**b. Surroundings → Environment Scanning — the category most likely to be
missed, and the one that describes this product.**
Apple defines it as mesh, planes, scene classification and/or image detection of
the user's surroundings. All three ship on every capture that can produce them:

- **Planes with classifications.** `PlaneAnchor` (proto field 12) — the
  session's final ARKit plane set, each carrying pose, centre, extent, a
  boundary polygon, horizontal/vertical alignment, and ARKit's own
  classification string verbatim: `wall`, `floor`, `ceiling`, `table`, `seat`,
  `window`, `door`.
- **LiDAR depth.** `Depth` — a 256×192 float32 raster of distances in metres per
  frame, plus a per-pixel confidence raster, uploaded as separate blobs
  (`Depth.depth_gcs_path` / `confidence_gcs_path`).
- **RoomPlan's parametric model.** Apple's `CapturedRoom` Codable JSON, verbatim
  (`RoomPlanModel.json_gcs_path`, decision 0077): wall outlines, floor polygon,
  doors, windows and openings with parenting, and boxes around furniture with
  categories, confidences and dimensions.

Only the LiDAR Pro tier produces all three (`CaptureTier`: `ARKIT_ONLY`,
`LIDAR_ARKIT`, `LIDAR_ROOMPLAN`), and the product is Pro-only by design
(decision 0071) — so in practice the fullest form is what ships.

**c. Identifiers → User ID.**
The Firebase account UID, on every capture (`CaptureBundle.user_id`, proto field
3) and every authenticated request. Anonymous on first launch and stable
thereafter — linking a provider deliberately does not change it
(`Auth/AuthManager.swift`, the link core asserts the UID unchanged; decisions
0036/0051/0118). The backend takes only the `uid` claim out of a verified token
and nothing else (`services/api-public/auth.py:61`).

**d. Identifiers → Device ID.**
`Device.device_id` (proto field 5) — a UUID minted on first use and persisted in
the iOS Keychain as `kSecClassGenericPassword` with accessibility
`AfterFirstUnlockThisDeviceOnly` (`Support/DeviceIdentity.swift`). The backend
**requires** it and rejects a bundle without one as `failed_invalid`
(`device_id_missing`).

Three things worth stating plainly on the record, because they are the
difference between an honest Device ID answer and a misleading one:

- it is **per installation**, not per person, and not an Apple-provided ID — it
  is neither the IDFA nor `identifierForVendor`;
- it does **not** survive a restore onto different hardware: `ThisDeviceOnly`
  excludes it from device backup/restore and `kSecAttrSynchronizable` is left
  unset, so a new phone mints its own;
- `Device.hardware_id` beside it is a **model** string (`iPhone17,1`), not a
  unique identifier — two phones of the same model produce the same value.
  It is disclosed under Diagnostics instead (3.1g).

**e. Contact Info → Name.**
Collected only when the user links a sign-in provider. Sign in with Apple is
requested with `requestedScopes = [.fullName, .email]`
(`Auth/SignInSheet.swift:207`), and the name is forwarded to Firebase so it
records a display name (`Auth/AuthManager.swift:207-210`). Google supplies a
display name with the credential.

**Nothing in this codebase reads it** — `grep -rn "displayName"` over
`ios/`, `services/` and `web/src/` returns nothing. It is nonetheless stored in
Firebase Authentication, in a project we control, which is what makes it
collected.

Verified live, aggregate only, no values read: of the 500 accounts returned by
one page of `identitytoolkit accounts:query`, **499 are anonymous-only and 1
has a `google.com` provider**; `displayName`, `email` and `photoUrl` are
populated on exactly that one account and no other.

**f. Contact Info → Email Address.**
Same trigger, same store. Sign in with Apple may return a **private relay
address** if the user chooses Hide My Email — in which case that relay address
is what is held.

The precise and creditable fact here: **the email never enters our application
datastore.** `auth.py:61` extracts `decoded["uid"]` and discards the rest of the
token, so no Firestore document and no GCS object anywhere carries an email
address. It exists only in the Firebase Auth user record.

**g. Diagnostics → Other Diagnostic Data.**
`Device` (proto field 4) carries `hardware_id` (model string), `os_version`,
`app_version` and `has_lidar` on every capture. The proto's own comment names
the uses: *"backend telemetry, debugging, and tier dispatch."* Tier dispatch is
functionality — it decides which models run — so the purpose is **App
Functionality**, not Analytics. It is disclosed under Diagnostics because
telemetry and debugging are among the stated uses and the honest category is the
one the code's own words point at.

Also in the bundle: `started_at_device_us` / `ended_at_device_us` (device
monotonic) and `started_at_wall_us` (wall clock) — when the capture started and
ended.

**No crash or performance data is collected by us.** There is no Crashlytics and
no `FirebasePerformance`. Crash reports users opt into sharing through iOS reach
Apple, and data Apple collects on a developer's behalf is outside this
questionnaire.

**h. Other Data → Other Data Types — a judgment call, stated as one.**
When a user links Google, Firebase Auth records a **`photoUrl`** — a URL
pointing at the user's Google profile picture on Google's CDN. It is not an
image we hold and it was never requested; it arrives with the credential.
Confirmed populated on the one provider-linked account in the live aggregate
above.

**Recommendation: disclose it** under Other Data Types. It is data about a
person, stored in a system we control, for longer than a request. A reasonable
filer could instead treat it as an attribute of the account already covered by
Name and Email; that reading is defensible, and the cost of the conservative
choice is one extra row on the label. Take the extra row.

**i. User Content → Other User Content — with a scoping note that is the
operator's call.**
When a user talks to the guest about a room, the messages they type are stored
verbatim: `conversations/{scene_id}__{user_id}/turns/{turn_index}` carries
`user_text` and `assistant_text`
(`services/api-public/conversation_repo.py`). Free text about a person's home,
retained with the room and deleted with the account.

**The scope question:** this surface is on the **web app today, not in the iOS
app.** Apple's questionnaire covers the app. Strictly, the iOS binary does not
collect conversation text.

**Recommendation: disclose it anyway.** The label is read by someone deciding
what happens to their data when they use this account, the iOS app is the only
on-ramp to that account, and the app is expected to gain the surface. Under-
disclosing and adding it later is the worse failure mode of the two. If the
operator prefers the strict reading, the note to keep is that this becomes a
required amendment the moment a conversation surface ships on iOS.

### 3.2 Not collected

Each of these is an answer, and several are load-bearing.

| Apple type | Answer | Basis |
|---|---|---|
| **Location → Precise Location** | Not collected | No location permission is declared at all; no CoreLocation |
| **Location → Coarse Location** | Not collected | same — but read §7 before filing |
| **Contact Info → Phone Number** | Not collected | No phone auth provider; `phoneNumber` populated on 0 of 500 live accounts |
| **Contact Info → Physical Address** | Not collected | Nothing in the app or API asks for one |
| **Contact Info → Other User Contact Info** | Not collected | — |
| **Health & Fitness → Health, Fitness** | Not collected | No HealthKit |
| **Financial Info → Payment, Credit, Other** | Not collected | No StoreKit, no payment SDK, no payment path anywhere |
| **Sensitive Info** | Not collected | See the note below — this one deserves more than a No |
| **Contacts** | Not collected | No Contacts framework |
| **User Content → Audio Data** | Not collected | No microphone usage description; no audio anywhere in the capture path |
| **User Content → Emails or Text Messages** | Not collected | No messaging surface; guest turns are Other User Content (3.1i) |
| **User Content → Gameplay Content** | Not collected | — |
| **User Content → Customer Support** | Not collected | Support is an email address in the policy, outside the app |
| **Browsing History** | Not collected | — |
| **Search History** | Not collected | — |
| **Purchases → Purchase History** | Not collected | No payment path; Terms §11 note 1a records that the service is free |
| **Usage Data → Product Interaction** | Not collected | No analytics on either surface — but read §7 |
| **Usage Data → Advertising Data** | Not collected | No advertising anywhere |
| **Usage Data → Other Usage Data** | Not collected | — |
| **Diagnostics → Crash Data** | Not collected | No Crashlytics; Apple's own crash sharing is Apple's collection |
| **Diagnostics → Performance Data** | Not collected | No FirebasePerformance |
| **Body → Hands** | Not collected | No hand tracking |
| **Body → Head** | Not collected | No face or head tracking; ARKit world tracking only |

**Location, stated properly.** The only permission the app declares is the
camera:

```
INFOPLIST_KEY_NSCameraUsageDescription = "RoomStudio captures your room with ARKit."
```

(`project.pbxproj:464` and `:500` — both build configurations, and no other
`INFOPLIST_KEY_NS*UsageDescription` exists.) No location, no photo library, no
microphone, no contacts, no tracking prompt. The camera poses in a capture are
expressed in a world frame ARKit assigns at session start — they describe where
the phone was **inside the room**, not where the room is on Earth. See §7 for
the server-side IP question, which is a separate matter and does not change this
answer.

**Sensitive Info, and why a bare No is not enough.**
Apple's Sensitive Info type covers racial or ethnic data, sexual orientation,
pregnancy, disability, religious or philosophical belief, trade union
membership, political opinion, genetic data and **biometric data**. None of it
is collected, sought, derived or inferred.

Two things make that answer honest rather than merely technically true, and both
belong in the operator's head when they file:

- **Person detection is not biometric.** `person` is a SAM 3 concept whose only
  output is a 2D pixel mask used to *exclude* those pixels
  (`services/perception-obj/privacy.py`, decision 0089). There is no face
  detection, no recognition, no embedding, no template, no identity. Nothing
  that could identify a person is computed, and the mask is never served.
- **Photographs of a home can incidentally show anything** — a religious object,
  a mobility aid, medication. That is not a declared data type, because we do not
  seek or derive it. It is precisely why §4a's disclosure has to be plain, and
  why Privacy Policy §8 and Terms §4 tell people to ask others to step out.

---

## 4. What is sent to a model, and to whom

Two calls go to a third party beyond the cloud provider. Both go to
**Anthropic**. **They are different disclosures and must not be collapsed into
one** — one sends pictures of the home, the other sends words about it.

### 4a. Material inference — the one that must be named

**This is the disclosure this filing exists for.** It is the only path by which
photographic image data from inside a person's home reaches a company that is
not the cloud provider.

| | |
|---|---|
| Where | `services/perception-obj/shell_material.py:189`, `classify_family_via_api` |
| Model | `claude-sonnet-5` — `SHELL_MATERIAL_MODEL`, `shell_material.py:71` |
| Vendor | Anthropic, via the `anthropic` Python SDK |
| Armed in production? | **Yes**, verified live |
| What is sent | Up to **4** rectified crops of one surface, each a **0.64 m** square patch resampled to **256×256 px** (~2.5 mm/px), base64 PNG — **actual photographic pixels from the room** — plus a short text prompt naming the crop size and the vocabulary |
| What comes back | `{family, confidence}` — one word from a closed list, and a number |
| How often | **Once per plane per room.** A wall or a floor, not the room, and not per frame |

The crop parameters are `shell_observation.py:71-74`:
`SHELL_EVIDENCE_CROP_M=0.64`, `SHELL_EVIDENCE_CROP_PX=256`,
`SHELL_EVIDENCE_MAX_CROPS=4`, `SHELL_EVIDENCE_MIN_OBS=0.8`.

Live verification, `perception-obj-00062-hum` at 100% traffic:

```
SHELL_MATERIAL_MODEL = claude-sonnet-5
SECRET ANTHROPIC_API_KEY <- anthropic-api-key
```

**What is deliberately NOT in the request.** Reading the content list the call
builds (`shell_material.py:209-268`), it contains only per-crop text, per-crop
images, and one closing instruction. No user id, no device id, no scene or
bundle id, no coordinates, no depth, no pose. The request carries pixels of a
surface and nothing that names whose surface it is.

**Person suppression applies to this path, and it is the sharpest form of it.**
A crop that would contain a suppressed pixel is rejected for that frame and the
tile falls back to a person-free frame or yields no crop at all
(`privacy.py` module docstring; decision 0089 puts the check inside
`_rectify_crop` at crop resolution rather than on the coarser texel grid,
precisely because *the crop is the surface that actually leaves the process*).

**If the call fails, nothing is guessed.** No API key, no crops, a call failure,
an off-vocabulary answer, `other`, or a confidence below
`SHELL_MATERIAL_MIN_CONF` (0.75, `shell_material.py:83`) all yield `family =
None` and the plane renders a clean matte in its measured colour. The degrade is
test-pinned and never blocks the room.

### 4b. The conversational guest

| | |
|---|---|
| Where | `services/api-public/public_server.py:663`, `AnthropicGuestStreamer` |
| Model | `claude-sonnet-5` — `GUEST_MODEL`, verified live on `api-public-00042-ruq` |
| What is sent | **Text only** |
| Surface | Web today; the iOS app has no conversation screen |

What travels is a derived fact sheet — inventory names, hedged sizes, distance
strings, measured colours — plus the user's typed messages. **No image, depth
map, or coordinate ever enters the request.** That is structural, not a
convention: `scene_facts.py` exists to be the guest's entire world, and its
docstring states the rule — *"The raw manifest never enters the prompt: no
quaternions, no float triples, nothing the model could do 3D arithmetic on."*
The streamer passes a `messages` list through unchanged and never constructs an
image block.

### 4c. What runs on our own hardware, and does not leave

Worth recording because it is the natural next question and the answer is good:
**SAM 3 segmentation and SAM 3D reconstruction run inside our own container on
our own GPU.** They are not API calls. The room's photographs are read by our
service in `asia-southeast1` and are not transmitted to a model vendor — with
the single, bounded exception of §4a's crops.

### 4d. The calling card sends nothing

`web/src/lib/card/` and `CallingCardSheet.tsx` — built, not deployed
(decisions 0221–0223). The card is composed in a browser canvas and downloaded
with `toBlob` (`CallingCardSheet.tsx:175-177`). **Nothing is uploaded and no new
route exists.** It adds no collection and needs no label change.

### 4e. What cannot be verified from this repo

**Anthropic's retention and training terms are not verifiable from the code.**
The claim that commercial API inputs and outputs are excluded from model
training is a statement about a vendor's published terms, not about anything in
this repo, and it is a term the vendor may change. The Privacy Policy already
carries this as operator review note 2 and it is still owed. **Do not assert a
retention period for the crops in the filing.** State that the vendor processes
them under its own published terms, and confirm those terms before submitting.

Same for Google Cloud's DPA covering the buckets and Firestore — asserted in the
Privacy Policy, not verifiable here.

---

## 5. Retention, verified against live config

Every row was checked against the running system on 2026-08-24, not against the
setup script.

| What | Where | Rule | How verified |
|---|---|---|---|
| **Raw capture** — every JPEG frame, depth and confidence raster, RoomPlan JSON/USDZ, `bundle.pb` | `gs://roomstudio-captures/captures/` | **Delete at age 1 day** | LIVE: the bucket's only lifecycle rule is `Delete` / `age: 1` / `matchesPrefix: ["captures/"]` |
| **The room** — manifest, shell, per-object splats | `gs://roomstudio-perception-outputs/scenes/` | **No age rule.** Kept until the user deletes it | LIVE: the outputs bucket's only rule is the masks rule below |
| **Segmentation intermediates** — `masks.npz`, including the person silhouette union | same bucket | **Delete at age 180 days** | LIVE: `Delete` / `age: 180` / prefix `scenes/` / suffix `/masks.npz` |
| **Failed scenes** | Firestore `scenes` | TTL on `expire_at`; api-internal stamps terminal failures at 90 days, clears on revival, never stamps `ready` | LIVE: `ttlConfig.state = ACTIVE` |
| **Upload bookkeeping** | Firestore `upload_sessions` | TTL on `created_at` → **swept promptly, not after 7 days** | LIVE: `ttlConfig.state = ACTIVE`; see F1 |
| **Conversations, design specs, quota counters** | Firestore | **No TTL.** Kept until account deletion | `account_deletion.py` names each collection |
| **Server request logs** — client IP, user agent, request URL, timestamp | Cloud Logging `_Default` | **30 days** | LIVE; see §7 |
| **Admin/audit logs** | Cloud Logging `_Required` | 400 days, locked | LIVE |

**Region.** Both buckets are `ASIA-SOUTHEAST1`, single-region; Cloud Run runs in
`asia-southeast1`; and **Firestore's `(default)` database is `asia-southeast1`**
— which resolves the open question in Privacy Policy operator review note 3.
Point-in-time recovery is disabled, so no PITR window holds recoverable copies
of deleted documents. No external log export sinks exist beyond the two default
buckets.

The 24-hour capture rule is the one the Privacy Policy calls the single most
important retention fact on the page, and it is enforced by storage lifecycle
rather than by anything remembering to run. That is true and it is verified.

---

## 6. Deletion, and the boundary it has

`DELETE /account` (`services/api-public/account_deletion.py`, decision 0095)
runs immediately, is idempotent and resumable, and deletes in the order GCS →
Firestore → identity, deliberately: a failure mid-pass leaves records intact so
the identical plan can be re-derived, and leaves the user able to sign in and
run it again.

It removes, by hand — **Firestore never cascades**, so every collection and
prefix is named in that module:

- `scenes`, `upload_sessions`, `upload_mint_quotas`, `conversations` **and their
  `turns` subcollection**, `design_specs`;
- `gs://captures/captures/{bundle_id}/**` for every bundle the user owns, taken
  from the **union** of `scenes` and `upload_sessions` — load-bearing, because
  the two sources have different lifetimes and either alone leaks blobs;
- `gs://outputs/scenes/{scene_id}/**`;
- the Firebase Auth user record last — which is where the email, display name
  and photo URL live, so those go with it.

**The boundary the labels have to be honest about: account deletion does not
reach Cloud Logging.** The request logs in §7 survive it and age out on their
own 30-day clock. Privacy Policy §7 is titled "Deleting everything" and does not
state this. See F2.

Two boundaries the policy already states correctly, worth keeping in the filing:
deletion does not reach the phone (the app starts over with a fresh anonymous
account), and anything a vendor retains under its own terms is outside our
delete.

---

## 7. The one judgment call: server request logs

This decides four category answers at once, so it is made explicitly here rather
than left implicit.

**The fact.** Cloud Run writes a request log for every call, and it is retained
30 days in the `_Default` bucket. A live sample from `api-public`, redacted to
its shape:

```
httpRequest.remoteIp    "103.139.xx.xx"
httpRequest.userAgent   "RoomStudioCapture/1 CFNetwork/3860.600.12 Darwin/25.5.0"
httpRequest.requestUrl  ".../captures/<bundle_id>/upload_session"
timestamp               2026-08-23T20:05:50Z
```

The IP is real, the URL contains the bundle id, the same request carried a
Firebase JWT, and the log outlives the request by 30 days. Under Apple's
definition that is collection, and it is linked.

**Our own application logging is clean**, which is worth stating: no user
message text is logged anywhere in `api-public`, and a UID appears in exactly
two log lines, one of them an exception path
(`public_server.py:919` and `:1332`).

**The recommendation, and the reasoning:**

- **Do not declare Coarse Location.** Apple's Coarse Location is data that
  *describes the location of a user or device*. We never derive location from
  the IP — nothing in this system geolocates, and no product behaviour depends
  on where a request came from. The IP is an artefact of operating a service on
  Google Cloud.
- **Do not declare Product Interaction** for the same reason: nothing reads
  these logs as usage data, there is no analytics pipeline, and no product
  behaviour derives from them.
- **Do fix the disclosure rather than the label.** The honest response is not to
  add a label row; it is to name server logs in Privacy Policy §6 and to state
  in §7 that they are the one thing account deletion does not reach — and,
  optionally, to shorten `_Default` retention, which is a one-line change and
  would make the 30-day figure smaller than the 90-day failed-scene figure the
  policy already publishes.

**The conservative alternative, if the operator prefers it:** declare
**Identifiers → Device ID** with purpose App Functionality, on the reading that
an IP is a string identifying a device. It costs nothing on the label — Device
ID is already declared for a different reason (3.1d) — and it removes the
argument entirely. **This is a reasonable choice and the operator may simply
take it.** What is not reasonable is leaving the logs undisclosed in the policy
either way.

---

## 8. Where the shipped policy and these labels would disagree

Flagged, not reconciled. The repo's standard is to fix the wrong side of a
mismatch rather than make the text self-consistent, and **the Privacy Policy and
Terms are not this lane's to edit** — each finding below is a drafted
correction for whoever owns those pages.

### F1 — The upload-session retention claim is wrong in three places

**Claim:** Privacy Policy §6 — *"Upload bookkeeping expires 7 days after the
upload."* Repeated in `infra/eventarc_setup.sh` §3 (*"TTL on field 'created_at',
7 days (604800s)"*), in `account_deletion.py`'s docstring (*"`upload_sessions`
carries a 7-day TTL"*), and in CLAUDE.md's retention line.

**What is true:** Firestore TTL has **no duration parameter**. A document is
deleted when the named field's *value* is in the past. The policy is on
`created_at`, and `created_at` is written as `datetime.now(tz=timezone.utc)`
(`upload_session_repo.py:337`, `:482`; written at `:392`, `:408`, `:552`,
`:584`). So the record is expired the instant it is written and is swept on the
next pass, not after seven days.

**The setup script's own §4 comment states this rule and warns against exactly
this mistake** — *"Do NOT point a TTL policy at created_at here: Firestore
deletes when the named field's value is past, which for created_at means
immediately"* — while §3 of the same file does it. `upload_session_repo.py:8-10`
is the one place that describes the behaviour accurately: *"Firestore sweeps
promptly once the timestamp is past."*

**Corroborated live:** `upload_sessions` held 2 documents, both ~30 minutes old;
none older than one day. Small sample, so the mechanism above is the primary
evidence and this is the confirmation.

**Assessment.** The error is in the **safe direction** — data is deleted far
sooner than users are told — and nothing is broken by it: `account_deletion.py`
unions bundle ids from `scenes` *and* `upload_sessions` precisely so a
short-lived session cannot leak capture blobs, and that union is correct at any
TTL. But a retention figure in a privacy policy that is wrong by a factor of
seven is still wrong.

**Where the "7 days" came from:** GCS resumable session URIs are valid for 7
days, which is a true fact about the URIs and was carried across to the
Firestore record's TTL, which is a different thing.

**Drafted correction, Privacy Policy §6:**
> **Upload bookkeeping** is deleted automatically, usually within a day of the
> upload.

Also correct the `eventarc_setup.sh` §3 comment, the `account_deletion.py`
docstring, and CLAUDE.md's retention line. **For the labels: do not state 7 days
anywhere.**

### F2 — Server request logs are undisclosed and outlive "delete everything"

Privacy Policy §6 lists six retention facts and none is the 30-day request log;
§7 is titled "Deleting everything" and account deletion does not reach Cloud
Logging. Nothing in the policy is falsified by this, but a filing that reasons
about it (§7 above) and a policy that is silent on it is exactly the mismatch
this section exists to catch. Recommendation in §7.

### F3 — Both policy pages are stale on iOS Google sign-in

Privacy Policy §3: *"you can attach Sign in with Apple to that same anonymous
account, and then sign in on the web with Apple or with Google."* Terms §3:
*"You may attach Sign in with Apple to it, and afterwards sign in on the web
with Apple or Google."* Both scope Google to the web.

**Google linking shipped on iOS** (decision 0118):
`AuthManager.linkGoogleAccount`, `SignInSheet.startGoogleSignIn` with its
preflight, the `CFBundleURLTypes` reversed-client-id scheme in
`RoomStudioCapture-Info.plist`, and `GoogleSignIn` + `GoogleSignInSwift` linked
in the project.

This matters to the labels because it changes *when* Name and Email are
collected on the app surface — under the policy's text, never; in fact,
whenever a user links Google in the app.

**Drafted correction, Privacy Policy §3, first sentence of the second
paragraph:**
> If you want to reach your rooms in a browser, you can attach Sign in with
> Apple or Google to that same anonymous account, from the phone or from the
> web.

### F4 — §5 describes Firebase Cloud Messaging as if it were live

Privacy Policy §5: *"Firebase Cloud Messaging if you allow notifications — see
only account identifiers and delivery tokens."*

`FirebaseMessaging` is not linked into the app. The `fcm_token` field exists
end-to-end on the server (`public_server.py:258`, `upload_session_repo.py`,
`Scene.fcm_token`) and on the client's request type
(`UploadSessionClient.swift:102`), but **no production call site supplies it** —
both `UploadCoordinator.swift:216` and `BlobUploadManager.swift:222` omit the
argument and it defaults to `nil`.

The phrasing is conditional, so it is not false. **For the labels this is
decisive: do not declare a push token as collected.** It becomes a required
amendment when APNs ships (CLAUDE.md records push as stubbed at named seams
pending the entitlement).

### F5 — §3 understates what a linked provider hands over

§3 says attaching a provider gives *"typically an email address, and a stable
provider-specific identifier."* In fact Sign in with Apple is requested with
`.fullName` and the name is forwarded to Firebase, and Google supplies a display
name and a profile photo URL — all three confirmed populated on the one
provider-linked account in the live aggregate.

**Drafted addition to §3:**
> Attaching a provider gives us whatever that provider releases: typically an
> email address, a stable provider-specific identifier, the name you allow it
> to share, and — from Google — a link to your profile picture. With Apple you
> may choose to hide your email, in which case we receive only a relay address.

### F6 — The camera permission string still says "RoomStudio"

```
INFOPLIST_KEY_NSCameraUsageDescription = "RoomStudio captures your room with ARKit."
```
(`project.pbxproj:464`, `:500`.)

This is **user-visible** — it appears in the camera permission dialog and in
Settings — so it is not covered by the deliberate decision to keep `roomstudio`
as the infrastructure stand-in. The name is settled as The Good Guest (0245).
An iOS lane's to fix, and it should be fixed before any TestFlight build, since
the permission prompt is the first sentence the product says to a new user.

### F7 — CLAUDE.md is stale on the material confidence gate

CLAUDE.md's open-defects list says *"Recommended and NOT applied: raise
`SHELL_MATERIAL_MIN_CONF` to 0.75."* The code's default **is** 0.75
(`shell_material.py:83`), raised on decision 0100's measurement, with the
reasoning in the comment above it. Not a labels issue; found while tracing §4a
and recorded because the repo fixes the wrong side of a mismatch.

### F8 — There is no `PrivacyInfo.xcprivacy`, and it is required

Its own section — §9.

---

## 9. The privacy manifest, which does not exist

Separate from the nutrition labels and also required. Apple requires a
`PrivacyInfo.xcprivacy` in the app bundle declaring collected data types,
required-reason API usage, and tracking domains. **This repo has none:**

```
$ find ios -iname "*.xcprivacy"
(no results)
```

The app uses **three** required-reason API categories, each verified by reading
the call sites:

| Category | Where | Reason code |
|---|---|---|
| `NSPrivacyAccessedAPICategoryUserDefaults` | `Home/BundleRestore.swift`, `Identity/WhySignInSheet.swift`, `Support/StagingHooks.swift`, `Upload/CaptureReaper.swift` | `CA92.1` — accessed only by the app itself |
| `NSPrivacyAccessedAPICategorySystemBootTime` | `Capture/CaptureManager.swift:256`, `:308`, `:760` — `CACurrentMediaTime()` | `35F9.1` — measuring elapsed time within the app |
| `NSPrivacyAccessedAPICategoryFileTimestamp` | `Capture/CaptureStorageSweeper.swift:100`, `:119`, `:122` — `contentModificationDateKey` | `C617.1` — timestamps of files inside the app container |

**No disk-space API is used** — no `volumeAvailableCapacity`, `statfs`,
`systemFreeSize` or equivalent appears anywhere in the app source, so
`NSPrivacyAccessedAPICategoryDiskSpace` is **not** required. Worth stating
because it is easy to assume otherwise from `CaptureRecovery`'s behaviour.

`NSPrivacyTracking` is `false` and `NSPrivacyTrackingDomains` is empty — see §2.

**A draft is below. It is product code and this lane does not write product
code** — hand it to an iOS lane, which should also confirm at build time that
the Firebase (11.15.0) and GoogleSignIn (9.2.0) SDKs ship their own signed
manifests, as both versions should.

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>NSPrivacyTracking</key><false/>
  <key>NSPrivacyTrackingDomains</key><array/>

  <key>NSPrivacyCollectedDataTypes</key>
  <array>
    <dict>
      <key>NSPrivacyCollectedDataType</key>
      <string>NSPrivacyCollectedDataTypePhotosorVideos</string>
      <key>NSPrivacyCollectedDataTypeLinked</key><true/>
      <key>NSPrivacyCollectedDataTypeTracking</key><false/>
      <key>NSPrivacyCollectedDataTypePurposes</key>
      <array><string>NSPrivacyCollectedDataTypePurposeAppFunctionality</string></array>
    </dict>
    <dict>
      <key>NSPrivacyCollectedDataType</key>
      <string>NSPrivacyCollectedDataTypeEnvironmentScanning</string>
      <key>NSPrivacyCollectedDataTypeLinked</key><true/>
      <key>NSPrivacyCollectedDataTypeTracking</key><false/>
      <key>NSPrivacyCollectedDataTypePurposes</key>
      <array><string>NSPrivacyCollectedDataTypePurposeAppFunctionality</string></array>
    </dict>
    <dict>
      <key>NSPrivacyCollectedDataType</key>
      <string>NSPrivacyCollectedDataTypeUserID</string>
      <key>NSPrivacyCollectedDataTypeLinked</key><true/>
      <key>NSPrivacyCollectedDataTypeTracking</key><false/>
      <key>NSPrivacyCollectedDataTypePurposes</key>
      <array><string>NSPrivacyCollectedDataTypePurposeAppFunctionality</string></array>
    </dict>
    <dict>
      <key>NSPrivacyCollectedDataType</key>
      <string>NSPrivacyCollectedDataTypeDeviceID</string>
      <key>NSPrivacyCollectedDataTypeLinked</key><true/>
      <key>NSPrivacyCollectedDataTypeTracking</key><false/>
      <key>NSPrivacyCollectedDataTypePurposes</key>
      <array><string>NSPrivacyCollectedDataTypePurposeAppFunctionality</string></array>
    </dict>
    <dict>
      <key>NSPrivacyCollectedDataType</key>
      <string>NSPrivacyCollectedDataTypeName</string>
      <key>NSPrivacyCollectedDataTypeLinked</key><true/>
      <key>NSPrivacyCollectedDataTypeTracking</key><false/>
      <key>NSPrivacyCollectedDataTypePurposes</key>
      <array><string>NSPrivacyCollectedDataTypePurposeAppFunctionality</string></array>
    </dict>
    <dict>
      <key>NSPrivacyCollectedDataType</key>
      <string>NSPrivacyCollectedDataTypeEmailAddress</string>
      <key>NSPrivacyCollectedDataTypeLinked</key><true/>
      <key>NSPrivacyCollectedDataTypeTracking</key><false/>
      <key>NSPrivacyCollectedDataTypePurposes</key>
      <array><string>NSPrivacyCollectedDataTypePurposeAppFunctionality</string></array>
    </dict>
    <dict>
      <key>NSPrivacyCollectedDataType</key>
      <string>NSPrivacyCollectedDataTypeOtherUserContent</string>
      <key>NSPrivacyCollectedDataTypeLinked</key><true/>
      <key>NSPrivacyCollectedDataTypeTracking</key><false/>
      <key>NSPrivacyCollectedDataTypePurposes</key>
      <array><string>NSPrivacyCollectedDataTypePurposeAppFunctionality</string></array>
    </dict>
    <dict>
      <key>NSPrivacyCollectedDataType</key>
      <string>NSPrivacyCollectedDataTypeOtherDiagnosticData</string>
      <key>NSPrivacyCollectedDataTypeLinked</key><true/>
      <key>NSPrivacyCollectedDataTypeTracking</key><false/>
      <key>NSPrivacyCollectedDataTypePurposes</key>
      <array><string>NSPrivacyCollectedDataTypePurposeAppFunctionality</string></array>
    </dict>
    <dict>
      <key>NSPrivacyCollectedDataType</key>
      <string>NSPrivacyCollectedDataTypeOtherDataTypes</string>
      <key>NSPrivacyCollectedDataTypeLinked</key><true/>
      <key>NSPrivacyCollectedDataTypeTracking</key><false/>
      <key>NSPrivacyCollectedDataTypePurposes</key>
      <array><string>NSPrivacyCollectedDataTypePurposeAppFunctionality</string></array>
    </dict>
  </array>

  <key>NSPrivacyAccessedAPITypes</key>
  <array>
    <dict>
      <key>NSPrivacyAccessedAPIType</key>
      <string>NSPrivacyAccessedAPICategoryUserDefaults</string>
      <key>NSPrivacyAccessedAPITypeReasons</key><array><string>CA92.1</string></array>
    </dict>
    <dict>
      <key>NSPrivacyAccessedAPIType</key>
      <string>NSPrivacyAccessedAPICategorySystemBootTime</string>
      <key>NSPrivacyAccessedAPITypeReasons</key><array><string>35F9.1</string></array>
    </dict>
    <dict>
      <key>NSPrivacyAccessedAPIType</key>
      <string>NSPrivacyAccessedAPICategoryFileTimestamp</string>
      <key>NSPrivacyAccessedAPITypeReasons</key><array><string>C617.1</string></array>
    </dict>
  </array>
</dict>
</plist>
```

The `OtherUserContent` and `OtherDataTypes` entries carry the two judgment calls
from 3.1i and 3.1h. If the operator takes the strict reading on either, drop
that entry from both the manifest and the label together — they must not
disagree.

---

## 10. What to re-check before submitting

These answers go stale when the pipeline changes. Each item names what would
change and how to check it in one command.

**Blocking — these must be done before the filing goes in.**

1. **Confirm the vendor terms** for both model calls (§4e). Not verifiable from
   this repo, and it is the one claim the Privacy Policy makes on someone else's
   behalf. Privacy Policy operator note 2 has been open since 2026-08-08.
2. **Decide the two judgment calls** and apply the decision to the label and the
   manifest together: the conversation surface's scope (3.1i) and the profile
   photo URL (3.1h).
3. **Decide the server-log question** (§7) — either take the conservative Device
   ID reading, or fix the Privacy Policy. Not both silent.
4. **Get the `PrivacyInfo.xcprivacy` into the app** (§9). It ships in the bundle;
   the labels alone are not sufficient.

**Fix before the build ships, not necessarily before the filing.**

5. F1, F3, F4, F5 — the four Privacy Policy corrections. F1 is the only one that
   is factually wrong rather than incomplete.
6. F6 — the camera permission string still says RoomStudio.

**Re-check whenever any of these changes.**

7. **A new model call, or a change to what §4a sends.**
   `grep -rn "anthropic" services/` — two call sites today. A third is a new
   disclosure. Widening the crops (`SHELL_EVIDENCE_MAX_CROPS`,
   `SHELL_EVIDENCE_CROP_M`) changes how much of a home is transmitted, and
   `SHELL_MATERIAL_MODEL` changes to whom.
8. **Any new per-user Firestore collection or GCS prefix.** It must land in
   `account_deletion.py`, in Privacy Policy §7, and be considered here. The
   deletion module's docstring already carries this instruction; this is the
   third place it now binds.
9. **APNs shipping.** `FirebaseMessaging` linked, or a call site supplying
   `fcm_token`, makes a push token collected (F4).
10. **A new permission.** Any `INFOPLIST_KEY_NS*UsageDescription` beyond the
    camera is a new category. There is exactly one today.
11. **A new SDK.** `Package.resolved` changing is not enough to matter; the
    `XCSwiftPackageProductDependency` section is what decides what is linked.
    An analytics or crash SDK appearing there flips three "Not collected" rows.
12. **Retention changes.** Re-run the four live checks in §5 — two bucket
    lifecycle rules, two Firestore TTL states — rather than reading
    `eventarc_setup.sh`, which F1 shows can be wrong about its own effect.
13. **`PERCEPTION_SUPPRESSED_CONCEPTS` widening** (0089's named seam). Adding
    concepts — screens showing faces, pets, documents — changes what §3.2's
    Sensitive Info note can claim.
14. **Payment.** Any StoreKit or payment path makes Financial Info and Purchases
    live, and Terms §11's cap stops being nominal at the same moment.
15. **A hosted share link.** Rung 0 (the calling card) sends nothing (§4d).
    Every rung above it moves room data off our systems to a third party and is
    a new disclosure — and is gated behind per-room deletion regardless
    (`docs/product/social-layer.md` §7).

---

## 11. The honest summary, in the product's own voice

If the labels had to be read aloud rather than transcribed:

> We hold photographs of the inside of your home for 24 hours and then delete
> them automatically. We keep the 3D room we build from them until you delete
> it. We know your account, your phone's model, and a random per-installation
> id — never your location, never your contacts, never a word about you from
> anywhere else. We send small close-up patches of your walls and floors to
> Anthropic to work out what they are made of; that is real photographic data
> from your room, and it is the only place pictures of your home go to anyone
> but our cloud provider. When you talk to the guest, we send words, never
> pictures. If someone is in the room, the system tries to cut them out of
> everything it measures, and we do not claim it always succeeds. There are no
> analytics, no advertising, and no tracking of any kind.

Everything in that paragraph is cited above.
