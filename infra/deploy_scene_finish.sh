#!/usr/bin/env bash
# Deploy scene-finish to Cloud Run.
#
# Run from the repo root:
#     ./infra/deploy_scene_finish.sh               # deploy, straight to 100%
#     ./infra/deploy_scene_finish.sh --candidate   # hold the revision at 0%, smoke, then flip
#     CANDIDATE_TAG=<lane> ./infra/deploy_scene_finish.sh --candidate   # your own tag per lane
#
# scene-finish is a CPU-only service (decision 0330 and the phase 2 design): it
# draws the room viewer in headless Chrome with software GL, so it needs no GPU,
# no model weights and no HF token. It is NOT part of perception-obj: that is one
# L4 instance at concurrency 1 with a ~195 s model load, and the finish work wants
# many small parallel workers that cannot starve SAM.
#
# WHAT THIS DEPLOYS IS RENDER-ONLY (decision 0363): /health, /render and /still,
# the room's still picture for the app. The Claude-layer routes (/finish,
# /furniture-piece, /furniture-merge) are not registered in finish_server.py, so
# no Anthropic key is mounted and none is granted; switching that layer on adds
# both back, with the secret-scoped grant perception-obj and api-public use.
#
# Prerequisites:
#   1. The Cloud Tasks queue 'perception-dispatch' and tasks-invoker@ exist.
#   2. Cloud Run Admin, Artifact Registry and Cloud Build APIs enabled.
#
# Sizing is an ESTIMATE (design 3, from a 10-core Mac measurement): 4 vCPU,
# 8 GiB, concurrency 1, 900 s. Software GL is multithreaded, so a render is
# slower here than on the measuring machine; re-measure on the first candidate
# before trusting the numbers.

set -euo pipefail

