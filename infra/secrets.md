# Secrets

This document records which secrets exist in the project and how to create them.
Secrets themselves are never committed.

## `hf-token`

Hugging Face access token, used by Cloud Build to download gated model weights
(VGGT, SAM 3, SAM 3D Objects).

### Create

1. Generate a token at https://huggingface.co/settings/tokens.
   - Type: "Read" (sufficient) or "Fine-grained" with read access to:
     - `facebook/VGGT-1B`
     - `facebook/sam3`
     - `facebook/sam-3d-objects`

2. Save it to Secret Manager. Use `read -s` to avoid echoing the token
   or writing it to shell history:

```bash
# Create the empty secret first
gcloud secrets create hf-token --replication-policy=automatic --project=thegoodguest

# Read the token without echoing it to the screen
read -s HF_TOKEN
# (paste token, press Enter)

# Pipe it in
printf '%s' "$HF_TOKEN" | gcloud secrets versions add hf-token \
    --project=thegoodguest --data-file=-

# Wipe the variable from the shell
unset HF_TOKEN
```

3. Grant read access to the service account Cloud Build actually uses.

   **NOTE**: On projects created after late 2024 / early 2025, Cloud Build runs
   builds as the **Compute Engine default service account** (`PROJECT_NUMBER-
   compute@developer.gserviceaccount.com`), NOT the legacy `PROJECT_NUMBER@
   cloudbuild.gserviceaccount.com`. Bind the Compute SA:

```bash
PROJECT_NUMBER=$(gcloud projects describe thegoodguest --format='value(projectNumber)')
gcloud secrets add-iam-policy-binding hf-token \
    --project=thegoodguest \
    --member="serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
    --role=roles/secretmanager.secretAccessor
```

   If you're unsure which SA Cloud Build is using on this project, run:

```bash
gcloud builds describe BUILD_ID --region=asia-southeast1 \
    --format='value(serviceAccount)'
```

   after any build to see the SA that actually ran it. The deployed perception
   services do NOT read the secret at runtime (HF weights are baked into the
   image at build time), so only the build-time SA needs the binding.

### Verify

```bash
gcloud secrets list --project=thegoodguest
gcloud secrets versions access latest --secret=hf-token --project=thegoodguest | head -c 10 && echo
# Should print 'hf_' + 7 more characters.

gcloud secrets get-iam-policy hf-token --project=thegoodguest
# Should show exactly one accessor binding for the Compute SA.
```

### Rotation

To replace the token (revoke old, issue new on HF, then):

```bash
read -s HF_TOKEN
printf '%s' "$HF_TOKEN" | gcloud secrets versions add hf-token \
    --project=thegoodguest --data-file=-
unset HF_TOKEN
```

The cloudbuild configs reference `:latest`, so new builds automatically use the
new version. Existing deployed services aren't affected (weights are already in
the image).

## `anthropic-api-key`

Anthropic API key, created 2026-07-21. Unlike `hf-token` this one IS read at
runtime, by two services:

- **api-public** — the conversation guest model (decision 0058). Required in
  production: `_PRODUCTION_REQUIRED_VARS` in `services/api-public/public_server.py`
  lists it, so a missing key fails startup rather than degrading silently.
- **perception-obj** — shell material family inference (decision 0069), read at
  `services/perception-obj/shell_material.py:195`. Absent here it degrades by
  design: family inference switches off and planes ship the measured albedo as a
  clean matte.

Both mount it as `ANTHROPIC_API_KEY` from `:latest` via `--set-secrets`
(`infra/deploy_api_public.sh`, `infra/deploy_perception.sh`).

### Grants

Secret-scoped `roles/secretmanager.secretAccessor`, never project-scoped. Both
deploy scripts assert their own binding idempotently on every run —
`deploy_api_public.sh` for `api-public-runtime@`, and `ensure_obj_runtime_iam()`
in `deploy_perception.sh` for `perception-obj-runtime@`. api-public's also fails
fast if the secret is absent, since a `--set-secrets` deploy against a missing
secret fails later with a much less legible error.

A third accessor is currently bound and is NOT asserted by any script: the
default compute SA `502805861152-compute@developer.gserviceaccount.com`. It is a
leftover from before the dedicated runtime service accounts existed and is worth
revoking under decision 0090's least-privilege pass — check for a live consumer
first.

```bash
gcloud secrets get-iam-policy anthropic-api-key --project=thegoodguest
```

### Rotation

Add a new version. Both services mount `:latest`, which Cloud Run resolves when
an instance starts — so a redeploy guarantees the new version, and a revision
left running keeps whatever its live instances resolved at startup.

```bash
read -s ANTHROPIC_KEY
printf '%s' "$ANTHROPIC_KEY" | gcloud secrets versions add anthropic-api-key \
    --project=thegoodguest --data-file=-
unset ANTHROPIC_KEY
```

## Future secrets

Add new secrets here as they're created. Likely future addition:

- `gemini-api-key` — alternative reasoning model
