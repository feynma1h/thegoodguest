<!--
docs/briefs/hosting-preview-brief.md — implementation brief for board item
6(a): Firebase Hosting stood up, preview channels only.

Committed 2026-07-22 so the session prompt survives outside transcripts.
Consumer: whichever Code session runs 6(a) — hand the brief body over as the
kickoff prompt. NOT gated on Apple Developer enrollment: only the hosted
sign-in E2E leg needs the enrolled team, and that is Gate B's job (see the
0051 enrollment runbook bullet in CLAUDE.md).

Delete this file when 6(a) ships — CLAUDE.md becomes the durable record.
-->

# Build brief — Firebase Hosting, preview channels only (board 6a)

```
Read CLAUDE.md and .claude/WORKFLOW.md first.

Task:        Board item 6(a) — Firebase Hosting stood up, PREVIEW CHANNELS
             ONLY. Hard rule: do NOT deploy to the production channel
             (roomstudio.web.app) — a public site is the "first
             non-developer user" trigger for the abuse-surface gaps (board
             item 4), which close in launch hardening first.

Scope:       firebase CLI setup (the operator runs the interactive login);
             proper web-app Firebase registration replacing the
             roomstudio-smoke-test appId (env plumbing per
             web/.env.example); authorized domains — INCLUDING the preview
             channel's generated *.web.app subdomain, or the sign-in popup
             will fail on preview URLs; the frame-src CSP precondition
             recorded in the 0051 enrollment bullet (web/firebase.json
             lacks frame-src for roomstudio.firebaseapp.com, which the
             Firebase popup flow's hidden iframe needs); then a
             preview-channel deploy of a live-mode build.

Verify by:   The preview URL loads with a clean console (CSP violations =
             fail); signed-out invitations render on /rooms, /room, /new
             and the account menu (0051's web flow); a sign-in attempt
             reaches the Apple provider gate — full E2E completes only
             post-enrollment with Gate B (if enrollment has landed, run
             Gate B on the preview URL and record it); CORS for the
             hosting domains is already live server-side (decision 0054's
             env yaml).

Convention:  See CLAUDE.md. Housekeeping closes the stale "0051 remains
             unbuilt" clause in the scaffolded-not-deployed bullet while
             in there, and records the preview-channel state. No
             production channel, no merge, no push — report the branch
             ready.
```
