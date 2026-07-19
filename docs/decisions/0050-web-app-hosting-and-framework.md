# 0050 — Web app: Firebase Hosting + Next.js static export

**Date:** 2026-07-17
**Status:** Decided

## Context

The web app (Next.js + WebGPU splat rendering, per CLAUDE.md's "What we're building") had
never actually had its hosting or framework choice examined — "Next.js" appeared in CLAUDE.md's
initial framing with no recorded alternatives-considered process, and no hosting target had
been chosen at all before work on the web app was set to begin.

## What we tried

Compared three hosting targets — GitHub Pages, Vercel, Firebase Hosting — against what the
app actually needs: multiple views, login, and a WebGPU splat viewer. The backend already
lives separately on Cloud Run with Firebase JWT auth verified in-app, so the frontend needs no
server-side rendering, API routes, or middleware of its own — it's a client-heavy SPA
regardless of host.

- **GitHub Pages**: static-only, no server runtime. Works fine for a static-export Next.js
  SPA including multiple views and client-side auth gating, but: no custom response headers
  (CSP/Cache-Control/X-Frame-Options — only a partial `<meta>`-tag CSP workaround exists, and
  it excludes `frame-ancestors`), no PR preview deployments, no one-click rollback, and
  private-repo Pages needs a paid GitHub plan. Free for commercial use on public repos.
- **Vercel**: full custom headers via `vercel.json`, native PR previews, instant rollback,
  best-in-class first-party Next.js SSR/ISR support (irrelevant here — we don't need SSR).
  Its free Hobby tier is licensed for **non-commercial use only**; a "premium consumer
  product" intended to be monetized would need Pro ($20/mo/seat) regardless of repo
  visibility, which weakens the free-tier cost argument in Vercel's favor.
  Also fully separate vendor/account/billing from the rest of the GCP-based stack.
- **Firebase Hosting**: full custom headers via `firebase.json`, native SPA rewrites (no
  `404.html` hack needed), native PR preview channels (via the official GitHub integration),
  native rollback (Hosting release history), free tier allows commercial use, and — the
  deciding factor — it's the same Firebase project already used for iOS Auth. No new vendor,
  no new billing relationship, no new account to manage.

Framework-wise, considered keeping Next.js vs switching to Vite+React or SvelteKit, given
the app doesn't need any of Next's SSR/ISR/middleware machinery.

## What we chose

**Firebase Hosting** for hosting. **Next.js in static export mode** (`output: 'export'`) for
the framework, kept rather than switched.

## Why

Firebase Hosting closes every practical gap GitHub Pages had (headers, PR previews, rollback)
without introducing a second vendor the way Vercel would, and without Vercel's commercial-use
licensing wrinkle on its free tier. Given the app is a client-side SPA regardless of host,
Firebase Hosting's slightly less mature Next.js "Frameworks" SSR integration (vs. Vercel's,
which is built by the Next.js team) doesn't matter — we're not using SSR.

Next.js was kept over Vite+React/SvelteKit despite not needing SSR because the ecosystem
argument still holds even for a pure SPA: the largest body of WebGPU/three.js/React-Three-Fiber
tutorials and examples assumes Next.js, and it's the most hiring-familiar choice. The cost —
carrying App Router/RSC conventions and static-export caveats for capabilities we don't use —
was judged smaller than the ecosystem-availability benefit for a from-scratch build.

## What would change this decision

- If the web app ever needs real server-side rendering, API routes, or middleware (e.g. a
  lightweight backend-for-frontend proxy), Firebase Hosting's Next.js Frameworks integration
  would need to mature further, or the project would need to move to Vercel (accepting its
  licensing terms) or stand up the proxy as a separate Cloud Run service instead.
- If Vercel changes its Hobby-tier commercial-use restriction, or if PR-preview/rollback
  parity stops mattering (e.g. a different CI/CD setup is adopted), the vendor-consolidation
  argument for Firebase Hosting weakens and Vercel's SSR maturity becomes more relevant again.
