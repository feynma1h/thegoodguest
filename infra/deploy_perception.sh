#!/usr/bin/env bash
# Deploy a perception service (geom or obj) to Cloud Run.
#
# Run from the repo root:
#     ./infra/deploy_perception.sh geom              # deploy perception-geom (VGGT)
#     ./infra/deploy_perception.sh obj               # deploy perception-obj, straight to 100%
#     ./infra/deploy_perception.sh obj --candidate   # hold the new revision at 0%, smoke, then flip
#
# --candidate is the same shape deploy_api_public.sh and deploy_api_internal.sh
# use: the revision is created with --no-traffic --tag=candidate, reachable on
# its own tagged URL, and traffic moves only when you run the printed
# update-traffic command. Prefer it for perception-obj — a revision that fails
# at run time burns a full GPU request budget before anyone finds out, and the
# route table (the /shell and /compress stages) is not verifiable locally.
#
# Prerequisites (see infra/secrets.md for details):
#   1. HF token saved as a GCP secret named 'hf-token'
#   2. Cloud Build's runtime SA (compute default) granted Secret Manager Accessor
#   3. Gated access granted on huggingface.co for facebook/sam3 and
#      facebook/sam-3d-objects (only matters for the obj service)
#   4. Cloud Run Admin API, Artifact Registry API, Cloud Build API enabled

set -euo pipefail

