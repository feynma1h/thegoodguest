# 0325 — what the person's boxes reveal, and where they live

**Date:** 2026-11-05
**Status:** Decided

## Context

`person_boxes` and `boxes.json` (decisions 0320, 0322) are new stored data
about a home. They carry no pixels, but they say where the person's furniture is,
how big it is and what the detector called it.

## What we chose

- **Content**: id, the detector's class name, centre, yaw, size and a relative
  time — nothing else. No photo, mask, or detector internals ever enters the
  bundle through this field (the phone writer has no access to any).
- **Where**: inside the bundle in the captures bucket (deleted after one day by
  lifecycle, as the rest of the bundle), and in `boxes.json` in the outputs
  bucket, which is ready-room data: kept as long as the room, deleted with the
  account (the whole `scenes/{id}/` prefix goes, decision 0086 and the account
  deletion route).
- **Not logged**: `/process` logs counts only, never ids, labels or positions.
- **Treated as untrusted**: the bundle is client-supplied, so the cloud
  validates numbers, bounds, ids and count itself and caps the label length
  (0322). A label is advisory text; a later stage that quotes it in a prompt must
  treat it as data.
- **Privacy manifest**: the iOS app's declared data types are unchanged. The
  boxes are derived from the same camera session the bundle already uploads, and
  the field is written only by Debug builds while live boxes is Debug-only
  (0295). When live boxes ships, the privacy declaration should be re-read for
  "other user content" before that release; this note does not decide it.

## Why

Smallest content that serves the stated purpose, stored with data of the same
sensitivity and lifetime, deleted by the same existing path.

## What would change this decision

Adding anything pixel-shaped per box (a thumbnail), keeping boxes beyond the
room's life, or sending labels to a third party in an unvalidated form.
