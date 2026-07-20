<!--
docs/briefs/0058-build-brief.md — implementation brief for conversation stage 1.

Produced by the 2026-07-21 design session that authored decision 0058; committed
here so the brief survives the sessions that carried it. Consumer: the Code
session that implements conversation stage 1 — hand it over via WORKFLOW.md's
Prompt B, with one adjustment: the docs half of Prompt B is ALREADY DONE
(decision 0058 and its CLAUDE.md delta landed on main in commit 5c9dad7), so
the implementing session skips "write the decision note first" and goes
straight to the build. The brief body below is preserved verbatim from the
design session, including its now-satisfied "write it to docs/decisions/
first" convention line.

Delete this file when stage 1 ships — the durable record is decision 0058.
-->

# Build brief — conversation stage 1 (decision 0058)

```
Task:        Implement conversation stage 1 per decision 0058: the streaming
             conversation endpoint + GET on api-public (SceneFacts layer, guest
             prompt module, conversation repo, both routes), the web client
             (GuestEvent seam, composer reducer, card/stub transcript, mock
             parity), and the coupled infra changes. Suggested commit split:
             (1) scene_facts + guest_prompt with tests; (2) conversation repo +
             routes with tests; (3) web; (4) infra.

Constraints: Server code in services/api-public/ only (new modules:
             scene_facts.py, guest_prompt.py, conversation_repo.py; routes wired
             into public_server.py). Do NOT touch services/api-internal,
             services/perception-*, packages/schemas, ios/. packages/api-core
             stays untouched (service-local until a second consumer). Web: changes
             in web/src/lib/api/ + conversation components under web/src/;
             SplatViewer.tsx untouched (0053); no Firestore client SDK; no CSP
             change (Anthropic is called server-side; connect-src already covers
             api-public); static-export build must stay green. No Firestore
             security-rules changes (server-only writes). The four existing routes
             keep their sync-def posture; the conversation route is the service's
             FIRST async route — every blocking call (history load, persist,
             budget reads) via asyncio.to_thread or before the generator starts;
             record the divergence in a code comment the way the sync choice was.
             Copy guards: settledLine becomes a live invitation; WaitRoom keeps
             DisabledComposer and its copy unchanged; NO pin/keep/"put into words"
             vocabulary anywhere; the inventory panel keeps its "in this room"
             titling; nothing in the conversation surface is gold. Conversation is
             an enhancement layer: any conversation GET failure (403/404/network)
             degrades to the non-conversational settled layout — the room page
             never breaks.

Contract:    POST /scenes/{scene_id}/conversation/messages, body {text ≤2000
             chars, client_msg_id (UUID)}. Pre-stream JSON errors per the existing
             {error, detail} contract: 400 invalid_scene_id / message_too_long,
             401, 403, 404, 409 scene_not_ready, 409 turn_in_flight,
             429 budget_exhausted with body {error, guest_line, resets_at} (fixed
             guest_line, time-vague wording). Success: 200 text/event-stream with
             events delta {text} / done {turn} / error {code}, ": ping" comments
             during model silence (~15 s); the vocabulary is OURS — a transform of
             the model stream, never a passthrough. done carries the client
             projection _turn_to_client_dict(turn) = {turn_index, client_msg_id,
             user_text, assistant_text, created_at}; internal fields (usage,
             model, prompt_version, facts_version) never on the wire.
             GET /scenes/{scene_id}/conversation → {conversation: {scene_id,
             turn_count, rested_until|null}, turns: [projection…] (last ≤50,
             ordered), cursor before=turn_index (client v1 may ignore)};
             200-empty when none; 409 scene_not_ready until ready (both verbs).
             Firestore: conversations/{scene_id}__{user_id} {scene_id, user_id,
             created_at, updated_at, turn_count, cumulative usage,
             active_turn {client_msg_id, started_at} | null, day, turns_today};
             turns/{six-digit zero-padded index} {turn_index, client_msg_id,
             user_text, assistant_text, created_at, completed_at, facts_version,
             prompt_version, model, usage {input_tokens, output_tokens},
             finish_reason, flags[]}. Accept transaction: quota check
             (turns_today < GUEST_DAILY_TURNS, UTC day roll) + client_msg_id
             dedupe (match in recent turns → replay stored turn, no regeneration)
             + reservation (set active_turn if absent/expired; expiry 150 s —
             MUST exceed the full 120 s request envelope, see 0058 + 0011/0012;
             else 409 turn_in_flight). Persist transaction: create turn doc,
             increment counters + usage, clear active_turn. Turns exist only
             completed. On client disconnect: shield — drain the model stream to
             completion, persist, exit, all inside the request; model call
             wall-clock cap 60 s.
             scene_facts.py: derive_scene_facts(manifest) → SceneFacts
             {facts_version:int, inventory+confidence, distances (server-formatted
             framed strings, typed comparative vs absolute; no gap/clearance
             phrasing), vertical relations (relative only), provenance, limits
             list}. Pure + deterministic; in-memory cache keyed
             (scene_id, facts_version); NO orientation-derived facts.
             guest_prompt.py: PROMPT_VERSION int; static charter (identity,
             honesty rules — quantities verbatim-only from facts, two-level
             can't-see-that, the mover line, single-room truth); FIVE exemplars
             (grounded+invitation / can't-see-that / mutation→mover / off-domain
             "I'm here for the room" / cross-room→single-room);
             build_system_prompt(facts). Pinned-hash test on (PROMPT_VERSION,
             sha256(static charter)). Assembly order: static → facts → messages;
             user text never in the system prompt; ZERO tools on the model call;
             cache_control breakpoints after static and after facts (consider a
             third rolling breakpoint on history — tunable, not required).
             Post-stream telemetry (never blocks): token count, invitation-ending
             heuristic, foreign-measurement detector (allowlist = facts-block
             strings ∪ measurement tokens from history-window USER messages;
             assistant self-quotes still flag) → flags field + structured log.
             Voice eval suite: live-model pytest whose docstring documents BOTH
             triggers (PROMPT_VERSION bump OR GUEST_MODEL change),
             iOS-integration fail-closed posture.
             Env/infra (ships WITH this deploy): GUEST_MODEL (default
             claude-sonnet-5), GUEST_DAILY_TURNS (default 100), ANTHROPIC_API_KEY
             via Secret Manager; IAM prerequisite: api-public runtime SA needs
             roles/secretmanager.secretAccessor on the key secret;
             deploy_api_public.sh --timeout 30 → 120. Operator step (not code):
             the key's Anthropic workspace gets a monthly spend cap.
             Web: ApiClient/MockApiClient grow getConversation +
             sendMessage: Promise<AsyncIterable<GuestEvent>> (awaits headers,
             throws typed pre-stream errors BEFORE returning the iterable; SSE
             parsing inside LiveApiClient only). Composer reducer (pure,
             vitest-covered): idle / submitting / streaming / confirming (refetch
             by client_msg_id, ≤150 s window) / reoffer (retained text, human tap
             only, NEVER auto-resend) / rested (guest_line as speech; composer
             rests until resets_at ∪ rested_until) / blocked (turn_in_flight:
             quiet non-voice note, spaced refetches). Deltas accumulate outside
             React state, ~200 ms batch flush (sentence-boundary under reduced
             motion); SPRING for all entrances; no truncation note. Card = current
             exchange; stubs = user's own words truncated, tap-to-expand. Mock:
             accumulating in-memory conversation (starts empty, resets on
             reload), fixture-grounded beat+invitation replies incl. a
             can't-see-that about the unplaced plant, trigger phrases
             !error / !budget / !slow / !inflight.

Verify by:   Python: full suite green from repo root, including — scene_facts
             unit tests over fixture manifests (placed/unplaced/empty);
             conversation repo tests (transaction semantics, dedupe-replay,
             reservation expiry vs live holder, UTC quota roll); TestClient tests
             for BOTH routes per decision 0010 (streaming happy path, every
             pre-stream error incl. 429 body shape with resets_at, in-stream
             error event, 409 turn_in_flight, exact projection fields);
             guest_prompt pinned-hash test. Web: vitest (reducer transitions
             incl. confirming→reoffer timing and stub collapse), lint,
             static-export build. Live-local e2e (uvicorn api-public + real
             ANTHROPIC_API_KEY + web live-local): a happy turn streams and
             persists; kill the browser mid-stream → refetch confirms the turn
             by client_msg_id; second-tab 409 path; quota=1 env → real 429/rested
             path. Deployed (post-deploy): kill the client mid-stream against
             the deployed revision and confirm the completed turn lands in
             Firestore (the shield proof); the SECOND turn's persisted usage
             shows nonzero cache-read tokens (caching observed, not assumed);
             run the voice eval suite once at the initial PROMPT_VERSION with
             the default GUEST_MODEL.

Convention:  See CLAUDE.md and decision 0058 (paste-delivered with this brief —
             write it to docs/decisions/ first, per Prompt B). Tests pin
             invariants, not implementation. Every FastAPI route gets TestClient
             tests (0010). Facts speak meters, ARKit frame. Session-end
             housekeeping per CLAUDE.md; the CLAUDE.md delta accompanying this
             brief lands in its own docs commit.
```
