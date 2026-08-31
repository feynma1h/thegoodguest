# Decision notes

276 notes. **249 of them are `Decided`** -- those govern code that
ships today and are the ones worth reading before you change something. The
other 27 record decisions that were carried out, replaced, or
measured and refuted; they are kept because source comments cite them, not
because they constrain you.

This file is generated. Run `python3 tools/gen_decision_index.py` after adding
a note, and `--check` to verify the tree (duplicate numbers, statuses outside
the vocabulary, dangling links, a stale index).

The status vocabulary and the numbering rule live in
[0000-template.md](0000-template.md). Write a new note from that template.

## What is here

| status | count | means |
|---|---|---|
| `Refuted` | 3 | a measured negative -- read before proposing it again |
| `Superseded` | 7 | replaced by a later note |
| `Amended` | 2 | partly corrected by a later note |
| `Spent` | 15 | carried out; nothing left to comply with |
| `Decided` | 249 | governs code that ships today |

## Refuted (3)

*A measured negative -- read before proposing it again.*

| # | title | status |
|---|---|---|
| [0091](0091-mirror-as-mirror-probe.md) | Mirror-as-mirror: the depth-trust gate is not a mirror detector | Refuted |
| [0151](0151-splat-to-splat-registration-is-ajar-not-open.md) | splat-to-splat registration is ajar, not open | Refuted |
| [0181](0181-how-wrong-the-guessed-depth-is.md) | How wrong the guessed depth is, measured on rooms we already argue about | Refuted |

## Superseded (7)

*Replaced by a later note.*

| # | title | status |
|---|---|---|
| [0056](0056-design-language-and-stack-gating.md) | Design language: Apple-grade restraint; 3D-stack and conversation sequencing | Superseded by 0057, |
| [0063](0063-sam3d-layout-convention-verdict.md) | SAM 3D layout conventions: measured verdict (systematic ~90°) and the fix candidate | Superseded by 0065 |
| [0071](0071-room-boundary-source.md) | room-boundary source: raw plane anchors vs. RoomPlan vs. reconstructed geometry | Superseded by 0077 |
| [0120](0120-perception-build-layer-cache.md) | perception-obj builds cache layers via BuildKit inline cache on a stable tag | Superseded by 0199, |
| [0179](0179-sam3d-takes-a-pointmap-and-we-let-it-guess.md) | SAM 3D takes a LiDAR pointmap, and we let it guess one instead | Superseded by 0180 |
| [0263](0263-precision-is-a-gate-not-a-ranking.md) | precision against the box is a gate, not a ranking | Superseded by 0266 |
| [0265](0265-five-instruments-one-unrun-experiment.md) | five instruments for one choice, and the experiment none of them needs | Superseded by 0266 |

## Amended (2)

*Partly corrected by a later note.*

| # | title | status |
|---|---|---|
| [0099](0099-ci-scope-and-ios-posture.md) | CI scope, and why iOS CI is manual-only | Amended by measurement |
| [0173](0173-the-guest-cannot-tell-which-room-its-facts-describe.md) | the guest reads its own re-derived facts as stale, and says so | Amended by 0174 |

## Spent (15)

*Carried out; nothing left to comply with.*

| # | title | status |
|---|---|---|
| [0006](0006-perception-obj-syspath-hack-removal.md) | sys.path hack removal in process_receiver.py | Spent |
| [0015](0015-rate-limiting-concurrency-guards-deferred.md) | rate-limiting and concurrency guards deferred until v1 launch | Spent |
| [0018](0018-extend-0015-with-contract-shape-gaps.md) | Extend decision 0015 with contract-shape and production-hygiene gaps | Spent |
| [0030](0030-p2-gravity-gate-and-schema-version-rule.md) | P1→P2 gravity gate and schema_version enforcement rule | Spent |
| [0033](0033-c-decoupled-from-b-depth-residual.md) | C decoupled from B's depth residual; B-3 split per-tier | Spent |
| [0035](0035-p3-live-single-sided-contract.md) | P3 is a single-sided client build against a live contract | Spent |
| [0041](0041-p4-open-seams-and-on-device-gates.md) | P4 open seams and on-device verification gates (tracking note) | Spent |
| [0088](0088-launch-hardening-iam-audit.md) | Launch-hardening IAM audit: perception-obj SA + storage findings | Spent |
| [0101](0101-photos-history-purge.md) | Purging the real room photos from git history | Spent |
| [0106](0106-perception-obj-is-publicly-invokable.md) | perception-obj is publicly invokable, and stays that way for now | Spent |
| [0108](0108-back-against-the-wall.md) | "back against the wall" reads as a revert, and stands anyway | Spent |
| [0112](0112-clip-sign-ab-the-shipped-render-was-never-measured.md) | Clip-sign A/B: the shipped render was never measured, and the numbers invert the shear story | Spent |
| [0124](0124-assets-serial-signing-measured-not-fixed.md) | the assets endpoint's serial signing is real, measured, and not the P0 | Spent |
| [0182](0182-perception-obj-cannot-currently-be-rebuilt.md) | perception-obj cannot currently be rebuilt | Spent |
| [0256](0256-when-only-one-thing-fits-the-one-that-changes-wins.md) | when only one thing fits, the one that changes wins | Spent |

