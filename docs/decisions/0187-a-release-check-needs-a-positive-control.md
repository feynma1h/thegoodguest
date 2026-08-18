# 0187 — a content-marker release check needs a positive control

**Date:** 2026-08-18
**Status:** Decided

## Context

Firebase Hosting dedupes files by content hash, so an unchanged file keeps an
older `Last-Modified` across releases. That header is not a release marker and
cannot answer "what is currently live". `firebase hosting:releases:list` is not
a command in firebase-tools 15.24.0 either.

What remains is a content marker: fetch the deployed JavaScript and look for a
string that only the candidate commit introduces. That works, and it has one
trap sharp enough to invert the answer.

## What we tried

Verifying which of three commits a production release would carry. The first
pass fetched `/`, extracted its `_next/static/chunks` references, and searched
them for three strings introduced by the unreleased work. All three were
absent, which reads as "not deployed" and happened to be the right conclusion.

It was right by luck. The same search also found **zero** occurrences of
strings that were unquestionably already live. **Next.js code-splits per
route**, so the landing page never references the room page's chunks, and the
search had been looking at bundles that could not contain any of these strings
either way.

An absence proves nothing until you have shown the search could have found
something.

## What we chose

**Every content-marker release check carries a positive control.**

Pick a string that is known to be live — ideally the very string the candidate
commit REPLACES — and require that it is FOUND. If the control is absent, the
scoping is wrong and no conclusion about the candidate markers may be drawn.

Concretely, for this repo: fetch the route that actually renders the feature,
take its chunk list from that route's HTML, and grep the downloaded files
rather than piping bodies through the shell — some chunks contain bytes that
break shell string handling and produce silent per-chunk failures that look
like clean misses.

The check that settled the release: on `/room`, `"back to measured"` (the old
revert-control string) was present, and `"turned round"`, `"where you told me
it faces"` and `"undoes the turn"` were all absent. The present control is what
makes the three absences evidence.

## Why

The failure is asymmetric and quiet. A wrongly-scoped search returns absences,
absences read as "not yet deployed", and the natural next act is to deploy —
which is harmless when it happens to be true and is a redundant production
release when it is not. Nothing errors, and the report reads clean either way.

The positive control costs one extra grep and converts an unfalsifiable check
into a falsifiable one.

## What would change this decision

If Firebase Hosting exposes a usable release manifest — a working
`releases:list`, or a per-release file listing — that is a direct answer and
the marker method becomes a cross-check rather than the primary instrument.

If the app stops code-splitting per route, the scoping trap disappears, but the
positive control is still the thing that makes an absence mean anything.
