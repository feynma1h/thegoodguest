# Dockerfile for the roomstudio internal API (services/api-internal/).
#
# Build context is the REPO ROOT so that packages/schemas/ and
# packages/api-core/ are reachable. Cloud Build stages this correctly;
# see infra/cloudbuild/api-internal.yaml.
#
# Usage (from repo root):
#   docker build -f services/api-internal/Dockerfile -t roomstudio-api-internal .
#   docker run -p 8080:8080 -e PORT=8080 roomstudio-api-internal
#
# DEPENDENCY NOTE — protobuf version conflict:
#   thegoodguest-schemas requires protobuf>=7.35.0 (enforced by
#   ValidateProtobufRuntimeVersion in the generated pb2 file).
#   google-cloud-tasks/firestore and thegoodguest-api-core (via proto-plus 1.x)
#   declare protobuf<7.0.0dev. pip resolves to 6.x when any of these are
#   installed in the same resolver pass as the >=7.35.0 constraint.
#   Workaround: install ALL google-cloud-* deps and api-core first (protobuf
#   stays at 6.x), THEN force-reinstall protobuf>=7.35.0 as the final pip
#   step before thegoodguest-schemas. Layer order is load-bearing — do not
#   move api-core after the force-reinstall.
#   See docs/decisions/0005 and 0021 for full context.

FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1

WORKDIR /app

# ── Layer 1: install service deps (pulls proto-plus 1.x → protobuf 6.x) ─────
COPY services/api-internal/pyproject.toml services/api-internal/pyproject.toml
RUN pip install --no-cache-dir \
        fastapi \
        "uvicorn[standard]" \
        google-cloud-storage \
        google-cloud-firestore \
        google-cloud-tasks \
        google-auth \
        firebase-admin

# ── Layer 2: install thegoodguest-api-core ─────────────────────────────────────
# BEFORE the protobuf force-pin — api-core depends on google-cloud-firestore
# which via proto-plus 1.x would downgrade protobuf if installed after the pin.
COPY packages/api-core/ packages/api-core/
RUN pip install --no-cache-dir packages/api-core/

# ── Layer 3: force protobuf>=7.35.0 then install thegoodguest-schemas ──────────
# AFTER all google-cloud-* and api-core installs. Nothing may follow that
# re-resolves the dep tree, or proto-plus will downgrade protobuf back to 6.x.
COPY packages/schemas/ packages/schemas/
RUN pip install --no-cache-dir --no-deps --force-reinstall "protobuf>=7.35.0" \
    && pip install --no-cache-dir packages/schemas/

# ── Layer 4: copy api-internal source ───────────────────────────────────────
COPY services/api-internal/ services/api-internal/

WORKDIR /app/services/api-internal

ENV PORT=8080
CMD uvicorn ingest_server:app --host 0.0.0.0 --port "$PORT"
