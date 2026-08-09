# Workflow: Claude Code, Claude Chat, and how to brief each one

This file is operational, not strategic. Read it once; refer back when you're stuck on "where does this question go?"

## The two tools

**Claude Code** — runs in this repo on your machine. Reads `CLAUDE.md` on every session. Edits files in place. Runs code in your actual environment. Use for executing well-defined tasks.

**Claude Chat** — runs in a browser. Doesn't see your repo unless you upload. Better at open-ended back-and-forth. Use for decisions, not tasks.

The split isn't about model capability. It's about interaction shape. Code wants to act; Chat is comfortable sitting with ambiguity. Pick the one whose default behavior matches what you need.

## Decision rubric

Ask yourself: "Am I asking *what to do* or *how to do something specific*?"

| You're asking… | Tool | Example |
|---|---|---|
| What to build next | Chat | "Bundle ingester is done — iOS or _compose_scene rewrite first?" |
| Whether a design is sound | Chat | "Pos+quat vs matrix for Pose. Which is better?" |
| Whether a path is worth abandoning | Chat | "VGGT scale-calibration keeps failing; do I keep iterating or wait for π³?" |
| To build a thing whose shape is settled | Code | "Build the FastAPI ingester route per the spec in CLAUDE.md. Validate against outputs/test_bundle/bundle.pb." |
| To debug an error you're looking at | Code | "perception-obj returns 500 on this bundle; here's the stack trace, find it." |
| To refactor without changing behavior | Code | "Move the GCS path joining logic from inspect_bundle.py into pose_math.py? No — into a new io_paths.py module." |
| To explain code you don't understand | Either | Code is better if you want it to walk you through running it; Chat is better if you want a high-level explanation. |

When in doubt: if you'd start your message with "should I…" or "is it better to…" — that's Chat. If you'd start with "do this:" — that's Code.

## Model choice

In Claude Code, set **Sonnet 4.6** as the default. Switch to **Opus 4.7** only when reasoning depth genuinely matters — coordinate-frame conversions, perception-pipeline architecture, anything where a wrong answer propagates through a lot of code.

In Claude Chat, **Opus 4.7** is fine to default to. The work you do in Chat is the kind Opus is built for. You'll burn more tokens than necessary if you also use Opus in Code for things Sonnet handles fine.

## How to brief Claude Code

A good brief is specific about scope, contract, and verification. Use this template:

```
Task:        <one sentence>
Constraints: <what to touch and what NOT to touch>
Contract:    <which proto/schema/interface defines correctness>
Verify by:   <the command that proves it works>
Convention:  <relevant CLAUDE.md sections; usually "see CLAUDE.md">
```

### Good example

```
Task:        Build the bundle ingester FastAPI route.
Constraints: New code in services/api-internal/ only. Don't modify
             perception-obj or perception-geom. Don't touch packages/schemas.
Contract:    Accepts a bundle by GCS URI, parses with
             roomstudio_schemas.CaptureBundle, validates schema_version,
             quaternion norms (< 1e-3), and tier-vs-depth consistency.
             Returns 400 on validation failure with a structured error.
Verify by:   Running the route locally against outputs/test_bundle/bundle.pb
             (uploaded to a test GCS bucket); should return 200 + a bundle
             summary identical to `tools/inspect_bundle.py`.
Convention:  See CLAUDE.md. Frame is ARKit-native; don't transform.
```

### Bad example

```
make the ingester
```

Why bad: no scope, no contract, no verification. Code will sprawl — it'll touch six files, redesign the orchestrator, invent fields the proto doesn't have. You'll spend more time reviewing the diff than writing a proper brief would have taken.

### When to NOT use the template

If the task is small enough ("rename `_pose_position` to `pose_position`"), don't ceremonialize it. Just ask. The template is for tasks big enough that drift is a real risk.

## How to brief Claude Chat

Chat doesn't have a template because the value isn't in the structure of your prompt — it's in giving Chat enough context to push back usefully.

Three things to include:

1. **The state.** Upload `CLAUDE.md`. Always. Even if it feels redundant.
2. **The decision you're trying to make.** Frame it as a question, not a request for output.
3. **What you've already considered.** If you've narrowed it down to two paths, say so. If you haven't, say that too.

### Good example

> "I uploaded CLAUDE.md. Three options live for what's next. I'm leaning toward the ingester (option 2) because it unblocks option 3, but I'm worried that without the iOS side existing, I'll design the ingester for what I *think* an ARKit bundle looks like and get it wrong. Talk me through whether to do option 1 first to derisk the contract, or commit to option 2 and trust the synthetic bundle."

This gives Chat enough context to either confirm or push back, and to point at the specific risk you're worried about.

### Bad example

> "What should I do next?"

Chat will give you a generic answer that's not wrong but isn't useful. The good version of this question lives in your head — extract it before opening the chat.

