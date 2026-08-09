# roomstudio web

The web app: browse and view the rooms captured with the iOS app, and talk to
them. Next.js static export (decision 0050) deployed to Firebase Hosting; the
backend is api-public on Cloud Run, so this is a pure client-side SPA with no
server of its own.

## Dev

Node 22.

```bash
npm ci
npm run dev        # http://localhost:3000, mock data by default
npm test           # vitest
npx tsc --noEmit   # types
npx eslint .       # lint
npm run build      # static export to out/
```

Data modes (`NEXT_PUBLIC_API_MODE`, see `.env.example`):

- `mock` — offline fixtures, no backend, no auth. The default, and the only
  mode with no network dependency. `src/lib/api/mock.ts` covers every
  `SceneStatus`, and its `!`-prefixed bundle ids (`!error`, `!budget`,
  `!slow`, `!inflight`, `!v3`, `!move`, `!remove`, `!revert`) drive the states
  that are otherwise hard to reach.
- `live-local` — a local uvicorn api-public, authenticated with the dev
  `test-uid:` token its `NullTokenVerifier` accepts.
- `live` — deployed api-public, signed in with a real provider. The Firebase
  SDK only loads in this mode.

Sign-in reads an identity, it never creates one: an account is born on the
phone, and the web links to it. Google works today; Apple is gated on Apple
Developer Program enrollment (decisions 0051, 0094). Signed out, every surface
renders an invitation rather than an error and makes no network call.

`.env.production` is committed and is what `next build` reads, so a bare build
from a fresh checkout is the Hosting artifact. Nothing in it is secret — every
`NEXT_PUBLIC_*` value is a public identifier. `.env.local` overrides it for
local work and `next dev` never reads it.

To see an assembled room offline, stage the synthetic fixtures once from the
repo root:

```bash
python tools/make_synthetic_splat.py      # a synthetic room + manifest
python tools/make_shell_v3_fixtures.py    # shell.json v3, both methods
```

Then `/viewer` loads `/dev-fixtures/manifest.json`, or `/viewer?fixture=<dir>`
loads a staged real-scene fixture. Fixtures are gitignored — they are real
captured rooms — and are excluded from Hosting in `firebase.json` so a deploy
cannot publish one.

## Routes

Room-centric: `/` (the landing hero — the reveal's first two movements over a
real room's measured geometry), `/rooms` (the browser), `/room?bundle=` (one
room: the wait, the reveal, the inventory, the composer), `/new` (scan
instructions and a listening panel), `/privacy` and `/terms` (the legal pages,
which App Store review needs at a URL), `/viewer` (dev workbench, hidden from
nav in live mode).

`/room` uses a query param rather than a path segment because a static export
cannot prerender unknown segments.

## Structure

- `src/lib/api/` — the typed client for api-public (mock + live), manifest-v2
  types, and `assembleScene` (assets → positioned splats + shell planes).
- `src/lib/` — decisions extracted out of React so they can be pinned as
  tables rather than reviewed by eye. Each has a `.test.ts` beside it:
  `reveal.ts` (the whole reveal score), `voice.ts` (copy grounded in real
  counts), `shell3d.ts`, `designSpec.ts`, `viewerKey.ts`, `status.ts`,
  `heroRoom.ts`, `seen.ts`, `account.ts`, and `conversation/` (the composer
  reducer).
- `src/components/SplatViewer.tsx` — the ONLY module that touches the rendering
  library (three.js + @sparkjsdev/spark). Its input contract is a list of
  `PositionedSplat`s, so a renderer swap is a one-file rewrite. It PLAYS the
  reveal score; it does not decide it.
- `src/components/ui/spring.tsx` — the DOM motion system; see its header for
  the two deliberate exceptions.
- `src/components/Wordmark.tsx` — the placeholder wordmark. NO PRODUCT NAME HAS
  BEEN CHOSEN; its header lists everywhere else the string is user-visible.
- `firebase.json` — Hosting config including the CSP. Three entries in it are
  load-bearing and were each found by a blank screen, not by review:
  `connect-src` must allow api-public and `storage.googleapis.com` (splats) and
  `data:` (Spark's wasm); `script-src` needs `'wasm-unsafe-eval'` for that wasm
  to compile at all; `frame-src` and `apis.google.com` carry the sign-in popup.

## Design language

The Good Guest system (decision 0057, superseding 0056): warm and light-first —
parchment and cream surfaces, warm-brown ink, rust for primary actions, and
muted gold used ONLY as a light semantic, never as decoration. Source Serif 4
is the guest's voice and the display face, Instrument Sans is the UI, IBM Plex
Mono is eyebrows and machine data. All three are `next/font`, self-hosted at
build, which is why the CSP needs no font host.

Colour belongs to the room and its light. Chrome stands down — on `/room` the
nav and footer withdraw entirely.

## A quirk worth knowing before you edit copy

SWC drops the leading space when a JSX text run follows an element or an
`{expression}` and begins with an escaped entity. It is invisible to vitest,
tsc, eslint, and the build — the first time it was caught, the deployed page
read "room.The app keeps". Verify rendered copy in a browser, not in source.
See `AGENTS.md`.
