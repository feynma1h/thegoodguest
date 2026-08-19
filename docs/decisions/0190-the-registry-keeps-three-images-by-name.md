# 0190 — the registry keeps three images, and one of them is kept by name

**Date:** 2026-08-19
**Status:** Decided — executed 2026-08-19

## Context

Artifact Registry was 64% of the project's cloud bill. The repository held
1,446.7 GiB across 75 images, of which 1,430.8 GiB was 39 `perception-obj`
images averaging 38 GiB each — 22 of them from May, the pre-RoomPlan era.
`gcloud artifacts repositories describe roomstudio` returned no
`cleanupPolicies` field at all: nothing had ever deleted an image, and every
build since 2026-05-13 was still being paid for.

The bill is in **INR**, not USD (billing account `01DA27-90C1F7-6268ED`
reports `currencyCode: INR`), so Aug 7–18 was ₹10,389 ≈ US$124. That is worth
stating because the same numbers read as a five-figure emergency in the wrong
currency, and the response to a $10,000 fortnight is not the response to a
$124 one.

## What we tried

**Recency alone, which is the obvious policy and is not sufficient here.**
A `mostRecentVersions` KEEP with `keepCount: 3` protects the live image only
while it is among the three newest, and the registry already shows that
failing: of the three newest `perception-obj` images, **two were built and
never deployed** — `20260810-023434` is decision 0120's cache-seeding build
(build `5ab7cb34`, "traffic verified untouched throughout") and
`20260816-050851` is decision 0182's rebuild. The live image is second-newest
today. Two more builds that do not flip and a recency-only policy reclaims the
image Cloud Run is serving, on a service that scales to zero — so the next
`/process` request would fail to start an instance.

**Correcting the keep-list.** The split the coordinator proposed and the
operator saw named `20260810-023434` as "one rollback behind". It is not a
rollback target: no Cloud Run revision has ever referenced that digest. The
image that actually served before the current one is `20260810-002003`
(revision `perception-obj-00038-7b5`), and it sits fourth by recency — so the
raw policy would have kept the cache seed and deleted the only deployable
rollback.

## What we chose

`infra/artifact-cleanup-policy.json`, applied to the `roomstudio` repository:

- KEEP anything tagged `serving` or `buildcache`.
- KEEP the 3 most recent `perception-obj` versions.
- KEEP the 10 most recent `api-*` versions (0.1 GiB each; the count buys two
  months of rollback for nothing).
- DELETE everything else under the `perception-obj` and `api` prefixes, at any
  age. `perception-geom` is outside every prefix and the policy cannot touch
  it.

A stable `serving` tag now points at the live digest, and
`infra/deploy_perception.sh` moves it **at the traffic flip** — in direct mode
automatically, in candidate mode as a printed command beside the flip.

The one-off delete was ordered so that policy and intent agree afterwards: the
never-deployed cache seed `20260810-023434` was deleted alongside the 35 old
images, which promotes `20260810-002003` into the top three. From then on the
policy is a no-op on the kept set.

## Why

**The DELETE condition carries no age.** That is what makes the steady state
statable: after N future builds the repository holds exactly three
`perception-obj` images, not "three plus whatever is younger than 30 days".
An age-based delete would have let the heaviest fortnight in the project's
history (10 perception builds in 12 days) hold 380 GiB and still be compliant.

**Two protections, both failing safe.** Recency is automatic but depends on
deploy rhythm; the tag is explicit but depends on discipline. They fail in
opposite directions, and the tag's failure mode is over-keeping one stale
image — which costs about $4/month and breaks nothing. A cleanup policy has no
knowledge of Cloud Run, so the live image's protection had to come from
somewhere; a name is the only thing the registry understands.

**`buildcache` is kept by name for the same reason**, though today it is also
newest: it is the tag `infra/cloudbuild/perception-obj.yaml` reads with
`--cache-from`, and losing it costs a ~58-minute uncached build (0120, whose
5.1× speedup was measured in 0164).

**Rollback that far back was never a live option.** Everything below revision
`00040` is May–July code, and the deploy discipline is candidate → smoke →
flip with a named rollback target (0163). Keeping the last image that actually
served preserves the rollback that discipline actually uses; keeping 36 of
them preserved an option nobody would exercise, at ₹6,700 per fortnight.

## What would change this decision

- If perception ever needs a rollback more than one deploy deep — a defect
  found weeks after a ship — raise `keepCount` and accept ~38 GiB per extra
  image (~$4/month).
- If a build cadence appears where three consecutive builds routinely do not
  flip, the `serving` tag stops being belt-and-braces and becomes the only
  protection; that is the point to raise `keepCount` rather than rely on it.
- If Artifact Registry ever learns which images Cloud Run is serving, the tag
  and its deploy-script step can go.

## Outcome (2026-08-19)

Executed with the operator's explicit approval. **51 images deleted, 51/51
succeeded, 0 failures.** The registry now holds exactly the predicted set: 3
`perception-obj` (114.2 GiB), 10 `api-public`, 10 `api-internal`, 1
`perception-geom` — **24 images, 128.7 GiB, from 1,446.7 GiB.** The `api`
package is gone entirely. The policy was then flipped out of dry-run and is
live; it is a no-op on what remains, by construction.

The load-bearing verification is not the count. `perception-obj` scales to
zero, so after deleting 36 of its 39 images an authenticated `/health` **cold
started in 12.99 s** and a second call answered in **0.40 s** — the first was a
real instance start with a real image pull, which is the only thing that proves
the delete did not strand the serving image. `/ready` returned 503
`not_loaded`, the 0024 lazy-load posture. The rollback target's manifest fetches
200 **by digest**, and a real 28.6 MB layer blob downloads at 200 — bytes, not
just metadata. All four services: api-public 200 unauth, api-internal 403 / 200
authed, perception-obj 403 unauth (0106's gate intact) / 200 authed,
perception-geom 200.

**Storage reclamation lags the delete, and the next person needs to know it.**
Immediately after, `Repository Size` still read 1,477,656 MB and the files API
still summed **1,376.2 GiB** against 128.7 GiB of live image content — the
manifests are gone, the layer blobs are garbage-collected on Artifact
Registry's own background schedule. 70.5 GiB had been reclaimed within minutes;
the rest follows over roughly a day. So *the bill does not fall the moment the
images disappear from `images list`*, and neither the size metric nor the file
listing is the place to check whether the delete worked — enumeration is.

One dead end worth not repeating: the `owner` field on a file is **not** a
garbage-collection signal. It is populated only on manifest files, so a layer
belonging to a *kept* image reads `owner: <none>` exactly like a layer belonging
to a deleted one. Reading it as "orphaned" gives 1,335 files and a wrong story.