CANDIDATE_MODE=0
if [[ $# -gt 1 || ( $# -eq 1 && "$1" != "--candidate" ) ]]; then
    echo "Usage: $0 [--candidate]"
    exit 1
fi
[[ $# -eq 1 ]] && CANDIDATE_MODE=1

SERVICE="scene-finish"
CONTEXT_DIR="services/scene-finish"
CLOUDBUILD_CONFIG="infra/cloudbuild/scene-finish.yaml"

PROJECT_ID="thegoodguest"
REGION="asia-southeast1"
REPO="thegoodguest"

# Dedicated least-privilege runtime SA, the perception-obj pattern (decision
# 0090): everything it is granted is enumerated in ensure_runtime_iam below.
RUNTIME_SA="scene-finish-runtime@${PROJECT_ID}.iam.gserviceaccount.com"
CANDIDATE_TAG="${CANDIDATE_TAG:-candidate}"
INVOKER_SA="tasks-invoker@${PROJECT_ID}.iam.gserviceaccount.com"
# The service's own URL: the audience its task routes check (task_auth.py).
# Cloud Run names a service URL from the service, the project and the region,
# so it is known before the first deploy; the end of this script checks it.
RECEIVER_URL="https://${SERVICE}-o4dhc34kqq-as.a.run.app"
IMAGE_TAG="$(date +%Y%m%d-%H%M%S)"
IMAGE_URI="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO}/${SERVICE}:${IMAGE_TAG}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

# ---------------------------------------------------------------------------
# Runtime IAM. All idempotent, scoped to the exact resource wherever the API
# allows. Runs BEFORE the deploy: --service-account and --set-secrets are
# validated at revision creation.
# ---------------------------------------------------------------------------
ensure_runtime_iam() {
    echo "=== Runtime IAM for ${RUNTIME_SA} ==="

    gcloud iam service-accounts describe "${RUNTIME_SA}" \
        --project="${PROJECT_ID}" >/dev/null 2>&1 \
      || gcloud iam service-accounts create scene-finish-runtime \
            --project="${PROJECT_ID}" \
            --display-name="scene-finish Cloud Run runtime" \
            --description="Least-privilege runtime SA for scene-finish"

    # Capture bundles: READ ONLY (poses, intrinsics, frames; never written).
    gcloud storage buckets add-iam-policy-binding "gs://thegoodguest-captures" \
        --member="serviceAccount:${RUNTIME_SA}" \
        --role="roles/storage.objectViewer" \
        --project="${PROJECT_ID}" >/dev/null

    # Perception outputs: read shell.json/finish.json/furniture.json, write
    # and delete scenes/<id>/still.jpg and still-night.jpg (and, once the
    # Claude layer runs, finish.json, furniture.json and work/). The same
    # managed role perception-obj holds.
    gcloud storage buckets add-iam-policy-binding "gs://thegoodguest-perception-outputs" \
        --member="serviceAccount:${RUNTIME_SA}" \
        --role="roles/storage.objectAdmin" \
        --project="${PROJECT_ID}" >/dev/null

    # Firestore, for one field: /still marks the scene document `still` after
    # writing the pictures (decision 0363), with update(), never touching
    # status, so it still cannot un-ready a room (design 4.5). Firestore IAM
    # has no per-collection role; this is the role perception-obj holds.
    gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
        --member="serviceAccount:${RUNTIME_SA}" \
        --role="roles/datastore.user" --condition=None >/dev/null

    gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
        --member="serviceAccount:${RUNTIME_SA}" \
        --role="roles/logging.logWriter" --condition=None >/dev/null
    gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
        --member="serviceAccount:${RUNTIME_SA}" \
        --role="roles/monitoring.metricWriter" --condition=None >/dev/null

    # The finish route enqueues one piece task per boxed object, and a piece
    # enqueues the merge: enqueue rights on the queue and actAs on the OIDC
    # invoker identity.
    gcloud tasks queues add-iam-policy-binding perception-dispatch \
        --location="${REGION}" --project="${PROJECT_ID}" \
        --member="serviceAccount:${RUNTIME_SA}" \
        --role="roles/cloudtasks.enqueuer" >/dev/null
    gcloud iam service-accounts add-iam-policy-binding "${INVOKER_SA}" \
        --project="${PROJECT_ID}" \
        --member="serviceAccount:${RUNTIME_SA}" \
        --role="roles/iam.serviceAccountUser" >/dev/null

    local deployer
    deployer="$(gcloud config get-value account 2>/dev/null)"
    if [[ -n "${deployer}" ]]; then
        gcloud iam service-accounts add-iam-policy-binding "${RUNTIME_SA}" \
            --project="${PROJECT_ID}" \
            --member="user:${deployer}" \
            --role="roles/iam.serviceAccountUser" >/dev/null 2>&1 || true
    fi
    echo "runtime IAM ensured"
}

echo "=== Deploying ${SERVICE} ==="

echo "=== 1/3: Ensure Artifact Registry repo exists ==="
gcloud artifacts repositories describe "${REPO}" \
    --location="${REGION}" --project="${PROJECT_ID}" >/dev/null 2>&1 \
  || gcloud artifacts repositories create "${REPO}" \
        --repository-format=docker \
        --location="${REGION}" \
        --project="${PROJECT_ID}" \
        --description="thegoodguest container images"

echo "=== 2/3: Build container via Cloud Build ==="
echo "Image:   ${IMAGE_URI}"
echo "Config:  ${CLOUDBUILD_CONFIG}"
# Its own upload list: the repo's .gcloudignore leaves out web/, which this
# image is built from (infra/cloudbuild/scene-finish.gcloudignore).
gcloud builds submit . \
    --project="${PROJECT_ID}" \
    --region="${REGION}" \
    --config="${CLOUDBUILD_CONFIG}" \
    --ignore-file="infra/cloudbuild/scene-finish.gcloudignore" \
    --substitutions="_IMAGE_URI=${IMAGE_URI}"

ensure_runtime_iam

echo "=== 3/3: Deploy to Cloud Run (CPU only) ==="
# Platform-gated like perception-obj (0106): only the Cloud Tasks invoker, which
# holds run.invoker (granted below), can call it.
DEPLOY_FLAGS=(--platform=managed --service-account="${RUNTIME_SA}" --no-allow-unauthenticated)
if [[ "${CANDIDATE_MODE}" -eq 1 ]]; then
    if gcloud run services describe "${SERVICE}" \
            --region="${REGION}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
        DEPLOY_FLAGS+=(--no-traffic)
        echo "[deploy] ${SERVICE} exists; new revision held at 0% traffic."
    else
        echo "[deploy] WARNING: ${SERVICE} has no prior revision; --no-traffic cannot be honored."
    fi
    DEPLOY_FLAGS+=(--tag="${CANDIDATE_TAG}")
fi
# concurrency=1: a render holds a Chrome and several GB; parallelism comes from
# more instances (max 12 = one per piece of a typical room), not more requests.
# CPU is billed per request (the default throttling): a still is one request of
# tens of seconds and nothing runs between requests. The Claude layer's design
# wants --no-cpu-throttling (billed through Claude waits); it brings that back.
gcloud run deploy "${SERVICE}" \
    --image="${IMAGE_URI}" \
    --region="${REGION}" \
    --project="${PROJECT_ID}" \
    "${DEPLOY_FLAGS[@]}" \
    --cpu=4 \
    --memory=8Gi \
    --max-instances=12 \
    --min-instances=0 \
    --concurrency=1 \
    --timeout=900 \
    --port=8080 \
    --cpu-boost \
    --startup-probe=httpGet.path=/health,httpGet.port=8080,initialDelaySeconds=2,periodSeconds=3,failureThreshold=10,timeoutSeconds=3 \
    --set-env-vars=ENVIRONMENT=production,PERCEPTION_OUTPUTS_BUCKET=thegoodguest-perception-outputs,CAPTURES_BUCKET=thegoodguest-captures,FIRESTORE_PROJECT="${PROJECT_ID}",RECEIVER_URL="${RECEIVER_URL}",CLOUD_TASKS_INVOKER_SA="${INVOKER_SA}",CLOUD_TASKS_PROJECT="${PROJECT_ID}",CLOUD_TASKS_LOCATION="${REGION}",CLOUD_TASKS_QUEUE=perception-dispatch,GIT_SHA="$(git rev-parse --short HEAD)"
    # --set-env-vars REPLACES the whole list: a variable missing from this line
    # silently does not ship. ENVIRONMENT=production makes a missing
    # RECEIVER_URL or CLOUD_TASKS_INVOKER_SA an error on the first task rather
    # than an unchecked route (task_auth.py).

EFFECTIVE_SA=$(gcloud run services describe "${SERVICE}" \
    --region="${REGION}" --project="${PROJECT_ID}" \
    --format='value(spec.template.spec.serviceAccountName)')
echo "=== Runtime SA on the new revision: ${EFFECTIVE_SA:-<compute default>} ==="
[[ "${EFFECTIVE_SA}" == "${RUNTIME_SA}" ]] || echo "WARNING: expected ${RUNTIME_SA}" >&2

gcloud run services add-iam-policy-binding "${SERVICE}" \
    --region="${REGION}" --project="${PROJECT_ID}" \
    --member="serviceAccount:${INVOKER_SA}" \
    --role="roles/run.invoker" >/dev/null
echo "=== run.invoker ensured for tasks-invoker@ (platform gate) ==="

if [[ "${CANDIDATE_MODE}" -eq 0 ]]; then
    gcloud run services update-traffic "${SERVICE}" --to-latest \
        --region="${REGION}" --project="${PROJECT_ID}"
fi

URL=$(gcloud run services describe "${SERVICE}" \
        --region="${REGION}" --project="${PROJECT_ID}" \
        --format='value(status.url)')
echo ""
echo "=== Done ==="
echo "Service URL: ${URL}"
if [[ "${URL}" != "${RECEIVER_URL}" ]]; then
    echo "WARNING: the service URL is not RECEIVER_URL (${RECEIVER_URL}); every task" >&2
    echo "         would fail its audience check. Fix RECEIVER_URL here and in" >&2
    echo "         deploy_perception.sh (SCENE_FINISH_URL), then redeploy." >&2
fi
if [[ "${CANDIDATE_MODE}" -eq 1 ]]; then
    echo ""
    echo "Smoke the candidate (platform-gated, so it needs an identity token):"
    echo "  curl -H \"Authorization: Bearer \$(gcloud auth print-identity-token)\" <candidate url>/health"
    echo "  CANDIDATE_URL=https://${CANDIDATE_TAG}---${SERVICE}-o4dhc34kqq-as.a.run.app \\"
    echo "    python3 tools/enqueue_still.py <scene_id> --candidate   # a real still, through the queue"
    echo "Then flip traffic:"
    echo "  gcloud run services update-traffic ${SERVICE} --to-latest --region=${REGION} --project=${PROJECT_ID}"
fi
