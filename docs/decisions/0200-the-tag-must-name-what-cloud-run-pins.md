# 0200 — the tag must name what Cloud Run pins

**Date:** 2026-08-20
**Status:** Decided; caught before it could bite, fixed in the build config

## Context

Decision 0199 moved the `perception-obj` build from `docker build` to
`docker buildx`. That is a change of build *tool*, and it was made for a
reason that had nothing to do with what the tool publishes.

Decision 0190 protects the live perception image from the registry cleanup
policy by TAG: `serving` is moved onto the deployed image at every traffic
flip, because recency alone is not protection on a service whose live image is
routinely not the newest. `deploy_perception.sh`'s `move_serving_tag` tags
`${IMAGE_URI}` — the timestamped tag the build pushed.

That whole arrangement rests on an assumption nobody had written down: **the
tag and the digest Cloud Run pins are the same object.**

## What we tried

Nothing was tried; this was caught by looking at the registry between the
smoke and the flip, before `serving` was moved.

The first buildx build pushed **three** versions at the same instant, not one:

| digest | tag |
|---|---|
| `1001adc7…` | `20260821-010928` |
| `5729d84d…` | (none) |
| `faa005c8…` | (none) |

And the candidate revision reported:

```
perception-obj-00062-hum → …/perception-obj@sha256:faa005c8…
```

buildx attaches a provenance attestation by default. That makes the pushed
artifact an **OCI index** over `{real image, attestation}`. The timestamped tag
names the *index*; Cloud Run resolves the index, picks the `linux/amd64` child,
and pins that child by digest — and the child carries no tag at all.

So `move_serving_tag` would have tagged `1001adc7`, the index, and left
`faa005c8` — the digest a scale-to-zero GPU service must pull to start —
untagged. Untagged is exactly what 0190's delete rule matches. The three new
versions were inside the "3 newest" Keep rule on the day, so nothing would have
broken immediately; three more builds later, the cleanup policy would have
deleted the image production boots from while faithfully preserving a tag that
pointed at an index whose child was gone.

The repository's `cleanupPolicyDryRun` is unset — the policy deletes for real.

## What we chose

`--provenance=false --sbom=false` on the buildx invocation, restoring the
single-manifest artifact `docker build` used to produce.

For the image already pushed, `serving` was applied to the **digest Cloud Run
reported**, read back from the revision, rather than to the timestamped tag.

## Why

The attestation buys nothing here. It exists to let a *consumer* verify build
provenance; this registry has exactly one consumer, Cloud Run, in the same
project as the builder, and nothing in the deploy path reads it. Against that,
it silently changed the shape of the published artifact in a way that broke an
invariant three other pieces depend on.

Fixing the publisher rather than the taggers is the smaller change and the one
that stays fixed. The alternative — teaching `move_serving_tag` to resolve an
index to its amd64 child — would leave every other tag-shaped assumption in the
repo (and any future one) still wrong, and would make the deploy script carry
registry-format knowledge it has no other reason to have.

**The general rule this leaves:** a tag is only protection if it names the
object the runtime pins. When those can differ, read the digest back from the
deployed revision and tag *that*, and prefer a publisher that cannot make them
differ in the first place.

## What would change this decision

If image signing or SLSA provenance ever becomes a requirement — a public
registry, a second consumer, a compliance ask — then attestations come back and
`move_serving_tag` must resolve the index to its platform child instead. The
tell that this has regressed is a build publishing more than one version at the
same timestamp: one build, one version, is the invariant to check.

## Outcome

Caught before the flip, so no untagged live image ever existed. The rollback
target for this deploy, `perception-obj-00044-m5p`'s image `d15ca00d…`, lost
its `serving` tag at the flip and was held with a
`serving-rollback-00044-m5p` tag while the new revision was proven — the Keep
rule matches on tag PREFIX, so a `serving…`-prefixed tag is a deliberate,
removable hold. That is a useful idiom and a sharp edge: the same prefix match
means any tag beginning with `serving` pins an image in the registry forever
until someone removes it.
