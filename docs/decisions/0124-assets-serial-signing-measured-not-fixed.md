# 0124 — the assets endpoint's serial signing is real, measured, and not the P0

**Date:** 2026-08-09
**Status:** Trigger fired — placed-only filter shipped 2026-08-10

> **Outcome (2026-08-10):** the first trigger fired (the compressed tier put
> the payload in the tens of MB), and the placed-only filter shipped. The
> consumer check this note demanded came back clean: the shell has signed
> nothing since 0069 (the handler builds `to_sign` from manifest objects
> only), `/viewer` fixtures never call `/assets` (staged from disk/GCS, and
> the staging tools filter `placed` before any URL lookup), and the web's
> `assembleScene` reads `asset_urls` only for objects it renders — unplaced
> ones become text-only inventory before the lookup matters. Both maps
> filter from the ONE uri set, so `asset_urls_compressed` can never carry a
> key without its PLY fallback. Live on the reference room: 22 signed → 10.
> The concurrency half was already done (ASSET_SIGN_CONCURRENCY=8, shipped
> with 0126); this closes the note's remaining half.

## Context

`GET /scenes/{id}/assets` signs **every** splat URI in the manifest — placed or
not — in a serial loop (`services/api-public/public_server.py:1300`). Each
`generate_signed_url` under `IamV4UrlSigner` is an IAM signBlob network round
trip. On the reference scenes, 12 of 22 signatures (`a7e073ae`) and 24 of 40
(`b667f891`) are for splats the client provably never fetches — `assembleScene`
builds a `PositionedSplat` only for placed objects.

The render-payload brief flagged this as "one real finding, adjacent and cheap",
and said explicitly: **measure it before fixing it — it may be 200 ms or it may
be 15 s.**

## What we tried

Measured from production Cloud Run request logs rather than by reasoning about
round-trip counts — 30 days of real `/assets` requests:

| scene | signed URIs | latency |
|---|---:|---:|
| `a71d125f` | ~20 | 0.92–1.20 s |
| `a7e073ae` | 22 | 1.46–2.19 s |
| `b667f891` | 40 | 2.19 s |
| `09684dde` | 20 | 1.24 s |

So: **0.9–2.6 s**, scaling with signed-URI count, exactly as the serial-loop
shape predicts. (The paired ~0.002 s entries in the same logs are the CORS
preflights, not signing.)

## What we chose

Left it alone. Recorded, not fixed.

## Why

It is 0.9–2.6 s of a 120–420 s wait — under 1%. Decision 0123 measured the
dominant term as network transfer of a 276–390 MB payload, and fixing a 1%
term while the 99% term is open is the wrong order of work. Shipping it now
would also mean touching api-public in the same window as a payload change,
for no user-visible gain.

The fix, when it is worth doing, is already shaped by precedent and should be
cheap: the identical serial-round-trip pattern in `_mint_all` was cured with a
bounded order-preserving pool (`UPLOAD_SESSION_MINT_CONCURRENCY`) — no note
records it, so the reasoning lives in that function's docstring in
`packages/api-core/thegoodguest_api_core/upload_session_repo.py`, with the
measurement that forced it (an 878-path manifest at ~80 s serial, past the iOS
client's 60 s timeout). Filtering to placed-only is a **separate**
and independently correct change — but it narrows the response contract, so
check what else consumes `asset_urls` first. Two consumers to clear before
narrowing: the shell's texture URIs join the same signing walk (0066), and
`/viewer` fixtures read manifests directly.

Doing both would take a 40-URI scene from ~2.2 s to roughly the cost of one
signature, and it is time-to-first-byte — the user waits through it before a
single splat starts.

## What would change this decision

- Once the payload lands in the tens of MB, 2.2 s stops being 1% and starts
  being a visible share of the wait. Fix it then; it is the natural companion
  to a compressed tier.
- If a room ever ships enough objects that signing crosses ~5 s, it becomes
  user-visible on its own and should not wait for the payload work.
- If `asset_urls` gains a consumer that needs unplaced entries, the
  placed-only filter is off the table and only the concurrency fix remains.
