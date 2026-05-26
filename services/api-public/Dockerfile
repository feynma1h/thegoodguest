# Dockerfile for the roomstudio public API (services/api-public/).
#
# Build context is the REPO ROOT so that packages/schemas/ and
# packages/api-core/ are reachable. Cloud Build stages this correctly;
# see infra/cloudbuild/api-public.yaml.
#
# Usage (from repo root):
#   docker build -f services/api-public/Dockerfile -t roomstudio-api-public .
#   docker run -p 8080:8080 -e PORT=8080 roomstudio-api-public
#
# DEPENDENCY NOTE — protobuf version conflict:
#   roomstudio-schemas requires protobuf>=7.35.0 (enforced by
#   ValidateProtobufRuntimeVersion in the generated pb2 file).
#   firebase-admin (via proto-plus 1.x) declares protobuf<7.0.0dev.
#   Workaround: install firebase-admin first (gets protobuf 6.x), then
#   force-reinstall protobuf>=7.35.0 before installing roomstudio-schemas.
#   See services/api-internal/Dockerfile for the same note.

FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1

WORKDIR /app

# ── Layer 1: install service deps (pulls proto-plus 1.x → protobuf 6.x) ─────
COPY services/api-public/pyproject.toml services/api-public/pyproject.toml
RUN pip install --no-cache-dir \
        fastapi \
        "uvicorn[standard]" \
        firebase-admin

# ── Layer 2: force protobuf>=7.35.0 then install roomstudio-schemas ──────────
COPY packages/schemas/ packages/schemas/
RUN pip install --no-cache-dir --no-deps --force-reinstall "protobuf>=7.35.0" \
    && pip install --no-cache-dir packages/schemas/

# ── Layer 3: install roomstudio-api-core ────────────────────────────────────
COPY packages/api-core/ packages/api-core/
RUN pip install --no-cache-dir packages/api-core/

# ── Layer 4: copy api-public source ─────────────────────────────────────────
COPY services/api-public/ services/api-public/

WORKDIR /app/services/api-public

ENV PORT=8080
CMD uvicorn server:app --host 0.0.0.0 --port "$PORT"
