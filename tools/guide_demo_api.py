"""Run api-public locally on one room with a diorama scene, to check the room guide
end to end with no cloud and no credits (decision 0376).

    python tools/guide_demo_api.py <scene_dir> [--port 8046] [--web-port 3046]
                                   [--llm replay] [--cache <scene_dir>/llm/cache]

<scene_dir> holds the room's scene.json, and solids.json when it has one. Rooms
are never in this repository, so it is a folder under the gitignored outputs/.

This starts api-public's own app, unchanged, with its in-memory stores filled
for one ready room owned by the web's live-local user (`test-uid:dev-user`):
the room's files are served as if from the bucket, its signed links point back
at this server, and the guide answers from the gateway's cache (GUIDE_LLM=
replay), so a conversation recorded live plays again for free. A turn the
cache has no answer for ends with the panel's error note.

Then run the web against it, with the switch turned on locally for the check
(it is never committed on) and the viewer taken from the diorama branch's
worktree. These three variables go in front of `npm --prefix web run dev`:

    DIORAMA_VIEWER_DIR=<diorama worktree>/services/diorama/viewer
    NEXT_PUBLIC_API_MODE=live-local
    NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8046

and open /room?bundle=<the bundle id this prints>. Binds 127.0.0.1 only.

Read by: a developer checking the guide locally (decision 0376's local run).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCENE_ID = "0b5e57a0-9d1c-4c6e-8a3f-376000000376"
BUNDLE_ID = "1f0c2b7e-5a4d-4b8e-9c61-376000000376"
OWNER = "dev-user"


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("scene_dir", type=Path)
    ap.add_argument("--port", type=int, default=8046)
    ap.add_argument("--web-port", type=int, default=3046)
    ap.add_argument("--llm", default="replay", choices=["replay", "live"])
    ap.add_argument("--cache", type=Path, default=None)
    args = ap.parse_args(argv)

    scene_dir = args.scene_dir.resolve()
    if not (scene_dir / "scene.json").is_file():
        sys.exit(f"no scene.json in {scene_dir}")
    cache = (args.cache or scene_dir / "llm" / "cache").resolve()

    # Before api-public is imported: it reads these once.
    os.environ.pop("ENVIRONMENT", None)
    os.environ.pop("FIRESTORE_PROJECT", None)
    os.environ["GUIDE_LLM"] = args.llm
    os.environ["GUIDE_LLM_CACHE"] = str(cache)
    os.environ["CORS_ALLOWED_ORIGINS"] = (
        f"http://localhost:{args.web_port},http://127.0.0.1:{args.web_port}"
    )
    for p in ("services/api-public", "packages/api-core", "packages/schemas", "packages/room-guide"):
        sys.path.insert(0, str(REPO / p))

    import public_server as server
    import uvicorn
    from fastapi import HTTPException
    from fastapi.responses import Response
    from thegoodguest_api_core.scene import Scene, SceneStatus
    from thegoodguest_api_core.scene_read_repo import InMemorySceneReadRepository

    bucket_dir = f"gs://guide-demo/scenes/{SCENE_ID}"
    now = datetime.now(tz=UTC)
    scene = Scene(scene_id=SCENE_ID, device_id="guide-demo", status=SceneStatus.READY,
                  bundle_uri=f"gs://guide-demo/captures/{BUNDLE_ID}/bundle.pb", created_at=now,
                  updated_at=now, bundle_id=BUNDLE_ID, user_id=OWNER,
                  result_uri=f"{bucket_dir}/manifest.json")
    store = {f"{bucket_dir}/manifest.json": json.dumps(
        {"scene_id": SCENE_ID, "manifest_version": 2, "objects": [], "frames": []}).encode()}
    for name in ("scene.json", "solids.json"):
        if (scene_dir / name).is_file():
            store[f"{bucket_dir}/{name}"] = (scene_dir / name).read_bytes()
    fetcher = server.InMemoryManifestFetcher(store)
    base = f"http://127.0.0.1:{args.port}"

    class LocalSigner:
        """Links that point back at this server's /dev-files/ route."""

        def sign(self, gs_uri: str, ttl_seconds: int) -> str:  # noqa: ARG002
            return f"{base}/dev-files/{gs_uri.rsplit('/', 1)[1]}"

    server._scene_read_repo = InMemorySceneReadRepository({SCENE_ID: scene})
    server._manifest_fetcher = fetcher
    server._url_signer = LocalSigner()

    @server.app.get("/dev-files/{name}")
    def dev_file(name: str) -> Response:
        data = fetcher.store.get(f"{bucket_dir}/{name}")
        if data is None or name not in ("scene.json", "solids.json"):
            raise HTTPException(404)
        return Response(data, media_type="application/json", headers={"Cache-Control": "no-store"})

    print(f"guide demo: {scene_dir.name}, guide {args.llm} from {cache}")
    print(f"guide demo: open http://localhost:{args.web_port}/room?bundle={BUNDLE_ID}")
    uvicorn.run(server.app, host="127.0.0.1", port=args.port, log_level="info")


if __name__ == "__main__":
    main()
