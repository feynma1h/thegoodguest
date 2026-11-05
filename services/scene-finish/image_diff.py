"""Render-equality: how far apart are two renders of the same frame?

The checks that accept or reject a spec compare a render with a photo, and the
same renderer must produce the "before" and the "after". This module measures
the other thing: whether two renders that should be the same are. It is how the
renderer was characterised (run to run, software GL against a GPU) and how a
golden render is pinned in a test.

    python image_diff.py DIR_A DIR_B [--max-mean 0.5]

compares every PNG name the two directories share and prints one line each:
identical, or the mean and 99th-percentile absolute difference per colour
channel (0-255) and the share of pixels differing by more than 8 levels.
Exit 1 if any mean exceeds --max-mean (default: any difference at all).
"""

from __future__ import annotations

import argparse
import io
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

LEVEL = 8  # a pixel "differs" past this many levels in any channel


@dataclass
class Diff:
    name: str
    identical: bool
    mean: float
    p99: float
    over_level: float  # fraction of pixels differing by more than LEVEL

    def line(self) -> str:
        if self.identical:
            return f"{self.name}: identical"
        return f"{self.name}: mean {self.mean:.3f}  p99 {self.p99:.0f}  >{LEVEL}: {self.over_level * 100:.2f}%"


def diff_images(a: bytes | Path, b: bytes | Path, name: str = "") -> Diff:
    def load(x):
        im = Image.open(x if isinstance(x, Path) else io.BytesIO(x))
        return np.asarray(im.convert("RGBA")).astype(int)

    x, y = load(a), load(b)
    if x.shape != y.shape:
        raise ValueError(f"{name}: shapes differ {x.shape} vs {y.shape}")
    d = np.abs(x - y)[..., :3]
    if not d.any():
        return Diff(name, True, 0.0, 0.0, 0.0)
    return Diff(name, False, float(d.mean()), float(np.percentile(d, 99)), float((d.max(-1) > LEVEL).mean()))


def diff_dirs(a: Path, b: Path) -> list[Diff]:
    names = sorted({p.name for p in a.glob("*.png")} & {p.name for p in b.glob("*.png")})
    return [diff_images(a / n, b / n, n) for n in names]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("a", type=Path)
    ap.add_argument("b", type=Path)
    ap.add_argument("--max-mean", type=float, default=0.0)
    args = ap.parse_args()
    diffs = diff_dirs(args.a, args.b)
    if not diffs:
        print("no PNG names in common", file=sys.stderr)
        return 2
    for d in diffs:
        print(d.line())
    return 1 if any(d.mean > args.max_mean for d in diffs) else 0


if __name__ == "__main__":
    sys.exit(main())
