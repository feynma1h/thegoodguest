"""Where a scene's JSON files live, and where its pixels come from.

The layer never touches a bucket directly: it asks a ScenePort. JSON is
addressed relative to the scene (`shell.json`, `boxes.json`, `finish.json`,
`work/furniture/<box>.json`). Pixels (the capture bundle and frames) are
materialised into a job workspace by `materialise`, and are deleted by the
workspace at job end, not by the port.

  LocalScenePort  a folder on disk (tests, the local end-to-end run, re-drive).
                  Reads come from `source`; writes go to `out`, so a read-only
                  scene folder stays read-only.
  GcsScenePort    the outputs bucket under `scenes/<scene_id>/`.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Protocol


def canonical(doc: dict) -> bytes:
    """Deterministic bytes: the same input always writes the same blob."""
    return (json.dumps(doc, indent=1, sort_keys=True) + "\n").encode()


class ScenePort(Protocol):
    scene_id: str

    def read_json(self, rel: str) -> dict | None: ...
    def write_json(self, rel: str, doc: dict) -> None: ...
    def list_json(self, prefix: str) -> list[str]: ...
    def materialise(self, dest: Path) -> None:
        """Put shell.json, boxes.json and captures/{bundle.pb,frames/} under dest."""
        ...


class LocalScenePort:
    def __init__(self, scene_id: str, source: Path, out: Path):
        self.scene_id, self.source, self.out = scene_id, Path(source), Path(out)

    def _read_path(self, rel: str) -> Path | None:
        for root in (self.out, self.source):  # what we wrote shadows the input
            if (root / rel).is_file():
                return root / rel
        return None

    def read_json(self, rel: str) -> dict | None:
        p = self._read_path(rel)
        return json.loads(p.read_text()) if p else None

    def write_json(self, rel: str, doc: dict) -> None:
        p = self.out / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + ".tmp")
        tmp.write_bytes(canonical(doc))
        os.replace(tmp, p)

    def list_json(self, prefix: str) -> list[str]:
        seen = set()
        for root in (self.out, self.source):
            d = root / prefix
            if d.is_dir():
                seen.update(f"{prefix}{p.name}" for p in d.glob("*.json"))
        return sorted(seen)

    def materialise(self, dest: Path) -> None:
        """Link the captures (never copy photos), copy the small JSON."""
        for name in ("shell.json", "boxes.json"):
            p = self._read_path(name)
            if p:
                (dest / name).write_bytes(p.read_bytes())
        cap = self.source / "captures"
        (dest / "captures").symlink_to(cap.resolve(), target_is_directory=True)


class GcsScenePort:
    """`scenes/<scene_id>/...` in the outputs bucket; capture pixels from the captures bucket."""

    def __init__(self, scene_id: str, outputs_bucket, captures_bucket, captures_prefix: str):
        self.scene_id = scene_id
        self._out, self._cap, self._cap_prefix = outputs_bucket, captures_bucket, captures_prefix
        self._prefix = f"scenes/{scene_id}/"

    def read_json(self, rel: str) -> dict | None:
        blob = self._out.blob(self._prefix + rel)
        if not blob.exists():
            return None
        return json.loads(blob.download_as_bytes())

    def write_json(self, rel: str, doc: dict) -> None:
        self._out.blob(self._prefix + rel).upload_from_string(canonical(doc), content_type="application/json")

    def list_json(self, prefix: str) -> list[str]:
        full = self._prefix + prefix
        return sorted(b.name[len(self._prefix):] for b in self._out.client.list_blobs(self._out, prefix=full)
                      if b.name.endswith(".json"))

    def materialise(self, dest: Path) -> None:
        for name in ("shell.json", "boxes.json"):
            doc = self.read_json(name)
            if doc is not None:
                (dest / name).write_bytes(canonical(doc))
        cap = dest / "captures"
        (cap / "frames").mkdir(parents=True)
        for blob in self._cap.client.list_blobs(self._cap, prefix=self._cap_prefix):
            rel = blob.name[len(self._cap_prefix):].lstrip("/")
            if rel == "bundle.pb" or rel.startswith("frames/"):
                blob.download_to_filename(str(cap / rel))
        # The person masks the shell already wrote: scenes/<id>/frames/<idx>/masks.npz.
        (dest / "masks").mkdir()
        for blob in self._out.client.list_blobs(self._out, prefix=self._prefix + "frames/"):
            parts = blob.name.split("/")
            if parts[-1] == "masks.npz" and len(parts) >= 2:
                blob.download_to_filename(str(dest / "masks" / f"{parts[-2]}.npz"))
