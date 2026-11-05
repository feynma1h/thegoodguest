"""Re-drive a scene from its cached pieces, with no pixels and no Claude.

    python -m claude_layer.redrive --scene-dir DIR --out DIR [--piece box_0 ...]
    python -m claude_layer.redrive --bucket NAME --scene-id ID [--piece box_0 ...]

Rebuilds furniture.json (and finish.json) from `work/furniture/<box>.json` and
`work/finish/result.json`: the accepted specs are placed again by the current
placement rules on the current boxes. Use it after the placement code changes,
after a box was edited, or to publish a scene whose deadline publish missed a
piece that finished late. With --piece, only those pieces' objects are replaced
in the published furniture.json (placement is still computed with every cached
spec, so neighbours are respected). Pixels are not needed and not read, so it works
after the capture photos are swept (decision 0086). A piece that never passed has
no spec to re-drive; that needs a new scan.
"""
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

from . import publish
from .scene_port import GcsScenePort, LocalScenePort, ScenePort


def redrive(port: ScenePort, pieces: set[str] | None, code_sha: str) -> dict:
    job = port.read_json(publish.JOB)
    if job is None:
        raise SystemExit("no work/job.json: this scene was never run through scene-finish")
    unknown = (pieces or set()) - set(job["pieces"])
    if unknown:
        raise SystemExit(f"not pieces of this scene: {sorted(unknown)}; they are {job['pieces']}")
    return publish.merge(port, time.time(), code_sha=code_sha, force=True, only=pieces)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scene-dir", type=Path)
    ap.add_argument("--out", type=Path, help="where the local run's work/ and outputs are (default: --scene-dir)")
    ap.add_argument("--bucket")
    ap.add_argument("--scene-id")
    ap.add_argument("--piece", action="append")
    ap.add_argument("--code-sha", default=os.environ.get("GIT_SHA", "redrive"))
    a = ap.parse_args()
    if a.scene_dir:
        port: ScenePort = LocalScenePort(a.scene_id or a.scene_dir.name, a.scene_dir, a.out or a.scene_dir)
    elif a.bucket and a.scene_id:
        from google.cloud import storage

        client = storage.Client()
        port = GcsScenePort(a.scene_id, client.bucket(a.bucket), client)
    else:
        ap.error("give --scene-dir, or --bucket and --scene-id")
    out = redrive(port, set(a.piece) if a.piece else None, a.code_sha)
    print(json.dumps({"wrote": out.get("wrote"), "pieces": {k: v["status"] for k, v in out["summary"]["pieces"].items()}}, indent=1))


if __name__ == "__main__":
    main()
