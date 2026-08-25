# 0246 — a yanked transitive dependency, and why the cure is a rebuild

**Date:** 2026-08-25
**Status:** Decided

## Context

`api-public-00044-wiz` — deployed 2026-08-24 22:29 with `PROMPT_VERSION 7` —
returned HTTP 500 on every Firestore read path. `GET /scenes` and
`GET /scenes/by-bundle/{id}` both failed, which is the rooms list the phone
asks for at every launch, and `upload_session_repo` builds its client the same
way, so minting an upload session was broken too. The service could not serve a
single authenticated request.

The traceback ended at:

```
google.api_core.exceptions.InvalidArgument: 400 Invalid database id %28default%29
```

`(default)` was reaching Firestore percent-encoded. Nothing in this repo passes
a database name — `scene_read_repo.py` and `upload_session_repo.py` both call
`_fs.Client(project=project)` and take the library default.

## What we tried

The revision was a clean regression, established before anything was changed:
all ten production 500s were on `00044-wiz`, and the previous revision
`00042-ruq` served `GET /scenes?limit=50` with 200 as recently as eighteen
minutes before `00044` was created.

Neither `services/api-public/Dockerfile` nor `packages/api-core/pyproject.toml`
had been touched in months, so the source was identical and only the RESOLVED
dependency versions could have moved. Cloud Build logs for the two builds gave
them exactly:

| package | working `00042` | broken `00044` |
|---|---|---|
| google-cloud-firestore | 2.28.1 | **2.29.0** |
| google-api-core | 2.34.0 | **2.35.0** |
| proto-plus | 1.28.3 | 1.28.3 |
| protobuf | 7.36.0 | 7.36.0 |

`protobuf` and `proto-plus` are identical across the two, which rules out the
Dockerfile's `--force-reinstall "protobuf>=7.35.0"` workaround — the loudest
and most obvious suspect in that file, and innocent.

Two packages moved, so the pair was bisected against real Firestore rather than
reasoned about:

| combination | result |
|---|---|
| firestore 2.28.1 + api-core **2.35.0** | **FAIL** — reproduces the exact error |
| firestore 2.29.0 + api-core **2.34.0** | OK |

**The culprit is `google-api-core`, which this repo does not declare.**
`google-cloud-firestore` — the package we DO declare, the one named in the
traceback, and the only plausible suspect by name — is innocent at 2.29.0.

PyPI then explained it. `google-api-core` 2.35.0 was uploaded 2026-08-24 and is
**yanked**, with the reason recorded on the release:

```
regression in path_template.expand. See issue #18213
```

`path_template.expand` is the function that builds resource paths, which is
precisely how `(default)` becomes `%28default%29`. The api-public build ran
2026-08-24 22:27 — inside the window when 2.35.0 was live and before it was
pulled.

## What we chose

**Rebuild. No pin, and no code change.**

pip excludes yanked releases from resolution, so a rebuild resolves 2.34.0 on
its own. The fix is the build, not the source.

Deliberately NOT done: pinning `google-api-core<2.35`. It would have worked
today and been wrong tomorrow — it blocks the 2.35.1 that will carry the
upstream fix, and it hard-codes into our source a fact that PyPI already
publishes and maintains. A yank is the ecosystem's own mechanism for this
class, and it is better maintained than our pin file would be.

## Why

The reasoning that matters is not about this package; it is about which suspect
to chase.

Everything visible pointed at `google-cloud-firestore`: it is the package we
declare, it is the module in the traceback, it is the one with an open version
range in `pyproject.toml`, and it had genuinely moved a minor version between
the two builds. Pinning it would have been a defensible-looking one-line fix,
it would have shipped, and it would NOT have worked — because the broken code
was in a package we never named.

Bisecting the two candidates cost three `pip install` runs and one query against
real Firestore. That is cheap against a deploy cycle spent on the wrong pin, and
it is the only reason the answer is right.

The second durable point: an unpinned build is not reproducible, and the failure
mode is not the usual one. The usual worry is "a new release breaks us". The
sharper version is that **a build can capture a release that the publisher later
withdraws** — after which the same source, rebuilt, silently produces a
different and working image. "Rebuild it and see" is normally a way of avoiding
diagnosis; here it IS the fix, and the diagnosis is what proves that.

## What would change this decision

If a build ever again resolves a dependency that is later yanked, check the yank
reason FIRST — `curl https://pypi.org/pypi/<pkg>/json` carries it per release,
and `pip index versions <pkg>` omits yanked releases entirely, so a version that
installs by exact pin but is absent from the index listing is the tell.

If we ever need reproducible builds for their own sake — an audit requirement, or
a rollback that must reconstruct a specific image — then the answer is a full
lockfile for every service, not a scattering of hand-added pins on whichever
package broke last. That is a different and larger decision, and this incident is
an argument for it rather than a substitute.
