#!/usr/bin/env bash
# Deploy a perception service (geom or obj) to Cloud Run.
#
# Run from the repo root:
#     ./infra/deploy_perception.sh geom    # deploy perception-geom (VGGT)
#     ./infra/deploy_perception.sh obj     # deploy perception-obj  (SAM 3 + SAM 3D)
#
# Prerequisites (see infra/secrets.md for details):
#   1. HF token saved as a GCP secret named 'hf-token'
#   2. Cloud Build's runtime SA (compute default) granted Secret Manager Accessor
#   3. Gated access granted on huggingface.co for facebook/sam3 and
#      facebook/sam-3d-objects (only matters for the obj service)
#   4. Cloud Run Admin API, Artifact Registry API, Cloud Build API enabled

set -euo pipefail

if [[ $# -ne 1 || ( "$1" != "geom" && "$1" != "obj" ) ]]; then
    echo "Usage: $0 {geom|obj}"
    exit 1
fi

WHICH="$1"
SERVICE="perception-${WHICH}"
CONTEXT_DIR="services/perception-${WHICH}"
CLOUDBUILD_CONFIG="infra/cloudbuild/perception-${WHICH}.yaml"

PROJECT_ID="roomstudio"
REGION="asia-southeast1"
REPO="roomstudio"
IMAGE_TAG="$(date +%Y%m%d-%H%M%S)"
IMAGE_URI="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO}/${SERVICE}:${IMAGE_TAG}"

# Always run from the repo root regardless of where the script is invoked from
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

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

echo "=== 3/3: Deploy to Cloud Run with L4 GPU ==="
gcloud run deploy "${SERVICE}" \
    --image="${IMAGE_URI}" \
    --region="${REGION}" \
    --project="${PROJECT_ID}" \
    --platform=managed \
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
    --allow-unauthenticated \
    --no-cpu-throttling \
    --cpu-boost \
    --startup-probe=tcpSocket.port=8080,initialDelaySeconds=30,periodSeconds=10,failureThreshold=60,timeoutSeconds=5 \
    --set-env-vars=PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True,PERCEPTION_OUTPUTS_BUCKET=roomstudio-perception-outputs,FIRESTORE_PROJECT=roomstudio,CLOUD_TASKS_INVOKER_SA=tasks-invoker@roomstudio.iam.gserviceaccount.com,RECEIVER_URL=https://perception-obj-q62kcditqa-as.a.run.app

URL=$(gcloud run services describe "${SERVICE}" \
        --region="${REGION}" --project="${PROJECT_ID}" \
        --format='value(status.url)')

echo ""
echo "=== Done ==="
echo "Service URL: ${URL}"
echo ""
if [[ "${WHICH}" == "geom" ]]; then
    echo "Update .env at the repo root:"
    echo "  PERCEPTION_GEOM_URL=${URL}"
else
    echo "Update .env at the repo root:"
    echo "  PERCEPTION_OBJ_URL=${URL}"
fi
