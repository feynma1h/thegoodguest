# Server-side orchestration — promotion plan

This service does not exist yet. This file is a marker for the inevitable
promotion of the perception pipeline orchestrator from the local CLI
(`tools/call_perception.py`) into a server-side Cloud Run service.

## Why this exists

When the perception layer was split into `perception-geom` and `perception-obj`
to resolve a torch version conflict, the composition step (placing per-object
splats into VGGT's coordinate frame) moved out of the service layer and into
`tools/call_perception.py`. That's correct *for now*: there is no web
frontend, and the only client is the local CLI.

It is not correct *for production*. A web client cannot run trimesh
composition in the browser. The composition has to live on a server.

## Promotion trigger

Build this service when ANY of the following are true:

- A web frontend exists and needs to call perception
- A non-CLI client needs to call perception (e.g. a background worker, a queue
  consumer, a mobile app backend)
- The composition step grows beyond what's reasonable to keep in a CLI
  (e.g. caching, retries, rate limiting, auth)

## Shape of the orchestrator

- CPU-only Cloud Run service (no GPU; just orchestration + composition)
- Endpoint(s) mirroring the current CLI commands: `/geom`, `/segment`,
  `/objects`, `/scene`
- Fans out to `perception-geom` and `perception-obj` via their internal Cloud
  Run URLs (no authentication between internal services initially; switch to
  ID-token auth before any public traffic)
- Hosts the composition logic currently in
  `tools/call_perception.py::_compose_scene` and `_estimate_placement`. Move,
  don't duplicate.
- Caches perception results by image-content hash. The pipeline is slow and
  pure; caching is high-value.

## Migration steps when the time comes

1. Copy `tools/call_perception.py::_compose_scene` and `_estimate_placement`
   into this service.
2. Build FastAPI routes that call `perception-geom` and `perception-obj` via
   `httpx` or `requests` and run the composition.
3. Update `tools/call_perception.py` to call this orchestrator directly
   instead of the two perception services. Keep the CLI thin; orchestrator
   owns the logic.
4. Add `API_URL` to `.env.example`.
5. Add `./infra/deploy_api.sh` mirroring the perception deploy script.
6. Turn off public access on `perception-geom` and `perception-obj` (their
   `--allow-unauthenticated` flag becomes `--no-allow-unauthenticated`) and
   bind invoker IAM so only the api service can call them.
