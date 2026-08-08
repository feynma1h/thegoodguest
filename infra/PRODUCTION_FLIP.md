# Production hosting flip — making roomstudio.web.app public

The web app has only ever been deployed to the `preview` channel. This file is
the operator-run procedure for releasing the `live` channel, and the record of
which preconditions were verified (and when) so the flip is a decision rather
than an investigation.

`infra/RUNBOOK.md` is the Cloud Run deploy runbook and is unaffected by this —
no backend change is required to go live. **This is a one-line command guarded
by a judgement call, not a technical project.**

Everything under "Preconditions" was verified live on 2026-08-08 against
serving revision `api-public-00032-has` and preview channel release
2026-08-08 22:50:34. Re-check anything older than a few weeks.

---

## The command

There is deliberately no `npm run deploy:production` script — a public site
should take a deliberate keystroke, not a habit. Run from `web/`:

```bash
cd web && npm run build && npx firebase deploy --only hosting --project roomstudio
```

`firebase.json` has a single unnamed hosting target serving `out/`, so
`--only hosting` releases the `live` channel and nothing else. The build step
is not optional: `firebase deploy` uploads whatever is already in `out/`, and a
stale `out/` is how you ship last week's bundle to the public URL.

After it completes, `https://roomstudio.web.app` serves the app instead of
"Site Not Found". The `preview` channel is untouched and keeps its own URL.

---

## Preconditions — all VERIFIED, no action needed

Each of these would have broken the public site, and each is already correct.
They are listed so a failure after the flip can be diagnosed against a known
starting point.

| # | Precondition | Verified state |
|---|---|---|
| 1 | api-public CORS allows the production origin | `https://roomstudio.web.app` echoes ACAO on a real preflight; a disallowed origin gets 400. Both production domains are in `CORS_ALLOWED_ORIGINS` in `infra/api-public.env.yaml` AND on the serving revision — no drift. |
| 2 | Outputs-bucket CORS allows it | `gs://roomstudio-perception-outputs` CORS lists `roomstudio.web.app` (with `roomstudio.firebaseapp.com`, the preview channel, and localhost) for GET/HEAD. This is the gate that made splats fail to render in decision 0102 — it is already correct for production. |
| 3 | Firebase API key referrer allowlist | The restricted browser key permits `https://roomstudio.web.app/*`. Note the shape trap from decision 0101: Google's referrer wildcards replace a whole subdomain label, so this had to be an exact entry. |
| 4 | Firebase Auth authorized domains | `roomstudio.web.app` is authorized, so the sign-in popup handler resolves. |
| 5 | CSP | `web/firebase.json` serves one headers block to every channel, and it is byte-for-byte the block decision 0102 proved a real 34 MB splat through (`wasm-unsafe-eval`, `worker-src blob:`, `connect-src` with the api + storage + `data:`). Enforcement re-confirmed on the deployed origin: off-origin `connect-src`/`img-src` attempts fire real violations. |
| 6 | Nothing private is served | `hero/piece.json`, `hero/*.ply` and `dev-fixtures/**` are in the hosting `ignore` list and return 404 on the deployed origin — confirmed by request, not by reading config. This lock is load-bearing: `next build` copies `public/` into `out/` **gitignore and all**, so a 44 MB splat of a real room is otherwise one deploy from a public URL. Re-confirm it after the flip. |
| 7 | Abuse surface | The board-4 gate for "first non-developer user" has shipped: per-UID daily capture ceiling (12) and mint quota (50), transactional bundle ownership, semantic manifest validation, scene TTLs. Live-probed on the serving revision. |

## Preconditions that are NOT technical — read before running

- **Terms §9–§11 have not been read by an Indian lawyer.** They are specific
  rather than boilerplate, and the §11 liability cap can be void against a
  consumer under Consumer Protection Act 2019 §2(46). The service is free, so
  the cap's first limb ("the greater of what you paid…") is always zero and the
  clause is doing all the work. Publishing the site publishes the Terms.
- **Sign-in on production is unproven end to end.** Gate B was passed on the
  preview channel with a real Google account (decision 0094). The production
  origin satisfies every precondition above, but no one has completed a sign-in
  on `roomstudio.web.app` itself. Expect to do that as step 1 of the post-flip
  check, in an ordinary browser — automation panes block the popup.

---

## Post-flip verification

Run against `https://roomstudio.web.app`. The first three are cheap and catch
the failure modes this project has actually hit.

```bash
P=https://roomstudio.web.app
curl -s -o /dev/null -w "hero   %{http_code} %{size_download}\n" $P/hero/room.json   # 200, 3557
for f in /hero/piece.json /hero/piece.ply /dev-fixtures/x; do
  curl -s -o /dev/null -w "lock   %{http_code}  $f\n" "$P$f"; done                   # all 404
curl -s -D - -o /dev/null $P/ | grep -i content-security-policy                      # wasm-unsafe-eval present
```

Then, in an ordinary browser (not an automation pane):

1. Sign in with Google. Expect the existing account, not a new one — decision
   0094's never-create guard means a brand-new identity here is a **failure**,
   not a first login.
2. Open a real room and confirm the splats render, with a clean console and
   zero `securitypolicyviolation` events. This is the check that would catch a
   regression of the 0102 chain, and it is the one that cannot be faked by a
   server-side 200: CORS is browser-only, and `curl` sends no `Origin`.
3. Confirm the reveal plays (decision 0097) — this is also the first chance to
   judge its pacing on a real machine, which the throttled automation browser
   cannot show.

## Rollback

Firebase Hosting keeps every release. To revert immediately:

```bash
cd web && npx firebase hosting:rollback --project roomstudio
```

There is no backend state to unwind — going live changes no data, mints no
credential, and alters no Cloud Run revision. The blast radius is the public
URL and whoever finds it.
