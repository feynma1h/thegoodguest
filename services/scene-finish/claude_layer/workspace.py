"""The throw-away folder a job's pixels live in (decision 0352).

Everything derived from pixels (the materialised captures, crops, renders,
atlases) exists only inside a Workspace. Leaving the `with` block deletes the
folder however the job ended: published, finally failed, deadline, or an
exception. Links to a read-only source (the local run) are removed as links;
the source's files are never followed or touched.

Person masks come from `masks/<frame:04d>.npz` (key `suppressed`, the union of
SAM 3's person masks, the same file the shell uses). A frame with no readable
mask is NOT usable evidence: the layer fails closed, so a crop is never sent
unless it was checked against a mask. The local end-to-end run is the one
caller that opts out, explicitly, because it only ever talks to a fake client.
"""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import numpy as np

from .scene_port import ScenePort


class Workspace:
    def __init__(self, port: ScenePort, *, assume_no_people: bool = False, base: Path | None = None):
        self.port = port
        self.assume_no_people = assume_no_people  # local fake-client runs only
        self.root = Path(tempfile.mkdtemp(prefix="scene-finish-", dir=base))
        try:
            port.materialise(self.root)
        except BaseException:
            self.close()
            raise

    def __enter__(self) -> Path:
        return self.root

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def person_mask(self, frame_index: int) -> np.ndarray | None:
        """True where a person is; None when unknown (the frame is then unusable)."""
        p = self.root / "masks" / f"{frame_index:04d}.npz"
        if p.is_file():
            try:
                with np.load(p) as npz:
                    arr = np.asarray(npz["suppressed"], dtype=bool)
                if arr.ndim == 2 and arr.size:
                    return arr
            except Exception:
                return None
            return None
        return np.zeros((1, 1), bool) if self.assume_no_people else None