## Decided (249)

| # | title | status |
|---|---|---|
| [0001](0001-ios-first-pivot.md) | Pivot from photo-upload composition to iOS-first capture | Decided |
| [0002](0002-pose-pos-quat-not-matrix.md) | Pose representation: position + quaternion, not 4×4 matrix | Decided |
| [0003](0003-async-perception-dispatch.md) | async-perception-dispatch | Decided |
| [0004](0004-perception-receiver-semantics.md) | perception-receiver-semantics | Decided |
| [0005](0005-protobuf-version-workaround-in-container.md) | protobuf version workaround in container | Decided |
| [0007](0007-perception-obj-lazy-model-loading.md) | Lazy model loading in perception-obj | Decided |
| [0008](0008-bake-all-model-weights-at-build-time.md) | Bake all model weights at build time | Decided |
| [0009](0009-gfe-intercepts-healthz-on-cloud-run.md) | GFE intercepts /healthz on Cloud Run public URLs | Decided |
| [0010](0010-every-fastapi-route-needs-a-testclient-test.md) | Every FastAPI route needs a TestClient test, not just a handler test | Decided |
| [0011](0011-perception-obj-stuck-scene-lease-semantics.md) | perception-obj lease semantics: fix the stuck-scene bug | Decided |
| [0012](0012-perception-obj-lease-release-on-shutdown.md) | perception-obj lease release on shutdown | Decided |
| [0013](0013-capture-bundle-monotonic-timestamps.md) | Capture-bundle timestamps: device-monotonic, with wall-clock alongside | Decided |
| [0014](0014-ios-upload-auth-architecture.md) | iOS upload + auth architecture | Decided |
| [0016](0016-two-service-api-split.md) | Two-service split for API trust-boundary separation | Decided |
| [0017](0017-smoke-tool-manifest-and-upload-contract.md) | Smoke tool: manifest derivation and upload contract (pass 3) | Decided |
| [0019](0019-scene-read-endpoint-and-polling-contract.md) | Scene read endpoint and polling contract (smoke tool pass 4) | Decided |
| [0020](0020-smoke-tool-failure-mode-flag-semantics.md) | Smoke tool: failure-mode flag semantics (pass 5) | Decided |
| [0021](0021-protobuf-runtime-pin.md) | Pin protobuf runtime to match gencode in api-internal/api-public images | Decided |
| [0022](0022-ingest-must-propagate-user-id.md) | Ingest must propagate `user_id` to scene on all ingest branches | Decided |
| [0023](0023-eventarc-bucket-filter-and-handler-ignore.md) | Eventarc trigger uses bucket-level filter + handler-side `bundle.pb` check (addendum to 0014) | Decided |
| [0024](0024-phase-0h-liveness-only.md) | Phase 0h gates liveness, not readiness | Decided |
| [0025](0025-synthetic-fixtures-cannot-reach-ready.md) | Synthetic fixtures intentionally cannot reach reconstruction `ready` | Decided |
| [0026](0026-operator-account-gcp-permission-limits.md) | Operator accounts cannot call certain GCP APIs that scripts assumed they could | Decided |
| [0027](0027-enum-contract-requires-reader-redeploy.md) | enum contract additions require co-deploying the reader | Decided |
| [0028](0028-ios-in-monorepo.md) | iOS app lives in the monorepo (`ios/` directory), not a separate repo | Decided |
| [0029](0029-ios-phase-plan-and-contract-notes.md) | iOS capture app: five-phase plan and ARKit contract notes | Decided |
| [0031](0031-schema-version-string-fix.md) | schema_version string: "1.0.0" → "1" | Decided |
| [0032](0032-depth-intrinsics-correction.md) | Depth intrinsics: scaled RGB, not capturedDepthData | Decided |
| [0034](0034-arkit-camera-transform-landscaperight-frame.md) | ARKit `camera.transform` is a fixed landscapeRight frame | Decided |
| [0036](0036-user-id-under-anon-auth-and-serialization-order.md) | user_id under anonymous auth; offline-safe serialization order | Decided |
| [0037](0037-upload-session-local-persistence.md) | Upload-session local persistence: protected file, not Keychain | Decided |
| [0038](0038-upload-session-retry-policy.md) | /upload_session client retry/backoff policy | Decided |
| [0039](0039-firebase-access-before-configure.md) | Firebase calls in property defaults fire before configure() | Decided |
| [0040](0040-p4-blob-upload-single-shot-background-urlsession.md) | P4 blob upload: single-shot whole-blob PUT over background URLSession | Decided |
| [0042](0042-upload-session-record-cafufa.md) | Upload-session record relaxes to CompleteUntilFirstUserAuthentication (addendum to 0037) | Decided |
| [0043](0043-blob-durability-application-support.md) | Capture blob durability: move to Application Support with CAFUFA | Decided |
| [0044](0044-p4-on-device-verification.md) | P4 on-device verification: finalize hardware-proven (alive-process), relaunch-recovery gap localized | Decided |
| [0045](0045-p5-relaunch-recovery-cluster.md) | P5 relaunch-recovery cluster design (c/b/a code-complete, OS-kill gate remains) | Decided |
| [0046](0046-p5a-poll-client-design.md) | P5(a) poll client: two independent start paths, lenient status decode | Decided |
| [0047](0047-p5a-scene-poll-design.md) | P5(a) scene-status poll client: the non-obvious design choices | Decided |
| [0048](0048-finalize-failed-strand-risk.md) | release_failed strand risk: bounded retry + alertable log, not a reconciliation system | Decided |
| [0049](0049-upload-remint-failure-semantics.md) | upload re-mint failure semantics: loop-guard fatal, persist-failure deferral | Decided |
| [0050](0050-web-app-hosting-and-framework.md) | Web app: Firebase Hosting + Next.js static export | Decided |
| [0051](0051-cross-device-identity-linkage.md) | Cross-device identity: upgrade anonymous auth to a linked real sign-in | Decided |
| [0052](0052-arkit-native-object-placement.md) | ARKit-native object placement: single-view depth fit + SAM 3D layout prior | Decided |
| [0053](0053-splat-renderer-spark-webgl2.md) | Splat renderer: Spark (three.js/WebGL2), contained in one component | Decided |
| [0054](0054-web-read-contract.md) | Web read contract: scene list, signed-assets endpoint, CORS posture | Decided |
| [0055](0055-founding-vision-recovered.md) | Founding vision recovered: what survived the pivot, what didn't | Decided |
| [0057](0057-good-guest-design-language.md) | Good Guest design language: warm hospitality supersedes 0056's visual specifics | Decided |
| [0058](0058-conversation-stage-1-design.md) | Conversation stage 1: transport, grounding, state, the guest contract, cost, client | Decided |
| [0059](0059-conversation-stage1-implementation-notes.md) | Conversation stage 1: implementation choices not in the design | Decided |
| [0060](0060-stranded-scene-gap-and-reenqueue.md) | stranded scenes: platform-queued retries can't reclaim; out-of-band re-enqueue is the cure | Decided |
| [0061](0061-oom-cascade-retry-traceback-pin.md) | OOM cascade root cause: the in-except retry pinned the failed attempt's GPU tensors | Decided |
| [0062](0062-frame-sampling-policy.md) | frame sampling: deterministic pose-diverse FPS, budget as the guarantee | Decided |
| [0064](0064-identity-roots-on-the-phone.md) | 0051 implementation: identity roots on the phone | Decided |
| [0065](0065-sam3d-layout-convention-probe-closure.md) | SAM 3D layout conventions: probe closure (conjugate wxyz, pytorch3d camera basis, arbitrary canonical frames) | Decided |
| [0066](0066-room-shell-design.md) | Room shell: measured planes on the wire, textured-quad shell as a second perception stage | Decided |
| [0067](0067-arkit-only-placement-quality.md) | ARKIT_ONLY placement quality: pixel-footprint correspondence, silhouette fitting, measured-plane contact priors | Decided |
| [0068](0068-placement-quality-build-verdicts.md) | placement-quality build verdicts: brief contracts vs measured reality | Decided |
| [0069](0069-generated-shell-surfaces.md) | Shell surfaces: generated parametric materials replace the photographic bake | Decided |
| [0070](0070-shell-surfaces-build-verdicts.md) | Shell-surfaces build verdicts: closure calibration, inference amendments, and the person-contamination finding | Decided |
| [0072](0072-ios-design-lidar-only-pivot.md) | iOS app design locked; LiDAR-only client pivot | Decided |
| [0073](0073-launch-restore-scope.md) | Relaunch recovery is launch-scoped and acknowledgement-aware | Decided |
| [0074](0074-icloud-backup-migration-phantom-room.md) | iCloud-backup migration: what carries over, and the phantom-room row | Decided |
| [0075](0075-lidar-adjudication-knobs-not-the-defect.md) | LiDAR adjudication: merge knobs measured correct; the defects are admission, closure, and instrument variance | Decided |
| [0076](0076-roomplan-corun-spike.md) | RoomPlan co-run spike: verdicts (board 3 → board 7) | Decided |
| [0077](0077-roomplan-integration-design.md) | RoomPlan integration: CapturedRoom as room + object skeleton, JSON verbatim on the wire, boxes carry placement | Decided |
| [0078](0078-envelope-selection-height-reach.md) | Envelope-wall selection: height-reach, not classification (a measured amendment to 0077's brief) | Decided |
| [0079](0079-corun-attach-depth-loss.md) | Same-turn RoomPlan co-run attach loses sceneDepth; frame-observed re-assert is the production guard | Decided |
| [0080](0080-rp8-walk-verdicts.md) | RP-8 operator walk: verdicts, defect classes, fork resolutions | Decided |
| [0081](0081-axis-mapping-cloud-instrument.md) | Box splat-axis mapping: appearance scoring refuted, cloud alignment adopted | Decided |
| [0082](0082-walk-classes-2-5-passes.md) | RP-8 walk classes 2–5: placement post-passes + the kink fix | Decided |
| [0084](0084-terminal-state-reclaim-and-blocked-reupload.md) | Terminal-state reclaim (CaptureReaper) + the server-blocked re-upload coordinator | Decided |
| [0085](0085-release-residue-sitting-verdicts.md) | Release-residue sitting: Gate 2b closed, Fork A answered, and three defects the runs surfaced | Decided |
| [0086](0086-retention-design-f5-f6.md) | Retention design for scenes + perception outputs (gaps F5/F6) | Decided |
| [0087](0087-upload-session-hardening-dispositions.md) | /upload_session hardening: gaps a/b/c/F1/F2/F3 dispositions | Decided |
| [0089](0089-person-suppression-only-concept.md) | Person as a suppression-only SAM 3 concept | Decided |
| [0090](0090-perception-obj-runtime-sa.md) | perception-obj runs as a dedicated least-privilege runtime SA | Decided |
| [0094](0094-google-web-read-provider.md) | Google as an additive web read-provider; never-create is provider-agnostic | Decided |
| [0095](0095-account-deletion.md) | Account deletion: the map, the ordering, and why the identity goes last | Decided |
| [0096](0096-sizes-and-clearance-floors.md) | Sizes and clearance floors: what the extents actually support | Decided |
| [0097](0097-reveal-choreography-redesign.md) | reveal choreography redesign: the room draws itself, then fills, then settles | Decided |
| [0098](0098-capture-ceiling.md) | Per-UID capture ceiling: bounding GPU spend, measured | Decided |
| [0100](0100-material-family-instability.md) | Material-family instability is the gate floor, not the evidence | Decided |
| [0102](0102-deployed-render-blocker-chain.md) | The deployed room-render blocker was a chain of three, not one | Decided |
| [0103](0103-account-deletion-live-findings.md) | Account deletion: two defects that only a live probe could find | Decided |
| [0104](0104-walk-classes-and-the-rotation-evidence-limit.md) | The 0085 walk: four fixable classes, and rotation's measured evidence limit | Decided |
| [0105](0105-ingest-requires-every-declared-blob.md) | Ingest requires every blob the bundle declares | Decided |
| [0107](0107-the-voice-evals-lag-the-charter.md) | the voice evals lag the charter at PROMPT_VERSION 3 | Decided |
| [0109](0109-node-comes-from-conda-not-apt.md) | Node comes from conda-forge, not apt | Decided |
| [0110](0110-background-launch-transfer-rate-limiter.md) | The bundle.pb stall is iOS's background-launch rate limiter, not our defect | Decided |
| [0111](0111-live-activity-terminal-narration-gap.md) | The Live Activity had no way to say the send finished | Decided |
| [0114](0114-force-quit-is-not-os-kill.md) | Force-quit is not OS-kill: the background-relaunch race cannot occur on the path we kept testing | Decided |
| [0115](0115-the-anon-uid-churns.md) | The anonymous UID churns, and the stand-down drains one room per launch | Decided |
| [0116](0116-mint-contract-force-remint.md) | force_remint: separating "retry my POST" from "my session is dead" | Decided |
| [0117](0117-composer-confirming-is-reachable.md) | the composer's `confirming` phase is reachable, and stays | Decided |
| [0118](0118-ios-google-linking.md) | iOS Google linking: the second provider rides Apple's rails | Decided |
| [0119](0119-google-config-seam-preflight.md) | Google's config seam: committed URL scheme, gitignored client ID, preflight instead of a crash | Decided |
| [0122](0122-hero-is-the-reveal.md) | the landing hero is the reveal, not a room | Decided |
| [0123](0123-render-payload-is-network-bound.md) | the render payload is network-bound; parse has no headroom to give | Decided |
| [0125](0125-spz-is-a-transcode-not-a-re-bake.md) | the compressed tier is a transcode, and Spark already reads it | Decided |
| [0126](0126-compressed-tier-sits-beside-the-ply.md) | the compressed tier sits beside the PLY, discovered by a sibling index | Decided |
| [0127](0127-the-reveal-waits-for-bytes.md) | the reveal waits for bytes; fetch order is not the lever | Decided |
| [0129](0129-what-a-moved-object-looks-like.md) | Probe 1: what a real object actually looks like moved, and what actually breaks | Decided |
| [0130](0130-r3f-reconciles-spark.md) | Probe 2: R3F reconciles a Spark SplatMesh, and load orchestration belongs outside the renderer | Decided |
| [0131](0131-design-specification-contract.md) | The Design Specification: a proposal sitting beside the measurement, never over it | Decided |
| [0132](0132-stage-2-tool-surface.md) | Stage 2's tool surface: the guest states intent, the server solves geometry | Decided |
| [0133](0133-stage-2-scope-undo-and-sequencing.md) | Stage 2 scope: move and remove ship, the catalog does not, the ledger stays banned | Decided |
| [0135](0135-yaw-convention-and-the-clip-volume.md) | `yaw_rad` is not the rotation the viewer applies, and the clip volume is built with the wrong sign | Decided |
| [0136](0136-a-proposal-is-held-to-the-rooms-own-standard.md) | A proposal is held to the standard the measurement meets, not a better one | Decided |
| [0137](0137-box-dims-carry-axis-semantics.md) | `roomplan_box.dims` is (width, height, depth), and 0096's premise does not hold | Decided |
| [0138](0138-the-keychain-survived-the-churn.md) | the Keychain survived the churn | Decided |
| [0139](0139-firebase-deletes-its-own-credential.md) | Firebase deletes its own credential | Decided |
| [0140](0140-the-second-churn-has-no-trigger-yet.md) | the second churn has no trigger yet | Decided |
| [0141](0141-a-lost-identity-is-not-a-first-run.md) | a lost identity is not a first run | Decided |
| [0142](0142-compress-is-a-process-stage.md) | /compress is a stage on perception-obj, not a sidecar service | Decided |
| [0143](0143-extent-axes-are-declared-not-inferred.md) | the up extent is declared per box, and the horizontals stay unnamed | Decided |
| [0146](0146-view-selection-does-not-predict-reconstruction-quality.md) | view selection does not predict reconstruction quality | Decided |
| [0147](0147-levelling-is-a-different-degree-of-freedom.md) | levelling is a different degree of freedom from the dead one | Decided |
| [0148](0148-a-surface-needs-a-top-and-a-short-splat-needs-a-face.md) | a surface needs a top, and a short splat needs a face to sit on | Decided |
| [0149](0149-one-object-one-cluster-whatever-sam-calls-it.md) | one object, one cluster, whatever SAM calls it | Decided |
| [0150](0150-capture-coverage-feedback-is-not-the-fix.md) | capture-coverage feedback is not the fix for truncation | Decided |
| [0152](0152-every-view-is-a-partial-view.md) | every view is a partial view, and that is the regime | Decided |
| [0153](0153-nobody-ever-looked-at-the-picture.md) | nobody ever looked at the picture | Decided |
| [0154](0154-how-much-of-the-object-a-frame-sees.md) | how much of the object a frame sees, measured properly | Decided |
| [0155](0155-the-single-viewpoint-ceiling.md) | the single-viewpoint ceiling, and why guidance cannot pass it | Decided |
| [0156](0156-the-vision-model-cannot-settle-the-facing-either.md) | the vision model cannot settle the facing either | Decided |
| [0157](0157-a-correction-departs-from-a-default.md) | a correction departs from a default, not from a measurement | Decided |
| [0158](0158-the-turn-is-a-selection.md) | the turn is a selection between two candidates, not a rotation | Decided |
| [0159](0159-turning-it-did-not-give-you-eyes.md) | the guest changes a facing it cannot see, on the person's authority | Decided |
| [0160](0160-the-per-box-view-budget-is-not-the-constraint.md) | the per-box view budget is not the constraint | Decided |
| [0161](0161-the-reconstruction-carries-what-it-is-shown.md) | the reconstruction carries what it is shown | Decided |
| [0162](0162-the-better-frame-did-not-reconstruct-better.md) | the better frame did not reconstruct better | Decided |
| [0163](0163-a-trust-gate-only-certifies-what-it-covers.md) | a trust gate only certifies the population it covers | Decided |
| [0164](0164-restoring-a-swept-capture-is-not-an-upload.md) | restoring a swept capture is not an upload | Decided |
| [0165](0165-what-the-missing-surface-is-missing-to.md) | what the missing surface is missing to | Decided |
| [0166](0166-two-reconstructions-are-two-different-objects.md) | two reconstructions of one object are two different objects | Decided |
| [0169](0169-the-room-knows-which-way-the-cupboard-faces.md) | the room supplies the ground truth the facing sign never had | Decided |
| [0170](0170-the-box-carries-the-facing-the-room-cannot-label-it.md) | the box carries the facing; the room still cannot label a row | Decided |
| [0171](0171-the-layout-knows-the-sign-two-times-in-three.md) | the layout knows the sign, two times in three | Decided |
| [0172](0172-an-eval-pins-behaviour-not-a-clause.md) | a voice eval pins behaviour, and cannot tell you which sentence holds it up | Decided |
| [0174](0174-the-room-re-derived-it-so-say-so.md) | the room already re-derived it, and the block never said so | Decided |
| [0175](0175-the-pin-covers-everything-the-guest-reads.md) | a version number that guards half a contract | Decided |
| [0176](0176-the-tinted-icon-is-not-a-multiply.md) | the tinted icon is not a multiply | Decided |
| [0177](0177-the-seating-question-is-not-answerable-yet.md) | the seating question is not answerable yet | Decided |
| [0178](0178-the-guest-holds-a-height-and-says-it-cannot-say.md) | the guest holds a height and says it cannot say | Decided |
| [0180](0180-the-pointmap-conditions-the-shape.md) | The pointmap conditions the shape, not only the layout | Decided |
| [0183](0183-the-facing-correction-is-a-concession.md) | the facing correction is a concession, not a feature | Decided |
| [0184](0184-the-room-already-knew-which-chair-was-red.md) | the room already knew which chair was red | Decided |
| [0185](0185-a-number-is-not-a-referent.md) | a number is not a referent | Decided |
| [0186](0186-rule-five-forbade-what-rule-six-grants.md) | rule 5 forbade what rule 6 grants | Decided |
| [0187](0187-a-release-check-needs-a-positive-control.md) | a content-marker release check needs a positive control | Decided |
| [0188](0188-the-key-costs-what-it-guards-not-what-it-holds.md) | the renderer key costs what it guards, not what it holds | Decided |
| [0190](0190-the-registry-keeps-three-images-by-name.md) | the registry keeps three images, and one of them is kept by name | Decided |
| [0191](0191-the-image-carries-the-checkpoints-twice.md) | the perception image carries the SAM 3D checkpoints twice | Decided |
| [0192](0192-perception-geom-is-retired.md) | perception-geom is retired, and it was a door, not a line item | Decided |
| [0193](0193-the-mark-is-generated-not-copied.md) | the mark is generated, not copied | Decided |
| [0197](0197-the-uncropped-photograph-is-not-a-better-photograph.md) | the uncropped photograph is not a better photograph | Decided |
| [0198](0198-the-mask-is-the-photograph-sam3d-sees.md) | the mask is the photograph SAM 3D sees | Decided |
| [0199](0199-the-inline-cache-destroys-itself-by-being-used.md) | the inline cache destroys itself by being used | Decided |
| [0200](0200-the-tag-must-name-what-cloud-run-pins.md) | the tag must name what Cloud Run pins | Decided |
| [0201](0201-the-repair-is-judged-by-what-it-added.md) | the repair is judged by what it added | Decided |
| [0202](0202-the-residue-was-never-asked-where-anything-is.md) | the residue was never asked where anything is | Decided |
| [0203](0203-a-second-arm-is-not-a-better-object.md) | a second arm is not a better object | Decided |
| [0204](0204-the-arm-that-ships-is-chosen-by-looking-at-it.md) | the arm that ships is chosen by looking at it | Decided |
| [0205](0205-fill-sees-one-axis.md) | fill sees one axis | Decided |
| [0206](0206-no-rooms-and-could-not-ask.md) | "no rooms" and "could not ask" are different answers | Decided |
| [0207](0207-a-layer-is-not-a-feed.md) | a layer is not a feed | Decided |
| [0208](0208-sharing-cuts-where-the-pipeline-already-cut.md) | sharing cuts where the pipeline already cut | Decided |
| [0209](0209-comparison-between-people-is-evidence-not-a-surface.md) | comparison between people is evidence, not a surface | Decided |
| [0210](0210-a-cold-room-is-two-deletions-and-an-audience.md) | a cold room is two deletions and an audience | Decided |
| [0211](0211-the-flag-was-never-in-the-image.md) | the flag was never in the image | Decided |
| [0212](0212-the-three-flags-are-one-decision.md) | the three flags are one decision | Decided |
| [0213](0213-two-candidates-refuse-rather-than-pick.md) | two candidates refuse rather than pick | Decided |
| [0214](0214-the-provenance-line-describes-the-room-on-screen.md) | the provenance line describes the room on screen | Decided |
| [0215](0215-the-conditional-survived-the-word.md) | the conditional survived the word | Decided |
| [0216](0216-a-count-that-cannot-exist.md) | a count that cannot exist | Decided |
| [0217](0217-the-declaration-is-the-stand-down.md) | the declaration is the stand-down | Decided |
| [0218](0218-the-bridge-was-never-waiting-on-the-fetch.md) | the bridge was never waiting on the fetch | Decided |
| [0219](0219-the-pin-covers-what-the-model-reads.md) | the pin covers what the model reads | Decided |
| [0220](0220-the-refusal-names-a-handle.md) | the refusal names a handle a person would have used | Decided |
| [0221](0221-a-rooms-eligibility-is-a-date.md) | a room's eligibility is a date, not a field | Decided |
| [0222](0222-the-card-draws-the-boundary-and-prints-the-measurement.md) | the card draws the boundary and prints the measurement | Decided |
| [0223](0223-the-yaw-is-not-a-measurement.md) | the yaw is not a measurement | Decided |
| [0224](0224-a-pinned-action-does-not-share-a-column.md) | a pinned action does not share a column | Decided |
| [0225](0225-coverage-for-visibility-purity-for-orientation.md) | coverage for visibility, purity for orientation | Decided |
| [0226](0226-the-family-map-and-the-prompt-are-one-contract.md) | the family map and the prompt are one contract | Decided |
| [0227](0227-an-unmatched-box-has-five-causes-not-two.md) | an unmatched box has five causes, not two | Decided |
| [0228](0228-the-oom-is-headroom-not-size.md) | the OOM is headroom, not size | Decided |
| [0229](0229-the-second-arm-is-also-the-oom-fallback.md) | the second arm is also the OOM fallback | Decided |
| [0230](0230-the-skip-is-a-plan-time-statement.md) | the skip is a plan-time statement | Decided |
| [0231](0231-a-band-the-camera-never-saw.md) | a band the camera never saw | Decided |
| [0232](0232-the-floor-tolerance-is-sized-for-the-floor.md) | the floor tolerance is sized for the floor | Decided |
| [0233](0233-the-third-axis-can-only-veto.md) | the third axis can only veto | Decided |
| [0234](0234-the-selector-can-reject-but-not-rank.md) | the selector can reject, but not rank | Decided |
| [0235](0235-a-quarter-of-rp6g2-is-dark.md) | a quarter of rp6g2 is dark | Decided |
| [0236](0236-a-veto-is-a-re-roll-not-a-filter.md) | a veto is a re-roll, not a filter | Decided |
| [0237](0237-dead-code-rusts-shut.md) | dead code rusts shut rather than staying ready | Decided |
| [0238](0238-one-slot-is-what-keeps-the-rule.md) | one notice slot, rendered in every variant, is what keeps 0224's rule | Decided |
| [0239](0239-drain-gate-last-decrement-fires-in-its-own-turn.md) | the last decrement fires the gate in its own turn | Decided |
| [0240](0240-the-dark-tail-is-a-covered-lens.md) | the dark tail is a covered lens | Decided |
| [0241](0241-the-capture-measures-darkness-and-does-not-act-on-it.md) | the capture measures darkness and does not act on it | Decided |
| [0242](0242-the-disclosure-is-measured.md) | A privacy disclosure is measured, not described | Decided |
| [0243](0243-the-flip-is-three-assertions.md) | the flip is three assertions, not one command | Decided |
| [0245](0245-the-name-is-the-register-it-was-built-in.md) | the name is the register it was built in | Decided |
| [0246](0246-yanked-transitive-dependency.md) | a yanked transitive dependency, and why the cure is a rebuild | Decided |
| [0247](0247-the-room-is-not-good-enough-and-coverage-is-not-the-lever.md) | the room is not good enough, and coverage is not the lever | Decided |
| [0248](0248-the-mark-is-the-oo-and-never-sits-beside-it.md) | the mark is the "oo", and never sits beside it | Decided |
| [0249](0249-two-terracottas-because-the-brand-ink-fails-aa.md) | two terracottas, because the brand ink fails AA on text | Decided |
| [0250](0250-the-wordmarks-oo-is-the-mark-itself.md) | the wordmark's "oo" is the mark itself | Decided |
| [0251](0251-the-splash-carries-whole-letters.md) | the splash carries whole letters, and the cut is found by crossings | Decided |
| [0252](0252-the-instrument-said-the-app-was-broken.md) | three more corrections to the layout audit, and the shape they share | Decided |
| [0253](0253-the-pinned-action-rule-was-never-propagated.md) | the pinned-action rule was never propagated | Decided |
| [0254](0254-home-is-a-claim-a-sentence-and-an-action.md) | home is a claim, a sentence, and an action | Decided |
| [0255](0255-the-splash-hands-the-mark-over.md) | the splash hands the mark over, to a measured slot | Decided |
| [0257](0257-one-grid-and-an-instrument-to-check-it.md) | one grid for every screen, and an instrument to check it | Decided |
| [0258](0258-type-scales-by-what-it-does.md) | type scales by what it does, and control labels are clamped rather than capped | Decided |
| [0259](0259-disqualify-a-frame-do-not-rank-it.md) | disqualify a frame, do not rank it | Decided |
| [0260](0260-a-probe-must-not-be-able-to-become-pipeline-state.md) | a probe must not be able to become pipeline state | Decided |
| [0261](0261-the-overlap-sort-rewards-a-mask-that-stops-early.md) | the overlap sort rewards a mask that stops early | Decided |
| [0262](0262-the-overlap-sort-is-flat.md) | the overlap sort is flat, and its tie-break is capture order | Decided |
| [0264](0264-read-the-model-not-the-wrapper.md) | the upstream source is vendored, pinned, and enforced | Decided |
| [0266](0266-keep-the-longer-mask.md) | keep the longer mask, and do not merge objects to hide a bad one | Decided |
| [0267](0267-the-newest-capture-has-no-depth.md) | the newest capture carries no LiDAR depth, and that disables mask repair | Decided |
| [0268](0268-the-leg-is-not-under-the-threshold.md) | the leg is not hiding under the 0.5 threshold | Decided |
| [0269](0269-the-click-loop-deleted-the-leg.md) | the click loop deleted the leg, and the guard called it progress | Decided |
| [0270](0270-reserve-a-whole-view-per-box.md) | reserve a whole view per box, rather than reject the cut ones | Decided |
| [0271](0271-nine-of-fourteen-objects-have-no-box.md) | nine of fourteen object kinds have no box, and every instrument needs one | Decided |
| [0272](0272-suppressing-a-person-removes-the-furniture-they-touch.md) | suppressing a person removes the furniture they touch | Decided |
| [0273](0273-the-keyframes-are-already-a-video.md) | the keyframes are already a video, and that is what makes a tracker applicable | Decided |
| [0274](0274-sam31-is-the-tracker.md) | SAM 3.1 is a tracker release, and the image path has nowhere to move to | Decided |
| [0275](0275-the-candidate-tag-is-a-shared-pointer.md) | the `candidate` tag is one shared pointer, and two lanes can hold it | Decided |
| [0276](0276-the-session-layer-carries-environment.md) | the session layer carries environment, not just dispatch | Decided |
| [0277](0277-sam31s-tracker-outruns-the-pinned-torch.md) | SAM 3.1's tracker needs a newer torch than SAM 3D lets us have | Decided |
| [0278](0278-the-tracker-has-nowhere-to-put-its-memory.md) | the tracker has nowhere to put its memory, and the detector wants 1.27 GiB | Decided |
| [0279](0279-the-ids-survive-a-visit-not-a-revisit.md) | the IDs survive a visit, not a revisit | Decided |
| [0280](0280-ray-convergence-does-not-separate-neighbours.md) | ray convergence does not separate a fragment from its neighbour | Decided |
| [0281](0281-one-object-many-prompts.md) | one object, many prompts: the duplication 0279 does not measure | Decided |
| [0282](0282-the-border-rule-is-the-whole-filter.md) | the border rule is the whole filter, and its margin is an operator call | Decided |
| [0283](0283-the-short-mask-is-the-one-without-legs.md) | the shorter of two nested masks is the one without the legs | Decided |
| [0284](0284-appearance-calibrates-well-and-fails-in-the-room.md) | appearance separates the objects that have boxes, and merges the ones that do not | Decided |
| [0285](0285-volume-merges-what-colour-and-position-could-not.md) | the volume merges what a point and a colour could not | Decided |
| [0286](0286-what-protects-the-scene-is-not-the-lease.md) | what protects the scene is not the lease | Decided |
| [0287](0287-every-state-not-every-screen.md) | the gallery photographs every state, not every screen | Decided |
| [0288](0288-the-second-leg-is-in-shadow.md) | the second leg is in the frame, in shadow, five pixels away | Decided |
| [0289](0289-a-click-on-the-missing-part.md) | a click on the missing part, and the luma guard that refuses it | Decided |
| [0290](0290-the-unclaimed-signal-cannot-be-tested-here.md) | the unclaimed signal cannot be tested here, and without depth it is not a pointer | Decided |
| [0291](0291-the-vision-model-points-and-the-frame-is-sideways.md) | a vision model points at the missing part, and the frame is stored sideways | Decided |
| [0292](0292-the-survivor-inherits-the-pairs-score.md) | collapsing a nested pair must not re-rank it against everything else | Decided |