## The loop

```
1. Chat   — decide what to do                 (when there's a fork)
2. Chat   — summarize the decision            (prompt A below)
3. Code   — apply + execute                   (prompt B below)
4. Code   — auto-runs session-end housekeeping (per CLAUDE.md)
5. You    — approve diffs
6. Goto 1 (next fork) or Goto 3 (next step obvious)
```

Steps 4 and 5 used to be manual — "remember to update CLAUDE.md, remember to consider a decision note." They aren't anymore; `CLAUDE.md`'s session-end housekeeping section instructs Code to self-prompt. You just approve diffs.

The one seam where manual work remains: Claude Chat can't write to your repo. So when a Chat session changes the project's state, you carry it over to Code with prompt B. That's it.

## Standard prompts

These are the prompts that move work between Chat, Code, and the docs. Copy them; fill in the blanks. After a few sessions you'll have them memorized — they're training wheels, not laws.

### Prompt A — end of any Chat session that decided something

> Summarize this conversation for the project's CLAUDE.md and `docs/decisions/`. Give me three things:
>
> 1. **CLAUDE.md delta** — exactly what should change in "What works," "What does NOT work," and "Next on the board." Just the new text, not the whole sections.
> 2. **Decision note?** — yes or no. If yes, draft it using the template structure (Context, What we tried, What we chose, Why, What would change this decision). If no, say "skip — routine."
> 3. **The brief for Code** — a paragraph I can paste into Claude Code to act on this decision. Include scope, contract, and verification.

Run it even when you think nothing changed — Chat will say "nothing material" and you'll have confirmation. Push back if the output is bloated: "shorter — I'm pasting this into Code."

### Prompt B — start of the next Code session, after a Chat decision

> Read CLAUDE.md and `.claude/WORKFLOW.md`. Then apply the following decision from a strategy session in Claude Chat:
>
> <paste prompt A's output here>
>
> Update CLAUDE.md and (if applicable) write the decision note first. Show me the diffs before writing. Then act on the brief.

Two phases in one prompt: docs update first, then the actual work. Code splits them naturally.

### Prompt C — end of Code session (fallback)

> Before we wrap: per CLAUDE.md's session-end housekeeping section, propose updates to "What works," "What does NOT work," and "Next on the board," and identify any decision-note candidates. Show diffs.

You shouldn't need C — Code reads CLAUDE.md at session start and auto-prompts at the end. Use C as a fallback when Code somehow skips it (e.g. session was interrupted, or the standing instruction hasn't fired yet in the first few sessions).

### Prompt D — start of a fresh Code session (any time)

> Read CLAUDE.md and `.claude/WORKFLOW.md`. Tell me what you understand the current state of the project to be, and what's next on the board. I'll correct anything stale before we start.

Cheap sanity check. Forces Code to load context and surface any drift between the docs and reality before it starts changing things. Use this when picking up after a long break, or after a Chat session that may have invalidated parts of CLAUDE.md.

## Cloud Build and deploy tooling

Cloud Build jobs run remotely on GCP. The local `./infra/deploy_*.sh` scripts submit the
build then stream logs — if the local process is killed (Ctrl-C, shell exit, task killed),
the Cloud Build job **continues running remotely**.

**Polling rule:** Never rely on a scheduled wakeup or task notification to signal Cloud
Build completion. The local task ID becomes stale once the local script dies; the wakeup
mechanism fires on wall-clock time, not build completion. Instead:

1. Note the build ID from submission output
   (`Created [https://cloudbuild.googleapis.com/...builds/<BUILD_ID>]`).
2. Poll directly at 2–3 minute intervals:
   ```
   gcloud builds describe <BUILD_ID> --project=roomstudio --region=asia-southeast1 \
     --format='value(status,finishTime)'
   ```
   Loop until `status` is `SUCCESS`, `FAILURE`, or `CANCELLED`.
3. If the build succeeded but the local deploy step never ran, trigger it manually:
   ```
   gcloud run deploy <service> \
     --image=$(gcloud builds describe <BUILD_ID> --project=roomstudio \
               --region=asia-southeast1 --format='value(images)') \
     --project=roomstudio --region=asia-southeast1
   ```

This pattern failed twice in the same session before the rule was written. Don't retry it.

## Things to actively NOT do

- **Don't run the same task in both tools.** If Code is building X, don't also ask Chat to design X. You'll get two designs and have to reconcile them.
- **Don't use Chat for production code.** Even though it can — the paste-run-paste-back loop is bad without repo context.
- **Don't use Code for architectural decisions.** It'll make them, and fast, before you've thought.
- **Don't skip prompt A** because "the session was small." A 30-second summary now beats reconstructing the decision from chat history in three weeks.
- **Don't write a decision note for every session.** Most sessions are routine. Save the notes for things worth not re-litigating.
