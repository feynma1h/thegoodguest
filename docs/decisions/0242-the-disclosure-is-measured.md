# 0242 — A privacy disclosure is measured, not described

**Date:** 2026-08-24
**Status:** Decided

## Context

App Store privacy nutrition labels were the one piece of submission collateral
blocked on nothing — they describe what the system already does. The obvious way
to fill them in is to read the Privacy Policy, which this repo wrote from the
code in the first place and annotated with the trace beside every claim, and
transcribe it into Apple's categories.

That would have shipped three wrong answers and one that could not have been
answered at all.

## What we tried

Every answer in `docs/product/privacy-nutrition-labels.md` was traced twice:
once to the code, and once to the running system. Where the two disagreed, the
running system won. Four disagreements, in descending order of consequence:

- **Upload bookkeeping is not retained 7 days.** Privacy Policy §6,
  `infra/eventarc_setup.sh:253`, `account_deletion.py:40` and CLAUDE.md's
  retention line all say 7 days. Firestore TTL has no duration parameter — it
  deletes when the named field's *value* is past — and the policy is on
  `created_at`, written as `datetime.now(tz=timezone.utc)`
  (`upload_session_repo.py:337`, `:482`). The record is expired the instant it
  is written. `upload_session_repo.py:8-10` is the one place that says so
  ("Firestore sweeps promptly once the timestamp is past"). Live corroboration:
  `upload_sessions` held 2 documents, both ~30 minutes old, none older than a
  day.

  **The setup script's own section 4 states the rule and warns against exactly
  this** — "Do NOT point a TTL policy at created_at here: Firestore deletes when
  the named field's value is past, which for created_at means immediately" —
  while section 3 of the same file does it. The 7 days is a true fact about GCS
  *resumable session URIs* that was carried onto a different mechanism.

- **Server request logs were undisclosed entirely.** Cloud Run records the
  client IP, user agent and request URL for every call, retained 30 days in the
  `_Default` log bucket — verified by reading one back. That is longer than the
  request it services, so under Apple's definition it is collected data; it is
  linked, because the same request carried a Firebase JWT; and `DELETE /account`
  does not reach it. Privacy Policy §6 lists six retention facts and this is not
  among them; §7 is titled "Deleting everything".

- **Firestore's region was an open question and is not.** Privacy Policy
  operator review note 3 has said since 2026-08-08 that §4 states the compute
  and blob region and that the Firestore database's location should be checked
  and stated if it differs. It is `asia-southeast1`, the same region. One API
  call closed a note that had been open for sixteen days.

- **The material-inference call had to be verified armed, not assumed.** It
  degrades silently to `family = None` with no API key
  (`shell_material.py:195-198`), by design — the fallback is load-bearing and
  test-pinned. So the deploy script setting `SHELL_MATERIAL_MODEL` proves
  nothing about whether pictures of homes are actually leaving. The serving
  revision does: `perception-obj-00062-hum` at 100% traffic carries the model
  env *and* the `anthropic-api-key` secret mount.

## What we chose

The labels are derived from the live system, and the document records the live
verification beside each answer with the date it was taken. `infra/` scripts are
treated as **statements of intent**, not as evidence of configuration — a script
can be edited, partially applied, or wrong about its own effect, and section 3
of `eventarc_setup.sh` is all three.

Two judgment calls were made explicitly rather than left implicit, because both
decide more than one label row and both would otherwise be silently re-decided:

- **Server logs do not become a Coarse Location row.** Apple's Coarse Location
  is data that *describes the location of a user or device*; nothing in this
  system geolocates an IP or behaves differently based on one. The honest
  response is to disclose server logs in the Privacy Policy and to state that
  account deletion does not reach them — fixing the disclosure, not decorating
  the label. A conservative operator may instead fold it into the Device ID row
  already declared for another reason, which costs nothing; what is not
  available is leaving the policy silent either way.

- **The conversation surface is disclosed even though it is web-only today.**
  Apple's questionnaire covers the app, and strictly the iOS binary collects no
  conversation text. It is disclosed anyway: the label is read by someone
  deciding what happens to their data under this account, the app is the only
  on-ramp to that account, and under-disclosing now and amending later is the
  worse of the two failure modes.

## Why

**A privacy policy derived from code is still a description of code, and code
does not tell you what a TTL policy actually swept.** This repo's Privacy Policy
is unusually careful — every claim carries the trace beside it, and that
discipline is what made three of these findings cheap to locate. It still
carried a retention figure wrong by a factor of seven, because the trace pointed
at a script that says one thing and a mechanism that does another. No amount of
care in the prose reaches that; only asking the running system does.

The direction of the TTL error is the reason it survived: data is deleted
*sooner* than users were promised. Errors in the safe direction produce no
symptom, no complaint and no bug report, so nothing surfaces them except
someone going to look. A disclosure obligation is the rare occasion when
somebody does.

The two judgment calls are written down for the same reason the numbers are:
whoever transcribes this into App Store Connect, or amends it in a year, will
face both questions again, and a filing that disagrees with the previous filing
for unrecorded reasons is worse than either answer.

## What would change this decision

- **The four Privacy Policy corrections landing** (findings F1, F3, F4, F5 in
  the labels document) makes the policy and the labels agree again, at which
  point the policy is once more a usable starting point — but the live checks in
  §10 of that document still stand, because what made them necessary was the
  gap between config and behaviour, not the state of the prose.
- **Shortening the `_Default` log bucket retention** would make the server-log
  question smaller than the 90-day failed-scene retention already published, and
  might retire §7 of the labels document entirely.
- **A conversation surface shipping on iOS** converts the second judgment call
  from a conservative choice into a required disclosure, and the note beside it
  can go.
- **Manifest provenance on scenes** (0221's trigger, wanted for the calling
  card's eligibility gate) would also let a disclosure state which rooms were
  processed with person suppression armed, rather than the current honest
  hedge in Privacy Policy §8 that older rooms may carry measurements taken from
  a person.
