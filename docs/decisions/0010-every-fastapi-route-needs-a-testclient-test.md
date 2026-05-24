# 0010 — Every FastAPI route needs a TestClient test, not just a handler test

**Date:** 2026-05-24
**Status:** Decided

## Context

Every route in `perception-obj` had thorough handler-level tests
(`test_process_receiver.py` for `/process`, etc.). All 173 tests passed.
Production broke anyway: `POST /process` returned 422 on every Cloud Tasks
delivery, the scene was never claimed, and the queue retried indefinitely.

## What happened

`ProcessRequest` was imported at line 583 of `server.py` — after the
`@app.post("/process")` decorator at lines 539–578. FastAPI resolves type
annotations at decoration time via `typing.get_type_hints()`. At that
moment, `ProcessRequest` was not yet in the module namespace. FastAPI fell
back to treating `req` as a plain query parameter rather than a body model.
Cloud Tasks sends a JSON body, never a query string. `req` was always
"missing" → 422. The 422 detail was `{"loc":["query","req"]}` — the
`"query"` location is the diagnostic.

The handler-level tests called `handle_process()` directly. They never
exercised the route registration. A working `handle_process` can coexist
with a broken route indefinitely — the tests pass because they skip the
layer where the bug lived.

## What we chose

Two-layer test requirement for every FastAPI route:

1. **Handler test** — calls the handler function (or a close analogue)
   directly. Verifies orchestration, failure paths, state transitions.
   Fast, deterministic, no network.

2. **TestClient test** — sends an HTTP request through the full FastAPI
   stack via `TestClient`. Verifies route registration, annotation
   resolution, and request parsing. Even a minimal "request reaches
   handler with correctly-typed arguments" test closes the gap.

The TestClient tests live in
`services/perception-obj/tests/test_server_routes.py` and
`test_server_registry.py`. For `/process` specifically, the critical
assertion is that `handle_process` receives a `ProcessRequest` instance —
not that the test reaches a terminal state.

Additionally, the `"ProcessRequest"` string annotation was changed to
unquoted `ProcessRequest`. With `from __future__ import annotations` in
effect, all annotations are strings internally, but the explicit quoting
was what allowed the import to be misplaced without a load-time error. An
unquoted annotation fails with `NameError` at module load time if the
class is not yet imported — failing loudly at the right moment instead of
silently misrouting live requests.

## Why

Handler tests are necessary but not sufficient. They verify the logic of the
function. They do not verify:

- That FastAPI resolves the function's type annotations correctly
- That the route is registered under the right path and HTTP method
- That request parameters (body, form fields, path params) are parsed
  into the right types before the handler is called

A 422 from FastAPI body validation fires before the handler is ever invoked.
No handler test can catch it. TestClient tests can.

## What would change this decision

If FastAPI added a static annotation-resolution check at app build time
(e.g. a `app.check_routes()` call that raises on unresolvable annotations),
a subset of these TestClient tests could be replaced by that check. As of
FastAPI 0.115, no such mechanism exists.
