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
gcloud secrets create hf-token --replication-policy=automatic --project=roomstudio

# Read the token without echoing it to the screen
read -s HF_TOKEN
# (paste token, press Enter)

# Pipe it in
printf '%s' "$HF_TOKEN" | gcloud secrets versions add hf-token \
    --project=roomstudio --data-file=-

# Wipe the variable from the shell
unset HF_TOKEN
```

3. Grant read access to the service account Cloud Build actually uses.

   **NOTE**: On projects created after late 2024 / early 2025, Cloud Build runs
   builds as the **Compute Engine default service account** (`PROJECT_NUMBER-
   compute@developer.gserviceaccount.com`), NOT the legacy `PROJECT_NUMBER@
   cloudbuild.gserviceaccount.com`. Bind the Compute SA:

```bash
PROJECT_NUMBER=$(gcloud projects describe roomstudio --format='value(projectNumber)')
gcloud secrets add-iam-policy-binding hf-token \
    --project=roomstudio \
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
gcloud secrets list --project=roomstudio
gcloud secrets versions access latest --secret=hf-token --project=roomstudio | head -c 10 && echo
# Should print 'hf_' + 7 more characters.

gcloud secrets get-iam-policy hf-token --project=roomstudio
# Should show exactly one accessor binding for the Compute SA.
```

### Rotation

To replace the token (revoke old, issue new on HF, then):

```bash
read -s HF_TOKEN
printf '%s' "$HF_TOKEN" | gcloud secrets versions add hf-token \
    --project=roomstudio --data-file=-
unset HF_TOKEN
```

The cloudbuild configs reference `:latest`, so new builds automatically use the
new version. Existing deployed services aren't affected (weights are already in
the image).

## Future secrets

Add new secrets here as they're created. Likely future additions:

- `anthropic-api-key` — for the reasoning service's Claude calls
- `gemini-api-key` — alternative reasoning model
- `supabase-service-key` — when the API service connects to the database
