# Dockerfile for scene-finish (services/scene-finish/): a CPU-only Cloud Run
# service that draws the room viewer in headless Chrome with software GL.
#
# Build context is the REPO ROOT: the viewer is built from web/, and the
# service imports packages/schemas and packages/room-look.
#
#   docker build -f services/scene-finish/Dockerfile -t scene-finish .
#   docker run --rm -p 8080:8080 scene-finish
#
# Three stages:
#   viewer   builds web/ as a static export WITH the finish flag (it is inlined
#            at build time) -- the headless build is the only consumer of the
#            flag; the product build is made elsewhere.
#   render   node deps and the Chromium headless shell (Playwright's own build,
#            pinned by package-lock.json).
#   runtime  node (for the driver) + python (for the service), both in one image
#            because the service starts the driver as a child process.
#
# Plain headless Chrome has no WebGL at all; the driver passes the SwiftShader
# flags that make it work on a CPU (render_driver.mjs, GL_ARGS).

FROM node:22-bookworm-slim AS viewer
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
ENV NEXT_PUBLIC_SHELL_FINISH=1 NEXT_TELEMETRY_DISABLED=1
RUN npx next build

FROM node:22-bookworm-slim AS render
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
WORKDIR /app
COPY services/scene-finish/package.json services/scene-finish/package-lock.json ./
RUN npm ci --omit=dev \
    && npx playwright-core install --with-deps chromium-headless-shell \
    && rm -rf /var/lib/apt/lists/*

FROM render AS runtime
ENV PYTHONUNBUFFERED=1 \
    VIEWER_DIR=/app/web-out \
    RENDER_GL=swiftshader \
    RENDER_CONTAINER=1 \
    PORT=8080
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-venv \
    && rm -rf /var/lib/apt/lists/* \
    && python3 -m venv /venv
ENV PATH=/venv/bin:$PATH

# Python deps. Local packages last: thegoodguest-schemas pins protobuf>=7.35
# (see services/api-public/Dockerfile for the layer-order trap); nothing here
# pulls an older protobuf, but keep them after the service deps anyway.
COPY services/scene-finish/pyproject.toml services/scene-finish/pyproject.toml
RUN pip install --no-cache-dir fastapi "uvicorn[standard]" numpy pillow
COPY packages/schemas/ packages/schemas/
COPY packages/room-look/ packages/room-look/
RUN pip install --no-cache-dir packages/schemas/ packages/room-look/

COPY --from=viewer /web/out /app/web-out
COPY services/scene-finish/*.py services/scene-finish/render_driver.mjs ./

# Chromium needs a home it can write to; Cloud Run's filesystem is in-memory.
ENV HOME=/tmp
CMD uvicorn finish_server:app --host 0.0.0.0 --port "$PORT"