if [[ $# -lt 1 || $# -gt 2 || ( "$1" != "geom" && "$1" != "obj" ) ]]; then
    echo "Usage: $0 {geom|obj} [--candidate]"
    exit 1
fi

CANDIDATE_MODE=0
if [[ $# -eq 2 ]]; then
    if [[ "$2" != "--candidate" ]]; then
        echo "Usage: $0 {geom|obj} [--candidate]"
        exit 1
    fi
    CANDIDATE_MODE=1
fi

WHICH="$1"
SERVICE="perception-${WHICH}"
CONTEXT_DIR="services/perception-${WHICH}"
CLOUDBUILD_CONFIG="infra/cloudbuild/perception-${WHICH}.yaml"

PROJECT_ID="roomstudio"
REGION="asia-southeast1"
REPO="roomstudio"

# Dedicated least-privilege runtime SA for perception-obj (decision 0090,
# remediating 0088 finding 1: the service parses UNTRUSTED user bundles and
# ran as the default compute SA, which holds project-level roles/editor).
# Everything it is granted is enumerated in ensure_obj_runtime_iam below —
# that function IS the grant list, and it is idempotent so every deploy
# reasserts it. perception-geom keeps the default SA (parked, no workload).
OBJ_RUNTIME_SA="perception-obj-runtime@${PROJECT_ID}.iam.gserviceaccount.com"
IMAGE_TAG="$(date +%Y%m%d-%H%M%S)"
IMAGE_URI="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO}/${SERVICE}:${IMAGE_TAG}"

# Always run from the repo root regardless of where the script is invoked from
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

# ---------------------------------------------------------------------------
# perception-obj runtime IAM (decision 0090). Every grant the service needs,
# in one place, all idempotent (add-iam-policy-binding no-ops when the binding
# exists). Scoped to the exact resource wherever the API allows it — only
# Firestore, logging, metrics and the FCM send permission are project-level,
# because none of them has a narrower scope.
#
# Runs BEFORE the deploy: --service-account and --set-secrets are both
# validated at revision creation, so an ungranted SA fails the deploy itself
# (observed live 2026-07-23 when the secret grant sat in a post-deploy block).
# ---------------------------------------------------------------------------
ensure_obj_runtime_iam() {
    echo "=== Runtime IAM for ${OBJ_RUNTIME_SA} ==="

    gcloud iam service-accounts describe "${OBJ_RUNTIME_SA}" \
        --project="${PROJECT_ID}" >/dev/null 2>&1 \
      || gcloud iam service-accounts create perception-obj-runtime \
            --project="${PROJECT_ID}" \
            --display-name="perception-obj Cloud Run runtime" \
            --description="Least-privilege runtime SA for perception-obj (decision 0090)"

    # Capture bundles: READ ONLY. The service never writes to captures.
    gcloud storage buckets add-iam-policy-binding "gs://roomstudio-captures" \
        --member="serviceAccount:${OBJ_RUNTIME_SA}" \
        --role="roles/storage.objectViewer" \
        --project="${PROJECT_ID}" >/dev/null

    # Perception outputs: read + write (splats, manifests, masks, shell.json).
    # objectAdmin is the minimal managed role covering create+get+list — the
    # same rationale recorded for api-public's mint grant.
    gcloud storage buckets add-iam-policy-binding "gs://roomstudio-perception-outputs" \
        --member="serviceAccount:${OBJ_RUNTIME_SA}" \
        --role="roles/storage.objectAdmin" \
        --project="${PROJECT_ID}" >/dev/null

    # Firestore 'scenes': claim/release transactions (receiver_repo.py).
    # datastore.user is the narrowest role with transactional read+write; it
    # cannot create or drop indexes or databases.
    gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
        --member="serviceAccount:${OBJ_RUNTIME_SA}" \
        --role="roles/datastore.user" --condition=None >/dev/null

    # Cloud Run runtime baseline. Container stdout is collected by the
    # platform, but any Cloud Logging/Monitoring API call needs these.
    gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
        --member="serviceAccount:${OBJ_RUNTIME_SA}" \
        --role="roles/logging.logWriter" --condition=None >/dev/null
    gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
        --member="serviceAccount:${OBJ_RUNTIME_SA}" \
        --role="roles/monitoring.metricWriter" --condition=None >/dev/null

    # FCM terminal-transition notifications (fcm.py). A CUSTOM role holding
    # exactly cloudmessaging.messages.create: the predefined
    # firebasecloudmessaging.admin would also grant topicSubscriptions.*,
    # which this service never touches.
    gcloud iam roles describe perceptionFcmSender --project="${PROJECT_ID}" \
        >/dev/null 2>&1 \
      || gcloud iam roles create perceptionFcmSender --project="${PROJECT_ID}" \
            --title="perception-obj FCM sender" \
            --description="Send FCM data messages only (decision 0090)." \
            --permissions=cloudmessaging.messages.create --stage=GA >/dev/null
    gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
        --member="serviceAccount:${OBJ_RUNTIME_SA}" \
        --role="projects/${PROJECT_ID}/roles/perceptionFcmSender" \
        --condition=None >/dev/null

    # Anthropic key for shell material inference (decision 0069).
    # SECRET-scoped, not project-scoped — the api-public pattern.
    gcloud secrets add-iam-policy-binding anthropic-api-key \
        --member="serviceAccount:${OBJ_RUNTIME_SA}" \
        --role="roles/secretmanager.secretAccessor" \
        --project="${PROJECT_ID}" --quiet >/dev/null

    # /process enqueues its own second- and third-stage tasks (/shell,
    # decision 0066; /compress, decisions 0125/0126): enqueue rights on the
    # queue and actAs on the Cloud Tasks OIDC invoker SA. Both stages ride
    # the same queue and the same invoker SA — the OIDC AUDIENCE differs per
    # route, which needs no IAM — so these two grants cover both and adding
    # a stage does not add a grant.
    gcloud tasks queues add-iam-policy-binding perception-dispatch \
        --location="${REGION}" --project="${PROJECT_ID}" \
        --member="serviceAccount:${OBJ_RUNTIME_SA}" \
        --role="roles/cloudtasks.enqueuer" >/dev/null
    gcloud iam service-accounts add-iam-policy-binding \
        "tasks-invoker@${PROJECT_ID}.iam.gserviceaccount.com" \
        --project="${PROJECT_ID}" \
        --member="serviceAccount:${OBJ_RUNTIME_SA}" \
        --role="roles/iam.serviceAccountUser" >/dev/null

    # The deployer must be able to act as the runtime SA, or `gcloud run
    # deploy --service-account` is rejected.
    local deployer
    deployer="$(gcloud config get-value account 2>/dev/null)"
    if [[ -n "${deployer}" ]]; then
        gcloud iam service-accounts add-iam-policy-binding "${OBJ_RUNTIME_SA}" \
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
        --description="roomstudio container images"

echo "=== 2/3: Build container via Cloud Build ==="
echo "Image:   ${IMAGE_URI}"
echo "Context: ${CONTEXT_DIR}/"
echo "Config:  ${CLOUDBUILD_CONFIG}"
if [[ "${WHICH}" == "geom" ]]; then
    echo "(First build downloads PyTorch + VGGT weights; expect 15-25 min.)"
else
    echo "(First build downloads PyTorch + SAM 3 + SAM 3D weights; expect 25-40 min.)"
fi

gcloud builds submit . \
    --project="${PROJECT_ID}" \
    --region="${REGION}" \
    --config="${CLOUDBUILD_CONFIG}" \
    --substitutions="_IMAGE_URI=${IMAGE_URI}"

if [[ "${WHICH}" == "obj" ]]; then
    ensure_obj_runtime_iam
fi

echo "=== 3/3: Deploy to Cloud Run with L4 GPU ==="
# perception-obj pins its dedicated runtime SA (0090); geom keeps the default.
# --platform seeds the array so it is never empty: expanding an empty array
# under `set -u` is an unbound-variable error on bash < 4.4, and macOS ships
# 3.2 as /bin/bash.
DEPLOY_FLAGS=(--platform=managed)
if [[ "${WHICH}" == "obj" ]]; then
    DEPLOY_FLAGS+=(--service-account="${OBJ_RUNTIME_SA}")
    # Platform-gated (decision 0106 outcome, flipped 2026-08-10): Cloud
    # Tasks — OIDC as tasks-invoker@, which holds run.invoker on this
    # service (asserted post-deploy below) — is the only caller. An
    # unauthenticated probe now gets the platform 403 and can no longer
    # boot the L4 (the cost vector 0106 measured). App-side OIDC
    # verification stays as defence-in-depth.
    DEPLOY_FLAGS+=(--no-allow-unauthenticated)
else
    # geom is parked (photo path) and has no Cloud Tasks caller; it keeps
    # the app-as-gate posture until it has a workload worth re-deciding.
    DEPLOY_FLAGS+=(--allow-unauthenticated)
fi
# Candidate mode holds the revision at 0% and gives it its own tagged URL.
# --no-traffic is silently ignored on a first-ever service creation, so pass it
# only when there is prior traffic to protect; the tag is useful either way.
if [[ "${CANDIDATE_MODE}" -eq 1 ]]; then
    if gcloud run services describe "${SERVICE}" \
            --region="${REGION}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
        DEPLOY_FLAGS+=(--no-traffic)
        echo "[deploy] ${SERVICE} exists; new revision held at 0% traffic."
    else
        echo "[deploy] WARNING: ${SERVICE} has no prior revision; --no-traffic cannot be honored and the new revision serves 100% on creation."
    fi
    DEPLOY_FLAGS+=(--tag=candidate)
fi
gcloud run deploy "${SERVICE}" \
    --image="${IMAGE_URI}" \
    --region="${REGION}" \
    --project="${PROJECT_ID}" \
    "${DEPLOY_FLAGS[@]}" \
    --gpu=1 \
    --gpu-type=nvidia-l4 \
    --no-gpu-zonal-redundancy \
    --cpu=8 \
    --memory=32Gi \
    --max-instances=1 \
    --min-instances=0 \
    --concurrency=1 \
    --timeout=900 \
    --port=8080 \
    --no-cpu-throttling \
    --cpu-boost \
    --startup-probe=httpGet.path=/health,httpGet.port=8080,initialDelaySeconds=5,periodSeconds=5,failureThreshold=6,timeoutSeconds=3 \
    --set-env-vars=PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True,PERCEPTION_OUTPUTS_BUCKET=roomstudio-perception-outputs,FIRESTORE_PROJECT=roomstudio,CLOUD_TASKS_INVOKER_SA=tasks-invoker@roomstudio.iam.gserviceaccount.com,RECEIVER_URL=https://perception-obj-q62kcditqa-as.a.run.app,CLOUD_TASKS_PROJECT=roomstudio,CLOUD_TASKS_LOCATION=asia-southeast1,CLOUD_TASKS_QUEUE=perception-dispatch,SHELL_WALL_MERGE_GAP_M=1.0,SHELL_WALL_NORMAL_TOL_DEG=15,SHELL_MATERIAL_MODEL=claude-sonnet-5,PERCEPTION_MASK_REFINE=1,PERCEPTION_ARM_SELECT=1 \
    --set-secrets="ANTHROPIC_API_KEY=anthropic-api-key:latest"
    # PERCEPTION_MASK_REFINE and PERCEPTION_ARM_SELECT are ON by operator
    # ruling (2026-08-23). They flip TOGETHER and refine goes first —
    # refinement changes what the chooser is choosing between (0212), so
    # they are one decision, not two switches. --set-env-vars REPLACES the
    # whole list, so a flag absent from this line is a flag that silently
    # does not ship: a deploy that looks like it applied the ruling and
    # did not is worse than one that fails outright.
    #
    # The three flags deliberately NOT here, each with its reason:
    #   PERCEPTION_OBJECT_AWARE_RESIDUE — parked; its job moved into the
    #     cover pass and it belongs to the throughput charter (0202/0212).
    #   PERCEPTION_CONDITIONAL_SECOND_ARM — OFF until the throughput
    #     charter closes; the second arm is currently the OOM fallback in
    #     six of nine affected boxes (0229).
    #   PERCEPTION_VISIBILITY_VETO — BLOCKED, not deferred: its long-tail
    #     regression check needs a GPU and has not run (0234).
    # Their absence is a ruling. Do not 'fix' it by adding them.
    # SHELL_MATERIAL_MODEL is the material-family classifier (decision
    # 0069; shell_material.py). Swapping it changes what families ship —
    # adjudicate on the reference room before widening. The secret mount
    # powers the same call; without it the 0069 fallback rule nulls every
    # family (clean neutral) rather than failing the shell.

# Post-deploy audit line: the runtime SA actually in the served spec.
if [[ "${WHICH}" == "obj" ]]; then
    EFFECTIVE_SA=$(gcloud run services describe "${SERVICE}" \
        --region="${REGION}" --project="${PROJECT_ID}" \
        --format='value(spec.template.spec.serviceAccountName)')
    echo "=== Runtime SA on the new revision: ${EFFECTIVE_SA:-<compute default>} ==="
    if [[ "${EFFECTIVE_SA}" != "${OBJ_RUNTIME_SA}" ]]; then
        echo "WARNING: expected ${OBJ_RUNTIME_SA}" >&2
    fi

    # The platform is the gate (0106 outcome): the Cloud Tasks delivery
    # identity must hold run.invoker on this service or every /process,
    # /shell and /compress dispatch dies at the frontend with 403.
    # Idempotent, and deliberately AFTER the deploy so a first-ever deploy
    # (service doesn't exist yet) works; Cloud Tasks retries cover the
    # seconds between revision-ready and this grant on that one-time path.
    gcloud run services add-iam-policy-binding "${SERVICE}" \
        --region="${REGION}" --project="${PROJECT_ID}" \
        --member="serviceAccount:tasks-invoker@${PROJECT_ID}.iam.gserviceaccount.com" \
        --role="roles/run.invoker" >/dev/null
    echo "=== run.invoker ensured for tasks-invoker@ (platform gate, 0106) ==="
fi

# The registry cleanup policy (infra/artifact-cleanup-policy.json, decision
# 0190) keeps only the three most recent perception-obj images plus whatever
# carries the `serving` or `buildcache` tag. The recency rule alone would drop
# the live image after three builds that never flip — which has happened: two
# of the images in the registry today were built and never deployed. So the
# `serving` tag is what makes the protection structural rather than lucky, and
# it moves with traffic, not with the build. Forgetting to move it over-keeps
# one stale image, which is the safe direction.
move_serving_tag() {
    if [[ "${WHICH}" != "obj" ]]; then
        return 0
    fi
    gcloud artifacts docker tags add \
        "${IMAGE_URI}" \
        "${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO}/${SERVICE}:serving"
}

# gcloud run deploy creates the revision but does NOT move traffic when the
# service's traffic spec is pinned to a revision NAME (perception-obj carried
# such a pin from a 2026-05 rollback: the 2026-07-21 deploy validated, was
# instantly Retired with zero traffic, and gcloud still printed "serving 100
# percent" — for the OLD revision). Force follow-latest explicitly; idempotent,
# and matches the direct mode's intent of deploying straight to 100%. In
# candidate mode the same command is the flip, run by hand after the smoke.
if [[ "${CANDIDATE_MODE}" -eq 0 ]]; then
    gcloud run services update-traffic "${SERVICE}" \
        --to-latest \
        --region="${REGION}" \
        --project="${PROJECT_ID}"
    move_serving_tag
fi

URL=$(gcloud run services describe "${SERVICE}" \
        --region="${REGION}" --project="${PROJECT_ID}" \
        --format='value(status.url)')

echo ""
echo "=== Done ==="
echo "Service URL: ${URL}"
echo ""

if [[ "${CANDIDATE_MODE}" -eq 1 ]]; then
    CANDIDATE_URL=$(gcloud run services describe "${SERVICE}" \
        --region="${REGION}" --project="${PROJECT_ID}" \
        --format='json(status.traffic)' \
        | jq -r '.status.traffic[] | select(.tag == "candidate") | .url // empty')
    if [[ -z "${CANDIDATE_URL}" ]]; then
        echo "ERROR: could not resolve the candidate revision URL from the --tag=candidate traffic entry." >&2
        gcloud run services describe "${SERVICE}" \
            --region="${REGION}" --project="${PROJECT_ID}" \
            --format='yaml(status.traffic)' >&2
        exit 1
    fi
    echo "Candidate URL: ${CANDIDATE_URL}"
    echo ""
    echo "perception-obj is platform-gated (0106), so the smoke needs an identity token:"
    echo "  curl -H \"Authorization: Bearer \$(gcloud auth print-identity-token)\" ${CANDIDATE_URL}/health"
    echo ""
    echo "Then flip traffic:"
    echo "  gcloud run services update-traffic ${SERVICE} --to-latest \\"
    echo "    --region=${REGION} --project=${PROJECT_ID}"
    echo ""
    if [[ "${WHICH}" == "obj" ]]; then
        echo "And move the serving tag, which is what keeps the cleanup policy"
        echo "from reclaiming the live image (decision 0190):"
        echo "  gcloud artifacts docker tags add ${IMAGE_URI} \\"
        echo "    ${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO}/${SERVICE}:serving"
        echo ""
    fi
fi

if [[ "${WHICH}" == "geom" ]]; then
    echo "Update .env at the repo root:"
    echo "  PERCEPTION_GEOM_URL=${URL}"
else
    echo "Update .env at the repo root:"
    echo "  PERCEPTION_OBJ_URL=${URL}"
fi
