# roomstudio web

The web app: browse, view, and (eventually) edit the scenes captured with
the iOS app. Next.js static export (decision 0050) deployed to Firebase
Hosting; the backend is api-public on Cloud Run — this app is a pure
client-side SPA.

## Dev

```bash
npm install
npm run dev        # http://localhost:3000, mock data by default
npm test           # vitest unit tests
npm run build      # static export to out/
```

Data modes (`NEXT_PUBLIC_API_MODE`, see `.env.example`): `mock` (offline
fixtures, default), `live-local` (local uvicorn api-public), `live`
(deployed api-public + Firebase anonymous auth — sees no scenes until the
iOS account-linking work from decision 0051 ships).

To see an assembled room offline, generate the synthetic fixtures once:

```bash
python tools/make_synthetic_splat.py   # from the repo root
```

then open /viewer (it auto-loads `/dev-fixtures/manifest.json`), or use
the mock ready room at /rooms.

## Structure

Routes are room-centric: `/` (thesis landing), `/rooms` (browser),
`/room?bundle=` (a single room — the viewer embeds HERE when ready),
`/new` (scan instructions), `/viewer` (dev workbench, hidden from nav in
live mode).

- `src/lib/api/` — typed client for api-public (mock + live), manifest-v2
  types, and `assembleScene` (assets → positioned splats).
- `src/components/SplatViewer.tsx` — the ONLY module that touches the
  rendering library (three.js + @sparkjsdev/spark). Its input contract is
  a list of `PositionedSplat`s; a renderer swap is a one-file rewrite.
- `src/components/Wordmark.tsx` — the placeholder wordmark; NO PRODUCT
  NAME HAS BEEN CHOSEN, and this file is the single point of change.
- `firebase.json` — Hosting config incl. the CSP (connect-src must allow
  api-public and storage.googleapis.com or the viewer loads nothing).

Type system (founding draft, decision 0055): serif (Fraunces) = feeling,
mono (DM Mono) = thinking, sans (Geist) = chrome. Never serif and mono in
the same sentence.
