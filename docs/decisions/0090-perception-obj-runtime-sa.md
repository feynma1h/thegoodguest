# 0090 — perception-obj runs as a dedicated least-privilege runtime SA

**Date:** 2026-08-08
**Status:** Decided — built and deployed; closes decision 0088's finding 1

## Context

0088's IAM audit found that perception-obj — the service that parses UNTRUSTED
user capture bundles, runs the heaviest third-party model code, and holds a
GPU — ran as `502805861152-compute@developer.gserviceaccount.com`, the default
compute service account, which holds project-level `roles/editor`. It could
write any resource in the project. api-public and api-internal have had
dedicated least-privilege runtime SAs since the two-service split; perception
predates that discipline and inherited Editor by default, which is also why it
never needed explicit bucket grants.

## The decision

`perception-obj-runtime@roomstudio.iam.gserviceaccount.com` owns the workload,
granted exactly what the code reaches and nothing else:

| grant | scope | why |
|---|---|---|
| `storage.objectViewer` | `gs://roomstudio-captures` | reads bundles, frames, depth, room.json. **Read only** — the service never writes to captures |
| `storage.objectAdmin` | `gs://roomstudio-perception-outputs` | splats, manifests, masks, shell.json: read + write + existence checks |
| `datastore.user` | project | the `scenes` claim/release transactions; cannot touch indexes or databases |
| `logging.logWriter`, `monitoring.metricWriter` | project | Cloud Run runtime baseline |
| `secretmanager.secretAccessor` | secret `anthropic-api-key` | shell material inference (0069); secret-scoped, the api-public pattern |
| `cloudtasks.enqueuer` | queue `perception-dispatch` | /process enqueues its own /shell task (0066) |
| `iam.serviceAccountUser` | SA `tasks-invoker@` | actAs for the OIDC task token |
| **custom** `perceptionFcmSender` | project | terminal-transition notifications |

The FCM grant is a CUSTOM role holding exactly `cloudmessaging.messages.create`.
The predefined `roles/firebasecloudmessaging.admin` is the obvious choice and
was rejected: it also grants `topicSubscriptions.*` (create/delete/update),
which `fcm.py` never touches. A custom role costs a line in the deploy script
and is the difference between "can send a message" and "can rewrite the
project's push-subscription topology" — a distinction worth keeping in the
service whose over-privilege opened this note.

## Where the grant list lives

In `ensure_obj_runtime_iam()` in `infra/deploy_perception.sh`, running on every
`obj` deploy. It is idempotent (`add-iam-policy-binding` no-ops when the
binding exists) and it creates the SA and the custom role if absent, so the
function IS both the documentation and the reproduction. It replaces two
scattered blocks — a pre-deploy secret grant and a post-deploy shell grant —
that each resolved the runtime SA by describing the LIVE service, meaning they
would have silently granted the old SA forever. The deploy now passes
`--service-account` explicitly and asserts the served spec afterwards.

Ordering is load-bearing and inherited from the 0069 deploy failure: IAM runs
BEFORE `gcloud run deploy`, because both `--service-account` and
`--set-secrets` are validated at revision creation, so an ungranted SA fails
the deploy itself.

## A bash trap fixed in passing

`--platform=managed` seeds the `DEPLOY_FLAGS` array so it is never empty.
Expanding an empty array under `set -u` is an unbound-variable ERROR on bash
< 4.4, and macOS ships 3.2 as `/bin/bash` — the `geom` path (which takes no
`--service-account`) would have died on an operator machine without a homebrew
bash, in a script neither service's change touched.

## What is deliberately NOT done

**Removing `roles/editor` from the default compute service account.** 0088
recommended "consider" it, and it is the obvious next move, but other things
may still ride that SA and verifying that is its own pass — an audit, not a
side effect of a perception deploy. perception-obj no longer contributes a
reason to keep it.

## What would change this decision

- A new code path reaching a resource not in the table above fails at runtime,
  not at deploy — a missing grant surfaces deep inside a GPU run. Add the grant
  to `ensure_obj_runtime_iam` in the same commit as the code, never afterwards.
- If the default compute SA's Editor is eventually removed, note it here and
  close 0088's finding 1 completely.
- If FCM ever needs topic subscriptions, the custom role grows one permission
  — do not swap it for the predefined admin role.
