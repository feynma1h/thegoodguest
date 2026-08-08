# 0102 — The deployed room-render blocker was a chain of three, not one

**Date:** 2026-08-08
**Status:** Decided
**Relates to:** 0053 (Spark as the splat renderer), 0054 (signed asset URLs),
0085 (the consolidated walk that found the first link), 0094 (Gate B)

## Context

The consolidated walk (0085) found that the deployed web app rendered zero
splats and traced it to `connect-src`: Spark fetches its WASM from a `data:`
URI, and that fetch is governed by `connect-src`. Commit `81431cf` added
`data:` and recorded "deploy + on-origin verification still owed."

Verification found the fix was **necessary but not sufficient**. There were
three independent gates between the deployed page and a rendered room, stacked
so that each one hid the next. Fixing only the first would have produced
another walk with the same symptom and no new information.

## What we found

Measured on the preview channel with a direct probe (minimal valid WASM module,
`securitypolicyviolation` listener attached), then re-measured after each fix.

**Gate 1 — `connect-src` blocks the WASM fetch.** Real, and `81431cf` fixes it.
After the fix the probe fetched the data: URI (8 bytes), and the network log
shows Spark's actual 217 KB base64 WASM at `200 OK`.

**Gate 2 — `script-src` blocks WASM *compilation*.** Separate from the fetch and
invisible until the fetch succeeded:

```
CompileError: WebAssembly.instantiate(): Compiling or instantiating WebAssembly
module violates the following Content Security policy directive because
'unsafe-eval' is not an allowed source of script in the following Content
Security Policy directive: "script-src 'self' 'unsafe-inline' https://apis.google.com"
```

CSP3 gates WebAssembly compilation on `script-src`, needing `'wasm-unsafe-eval'`
(or the much broader `'unsafe-eval'`). The policy had neither.

**Gate 3 — the outputs bucket had no CORS configuration at all.** With both CSP
gates open, every splat still died before a byte arrived:

```
Access to fetch at 'https://storage.googleapis.com/roomstudio-perception-outputs/…'
from origin 'https://roomstudio--preview-cydkerk6.web.app' has been blocked by
CORS policy: No 'Access-Control-Allow-Origin' header is present
```

Spark loads splats in a worker, so this surfaced in the console only as
`Worker error: TypeError: Failed to fetch` — a message that names neither CORS
nor the asset.

## What we chose

1. Keep `data:` in `connect-src` (`81431cf`).
2. Add `'wasm-unsafe-eval'` to `script-src` — **not** `'unsafe-eval'`.
3. Add a CORS policy to `gs://roomstudio-perception-outputs`, as a new
   idempotent section (6) of `infra/eventarc_setup.sh` with the reasoning
   inline, following the house pattern that the deploy script IS the
   documentation.

## Why

**`'wasm-unsafe-eval'` over `'unsafe-eval'`.** It permits WebAssembly
compilation and nothing else. Verified on the deployed origin after the change:
WASM instantiates, and `eval("1+1")` still throws `EvalError` with a
`script-src` violation logged. The renderer is a WebGL2 3DGS engine; WASM is not
optional for it, so this is granting the capability the product actually needs
rather than widening the policy to cover a symptom.

**Bucket CORS is not an access grant.** This is the part worth being precise
about, because "open CORS on the bucket holding users' rooms" sounds alarming.
CORS only tells a browser it may hand an *already-authorized* response to a
listed origin. Verified all three ways after applying it:

| probe | result |
| --- | --- |
| signed GET, listed origin | `206` + `access-control-allow-origin` echoed |
| **unsigned** GET, listed origin | **`403`** — objects remain private |
| signed GET, unlisted origin | **no ACAO header** — browser blocks |

The origin list deliberately mirrors api-public's `CORS_ALLOWED_ORIGINS`: one
trusted-origin set, two enforcement points (the API for JSON, the bucket for
assets). They must be edited together — otherwise a room loads its manifest and
then renders nothing, which is exactly the failure this note is about.

**Why this survived every previous check.** Two different blind spots, and both
are worth naming because they will recur:

- `next dev` does not apply hosting headers, so no amount of local verification
  can see a CSP defect. Already recorded in `81431cf`.
- **CORS is enforced by browsers only.** Every prior verification of the asset
  path — including Gate B's "signed URL fetches 34 MB at 200" (0094) — used
  curl or a server-side client. Those send no `Origin` and check for no ACAO,
  so they pass with 100% reliability against a bucket that no browser can read.
  A server-side 200 is not evidence about a browser.

## Verification

The whole chain, on the deployed preview origin, under its real headers:
Spark's 217 KB WASM fetched and compiled → blob worker spawned → a **real
34,043,936-byte splat** from captured scene `a7e073ae` (`00_bed.ply`) fetched
cross-origin over a V4-signed URL → decoded → rendered as Gaussians.
Zero `securitypolicyviolation` events; no errors in a clean-tab console.

The signed URL was minted by running the *same call* as api-public's
`IamV4UrlSigner.sign` (`generate_signed_url(version="v4", …)` with
`service_account_email` + `access_token`), which emits the path-style
`storage.googleapis.com/{bucket}/{path}` form — so the URL shape proven here is
the shape the product mints. Note the `gcloud storage sign-url` CLI defaults to
the *virtual-hosted* form (`{bucket}.storage.googleapis.com`), which
`connect-src https://storage.googleapis.com` would **not** match; if signing
ever moves to the CLI or to `api_access_endpoint`, CSP breaks again.

## What would change this decision

- If Spark ever ships its WASM as a separate `.wasm` file rather than an inline
  `data:` URI, `data:` can leave `connect-src` — but `'wasm-unsafe-eval'` must
  stay regardless, since it governs compilation, not transport.
- If a browser we care about lacks `'wasm-unsafe-eval'` (pre-16.4 Safari is the
  realistic case, and it did not gate WASM on CSP at all), revisit — but do not
  reach for `'unsafe-eval'` without a measured need.
- Adding a hosting origin (a per-PR preview channel, a custom domain) requires
  editing **both** `CORS_ALLOWED_ORIGINS` and section (6)'s origin list.
