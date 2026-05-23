# Dockerfile for the roomstudio bundle ingester (services/api/).
#
# Build context is the REPO ROOT so that packages/schemas/ is reachable.
# Cloud Build stages this correctly; see infra/cloudbuild/api.yaml.
#
# Usage (from repo root):
#   docker build -f services/api/Dockerfile -t roomstudio-api .
#   docker run -p 8080:8080 -e PORT=8080 roomstudio-api
#
# The image installs roomstudio-schemas from packages/schemas/ (non-editable,
# appropriate for containers) then installs services/api/ dependencies from
# its pyproject.toml. No model weights, no GPU required — CPU-only service.

FROM python:3.11-slim

# Keeps Python from buffering stdout/stderr so Cloud Run log streaming works.
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# ── Layer 1: install roomstudio-schemas ─────────────────────────────────────
# Copy only what the schemas package needs to install. Done as a separate
# COPY+RUN before the api source so Docker cache reuses this layer unless the
# proto or schema Python files change.
COPY packages/schemas/ packages/schemas/
RUN pip install --no-cache-dir packages/schemas/

# ── Layer 2: install api dependencies ────────────────────────────────────────
# Copy pyproject.toml first so the dependency install layer is cached
# independently of source changes.
COPY services/api/pyproject.toml services/api/pyproject.toml
RUN pip install --no-cache-dir \
        fastapi \
        "uvicorn[standard]" \
        google-cloud-storage \
        google-cloud-firestore \
        google-cloud-tasks

# ── Layer 3: copy api source ─────────────────────────────────────────────────
COPY services/api/ services/api/

# ── Runtime ──────────────────────────────────────────────────────────────────
WORKDIR /app/services/api

# Cloud Run injects PORT; uvicorn reads it at startup.
# Default to 8080 so local docker run works without -e PORT=....
ENV PORT=8080

CMD uvicorn server:app --host 0.0.0.0 --port "$PORT"
