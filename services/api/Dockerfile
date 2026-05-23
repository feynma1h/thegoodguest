# Dockerfile for the roomstudio bundle ingester (services/api/).
#
# Build context is the REPO ROOT so that packages/schemas/ is reachable.
# Cloud Build stages this correctly; see infra/cloudbuild/api.yaml.
#
# Usage (from repo root):
#   docker build -f services/api/Dockerfile -t roomstudio-api .
#   docker run -p 8080:8080 -e PORT=8080 roomstudio-api
#
# DEPENDENCY NOTE — protobuf version conflict:
#   roomstudio-schemas requires protobuf>=7.35.0 (enforced by
#   ValidateProtobufRuntimeVersion in the generated pb2 file).
#   google-cloud-tasks/firestore (via proto-plus 1.x) declare protobuf<7.0.0dev.
#   These constraints are mutually exclusive in a single pip resolve.
#
#   Workaround: install google-cloud-* first (gets protobuf 6.x), then
#   force-reinstall protobuf>=7.35.0 before installing roomstudio-schemas.
#   proto-plus 1.x uses only core protobuf APIs that are unchanged across
#   the 6→7 boundary, so the google-cloud SDKs work fine at runtime with
#   protobuf 7.x despite declaring otherwise.
#
#   The correct long-term fix is to update pyproject.toml when google-cloud-*
#   packages release versions that natively support proto-plus 2.x / protobuf 7.x.

FROM python:3.11-slim

# Keeps Python from buffering stdout/stderr so Cloud Run log streaming works.
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# ── Layer 1: install google-cloud SDKs and other api dependencies ─────────────
# These are installed first because they (via proto-plus 1.x) pull in
# protobuf 6.x, which we then upgrade in layer 2.
# Copy pyproject.toml so this layer rebuilds if declared deps change.
COPY services/api/pyproject.toml services/api/pyproject.toml
RUN pip install --no-cache-dir \
        fastapi \
        "uvicorn[standard]" \
        google-cloud-storage \
        google-cloud-firestore \
        google-cloud-tasks

# ── Layer 2: install roomstudio-schemas with protobuf>=7.35.0 ────────────────
# Force-reinstall protobuf to >=7.35.0 BEFORE installing roomstudio-schemas
# so that ValidateProtobufRuntimeVersion in capture_bundle_pb2.py succeeds.
# --no-deps prevents pip from trying to re-resolve proto-plus's protobuf
# constraint (which would downgrade again).
COPY packages/schemas/ packages/schemas/
RUN pip install --no-cache-dir --no-deps --force-reinstall "protobuf>=7.35.0" \
    && pip install --no-cache-dir packages/schemas/

# ── Layer 3: copy api source ─────────────────────────────────────────────────
COPY services/api/ services/api/

# ── Runtime ──────────────────────────────────────────────────────────────────
WORKDIR /app/services/api

# Cloud Run injects PORT; uvicorn reads it at startup.
# Default to 8080 so local docker run works without -e PORT=....
ENV PORT=8080

CMD uvicorn server:app --host 0.0.0.0 --port "$PORT"
