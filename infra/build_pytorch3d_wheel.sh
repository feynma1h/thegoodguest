#!/usr/bin/env bash
# One-time build of the pytorch3d wheel pinned by SAM 3D.
# Caches the result in GCS. Re-run only when SAM 3D bumps its pytorch3d pin.
#
# Run from the repo root:
#     ./infra/build_pytorch3d_wheel.sh

set -euo pipefail

PROJECT_ID="thegoodguest"
REGION="asia-southeast1"
CONFIG="infra/cloudbuild/pytorch3d-wheel.yaml"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

echo "=== Building pytorch3d wheel (one-time, ~45-75 min) ==="
echo "Source repo: facebookresearch/pytorch3d @ 75ebeeae"
echo "Target:      gs://thegoodguest-build-cache/wheels/"
echo ""

gcloud builds submit \
    --no-source \
    --project="${PROJECT_ID}" \
    --region="${REGION}" \
    --config="${CONFIG}"

echo ""
echo "=== Done ==="
echo "Verify the wheel made it to GCS:"
echo "  gsutil ls gs://thegoodguest-build-cache/wheels/"