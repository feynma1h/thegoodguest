# 0058 — Conversation stage 1: transport, grounding, state, the guest contract, cost, client

**Date:** 2026-07-21
**Status:** Decided (design; implementation pending — extends 0056's conversation
staging and 0057's voice charter; changes neither)

## Context

0056 staged conversation in two parts and scheduled stage 1 — read-only Q&A grounded
in what perception produced — directly after board item 1's deploy, which landed
2026-07-21. 0057 gave the guest its voice and shipped the composer disabled, honestly
labeled. Four things were pre-decided and not relitigated here: SSE-style streaming on
api-public; conversation state in Firestore keyed by scene; Claude as the reasoning
model; the narration card + composer slot as the UI home, under the guest's honesty
charter. This note records the seven-fork design session that turned those pins into a
buildable contract. The scope line, verbatim:

> Stage 1 is the ready room's read-only conversation — a real composer replacing the
> disabled one, streamed guest replies grounded in SceneFacts and nothing else, a
> durable turn transcript with stub collapse, honest budget rests, and template
> narration handing off to live speech — everything else in the design file remains
> summoned later, and the room page already holds every seat it will occupy.

## What we tried / rejected (named rejections — do not re-explore without new facts)

- **Native EventSource** — GET-only, no Authorization header. Token-in-query-string
  leaks ID tokens into logs; cookie auth means credentialed CORS plus a parallel auth
  path. fetch + ReadableStream is forced. Two-phase POST-then-stream rejected too:
  the second leg has the same auth problem, twice the failure surface.
- **Raw manifest in the prompt** — hands the model quaternions and float triples and
  invites 3D arithmetic: fabricated measurements wearing a measured costume, the one
  honesty failure that is silent. Also burns tokens and destroys the cacheable prefix.
- **Facts baked into the manifest at perception time** — facts logic must iterate
  without reprocessing scenes; manifests stay raw truth. Facts compute on-read in
  api-public.
- **Client-computed splat bounds as a facts source** — the viewer knows extents after
  load, but client-supplied data feeding the guest's "measured" claims crosses the
  trust boundary. Facts derive server-side from server-held data only.
- **Orientation-derived facts** ("the sofa faces the window") — SAM 3D layout
  conventions are runtime-unverified (CLAUDE.md); position-derived facts don't share
  that exposure. Banned until board item 1's verification event.
- **Summarization, twice** — rejected for model context (model-generated content
  feeding future grounding is a compounding fabrication channel; the window is last-N
  verbatim) and rejected for transcript stub labels (stubs are the user's own words,
  truncated). The eventual memory mechanism is ledger pins-as-context, not summaries.
- **Remote-config prompt storage** — no test gates it, environments drift, and it
  breaks per-turn prompt_version recording. The prompt is code.
- **Reply chips** ("short version" / "walk me through it") — require machine-
  identifiable invitations, i.e. structured output, which fights token streaming; and
  chips that only sometimes match the invitation violate no-fake-UI worse than their
  absence. Invitations are plain text; the user types.
- **Pulling pre-launch gap (b) forward** — general per-UID velocity limiting is
  launch-hardening infrastructure (trigger unchanged: first non-developer user).
  Stage 1 ships endpoint-local *cost bounds* (below), which make worst-case spend
  finite; velocity layers on top at launch.
- **Model-visible budget state** — the guest never performs resource anxiety; budgets
  are the house's business. Refusals are server-authored fixed lines in voice.

## What we chose

**Transport.** `POST /scenes/{scene_id}/conversation/messages` body
`{text, client_msg_id}`; the response IS the stream: `text/event-stream`, hand-parsed
from fetch. One stream per turn; no subscription channel exists. SSE framing with
named events (`delta`, `done`, `error`) — a vocabulary of ours, a transform of the
model stream, never a passthrough. Errors split at the stream boundary: everything
checkable pre-generation returns the existing JSON error contract; once streaming
starts, failures travel as a terminal `error` event. Cloud Run: `--timeout` raised
30 → 120 s (ships with this feature's deploy; 120 = 60 s model-call cap + shield drain
+ persist margin). The route is api-public's first async handler — a sync streaming
handler would hold a threadpool slot for the whole turn — with strict IO discipline:
every blocking call (history load, persist, budget reads) via `asyncio.to_thread` or
before the generator starts; this service was just un-async'd to fix loop-blocking and
the new route must not reintroduce it. On client disconnect the server shields
generation to completion — drains the model stream, persists, exits, all inside the
still-open request (the only place Cloud Run guarantees CPU). The client never resumes
a stream; it refetches state.

**Grounding.** `derive_scene_facts(manifest) → SceneFacts` — pure, typed,
deterministic, unit-tested, service-local in api-public — is the model's ENTIRE
world; the raw manifest never enters the prompt, so grounding is enforced by
construction, not discipline. Five fact classes: inventory with confidence tiers
(from frames_observed / cluster_spread); pairwise center-to-center distances;
vertical relations between centers (relative only — no floor exists); provenance;
and a machine-generated limits list (what this scene's data cannot answer). Distance
epistemics live inside the strings: comparative/ordinal claims are freely speakable;
absolute quantities are speakable only as server-formatted strings carrying their own
framing ("about 1.3 m between their centers"), pre-rounded to honest precision;
restating any distance as a gap or clearance is forbidden until extents ship. Same
rule for vertical deltas. `SceneFacts` carries `facts_version` (int). This layer is
the spatial-relationship graph's v0. The top manifest gap is per-object metric
extents — perception has them at fusion time and drops them; adding them (manifest
v2.x, post-verification) unlocks sizes and clearances. Multimodal grounding (frames
to Claude) is a separate future fork.

**State.** Top-level `conversations` collection, deterministic doc id
`{scene_id}__{user_id}` — per-scene+user now (zero cost today, no migration when
sharing arrives; a shared viewer should not inherit the owner's transcript by
default). Not nested under `scenes/` — that's another service's write domain. Turns
are the atomic unit: one doc per COMPLETED turn in a `turns` subcollection, doc id =
six-digit zero-padded turn_index, fields `{turn_index, client_msg_id, user_text,
assistant_text, created_at, completed_at, facts_version, prompt_version, model,
usage, finish_reason, flags}`. A half-persisted turn is unrepresentable. The
conversation doc carries `{turn_count, cumulative usage, active_turn, day,
turns_today, rested state}`, maintained in the accept/persist transactions.
`client_msg_id` dedupes at accept (replay the stored turn, never regenerate) and is
the client's refetch-confirmation key. Server-only writes: no Firestore
security-rules surface opens; the web client never touches Firestore. Model context
window: last N=20 turns verbatim + the always-present facts block. Client wire shape
via `_turn_to_client_dict` (mirroring `_scene_to_client_dict`): `{turn_index,
client_msg_id, user_text, assistant_text, created_at}` — internal fields (usage,
model, prompt_version, facts_version) never enter the wire contract.
`GET /scenes/{scene_id}/conversation` → meta (incl. nullable `rested_until`) + last
~50 turns + a `before=turn_index` cursor defined now (client v1 may ignore it);
200-empty for no conversation; 409 `scene_not_ready` until ready, both verbs.
**F6 inheritance, stated as fact:** Firestore never cascades deletes — scene TTL
alone would orphan conversations and turns; plan per-collection-group TTL on
`turns.created_at` + `conversations`, or explicit recursive delete in the sweep.

**The guest.** The prompt is code: `guest_prompt.py` owns `PROMPT_VERSION`, the
static charter + exemplars, and `build_system_prompt(facts)`. A pinned test asserts
`(PROMPT_VERSION, sha256(static charter))` — changing the prompt without bumping the
version goes red. Assembly order is fixed for caching and safety: global static →
per-scene facts → messages; user text never enters the system prompt. "I can't see
that yet" is two-level: capability truth in the charter (no moving things, no
color/light, walls on their way, ONE room per conversation), scene truth in the facts
limits list. Five exemplars: grounded answer + invitation; can't-see-that in voice;
mutation request → the mover line; off-domain deflection ("I'm here for the room");
cross-room question → single-room truth. Rhythm enforcement is a four-layer stack:
exemplars steer; `max_tokens` ≈ 250 backstops (generous — truncating the guest
mid-sentence is worse than a long beat); observe-only telemetry (token count,
invitation-ending heuristic, and the foreign-measurement detector: measurement-shaped
tokens must originate in the facts block ∪ the history window's USER messages —
echoing the user's numbers is legitimate; the guest re-using its own prior invention
still flags) writing a `flags` field + structured log, never blocking; and a
live-model voice eval suite asserting beat length, invitation ending, zero foreign
measurements, refusal shapes — run on PROMPT_VERSION bump OR GUEST_MODEL change
(model swaps are env-only and move voice more than prompt edits), documented
iOS-integration-posture style. The model call has ZERO tools — read-only is
architectural, not charter. `GUEST_MODEL` env-configured, default `claude-sonnet-5`;
every turn records the reproducibility triple (facts_version, prompt_version, model).

**Cost.** Exposure map: every pre-stream gate (auth, ownership, ready) runs before
any model call, so drive-by traffic — including free anon UIDs — costs zero; the
expensive path requires owning a READY scene. What this endpoint adds is unbounded
marginal cost per owned scene, so stage 1 ships bounds, not velocity limits: the
turn-taking reservation (`active_turn` lease set in the accept transaction with the
budget read, cleared on persist, **TTL 150 s — deliberately longer than the full
120 s request envelope**, because a lease expiring at 60 s while a legitimate turn
drains re-admits parallel generation through the mechanism that closed it; this repo
has already debugged lease-expiry-vs-live-holder, see 0011/0012); `409
turn_in_flight` as the honest turn-taking semantic (fork 3 initially accepted this
corner as a documented race; re-opened and shipped once budget-TOCTOU and parallel
burn priced it); message ≤ 2000 chars; N=20 window; `max_tokens` 250; 60 s model
wall-clock cap; and a daily per-conversation turn quota (~100/day, UTC boundary,
`GUEST_DAILY_TURNS`). Worst-case per-scene-daily spend is closed-form. **The
residual, explicitly:** K scenes per attacker is unbounded UPSTREAM via the unmetered
upload→perception path — gaps (a)/(b)'s pre-existing exposure, unchanged by this
feature; the Anthropic workspace monthly spend cap is the hard stop for both. Prompt
caching on from day one at both breakpoints (static; facts), with a third rolling
breakpoint on message history as a tunable. Budget refusals: `429 budget_exhausted`
body `{error, guest_line, resets_at}` — the guest_line is a server-authored fixed
line in voice, time-vague ("later," never "tomorrow") so voice never promises a
boundary the mechanism doesn't keep. Truncation appends nothing — the record stays
exactly what was said. Key in Secret Manager; runtime SA gets secretAccessor.

**Client + mock parity.** The seam is a normalized `GuestEvent` stream:
`sendMessage` is `Promise<AsyncIterable<GuestEvent>>` — it awaits response headers
and throws typed pre-stream errors (429/409/400/401) BEFORE returning the iterable;
the iterable covers only the stream phase. SSE parsing lives inside LiveApiClient;
MockApiClient yields the same events; components cannot tell transports apart (the
PositionedSplat trick, applied to conversation). The composer is a pure reducer —
the testable artifact — with states idle / submitting / streaming / confirming /
reoffer / rested / blocked: confirming refetches by client_msg_id across ≤150 s
(aligned to the lease); reoffer re-populates the retained text and requires a human
tap, NEVER auto-resend; rested renders the guest_line as speech and rests the
composer until resets_at ∪ rested_until (GET meta carries it so a reload can't wake
a resting composer); blocked (= turn_in_flight, second tab) shows a quiet non-voice
note and spaced refetches until the other tab's turn appears. Deltas accumulate
outside React state and flush on a ~200 ms batch timer — calm arrival and render
economy are one mechanism; sentence-boundary flushes under reduced motion; all
entrances ride the single SPRING; nothing in this surface is gold. The card carries
the current exchange; earlier exchanges collapse to stubs labeled with the user's own
truncated words, tap-to-expand. Template narration hands off: settledLine's copy
changes to a live invitation; the WaitRoom keeps DisabledComposer, whose copy remains
literally true. Conversation is an enhancement layer: any conversation GET failure
(403/404/network) degrades to the non-conversational settled layout — the room never
breaks. (The landing's demo room is local fixtures with no scene_id; it never touches
the API.) Mock: an accumulating in-memory conversation (starts empty — first-sight
reachable; resets on reload), canned beat+invitation replies grounded in the fixture
manifest (including a can't-see-that about the unplaced plant), and trigger phrases
`!error` / `!budget` / `!slow` / `!inflight` to walk every reducer state offline.

**Scope.** The ledger is DEFERRED — stage 1 cannot honor it: guest-authored pins
collide with zero-tools and no-structured-output; pin content collides with the
summarization rejection; stage-1 facts can't produce ledger-worthy findings (the
file's example pins are clearance and light — exactly what's unspeakable until
extents); evidence-attachment is R3F-gated. Trigger: extents and/or per-object
selection, designed in its own pass with these constraints inherited. The deferral
covers findings/pins only — the shipped inventory panel ("in this room") stays
as-is; no product copy adopts "put into words"/pin/keep vocabulary until the real
ledger ships. Also not shipping: wait-chat during processing (nothing to ground
pre-manifest; §3's "everything said here is remembered" promise is explicitly PARKED
— it needs memory-into-reveal machinery of its own); selection-as-asking (R3F gate;
the protocol accepts it later as a POST-body extension); all mutation (stage 2
entire, enforced by zero tools); chips; multimodal frames; cross-room conversation
(single-room scope is capability-level charter truth with its own exemplar);
conversation push notifications; pagination UI; admin tooling.

## Why

Stage 1 is the first feature that delivers the product's decision-support promise,
and the first money-per-call endpoint. Every choice above serves one of two masters:
the honesty charter made structural (facts-only world, numbers verbatim, zero tools,
no summaries, no fake affordances) or bounded cost made structural (pre-stream gates,
turn-taking lease, closed-form daily spend, caching by construction). Where the two
met — what the guest says at a budget, what a truncated reply looks like — voice won
the surface and the mechanism stayed honest underneath.

## What would change this decision

- Extents landing in the manifest re-opens: gap/clearance speech, ledger trigger
  half-met, facts_version bump.
- Board item 1's verification event clearing the SAM 3D conventions re-opens
  orientation-derived facts.
- Real usage showing the 20-turn window genuinely losing load-bearing context
  re-opens memory — via ledger pins-as-context, not summaries.
- Sharing/multi-user product decisions revisit per-scene+user scoping (schema
  already accommodates).
- Launch hardening layers gap (b)'s velocity limits over these bounds; nothing here
  substitutes for that.
- If the shield-to-completion disconnect pattern proves flaky on Cloud Run in
  practice, the recorded fallback is abort-on-disconnect with client re-offer — a
  worse transcript-durability story, adopted only on evidence.
