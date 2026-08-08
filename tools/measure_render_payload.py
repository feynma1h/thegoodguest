"""Measure what a browser actually fetches to render a room, and how long it takes.

Written for the render-payload P0 (decision 0123): a room took 6-7 minutes to
appear on production and nobody had separated the network term from the
parse term. This is the instrument that separates them, so the next person
does not have to rebuild it.

Read this if you are about to change what the viewer downloads — a splat
format, an LOD scheme, progressive loading, or the number of objects a room
ships. Run it first and after.

What it measures:

  inventory  the RENDERED set, using assembleScene's exact rule
             (web/src/lib/api/types.ts) — placed && world_transform && uri.
             Anything else is signed by api-public but never fetched, and
             counting it overstates the payload.
  network    real bytes from the real bucket over this machine's connection,
             at a configurable concurrency. This is the term that dominates.
  waste      Gaussians the client downloads and then discards: mass outside
             the decision-0104 `splat_clip` volume (already declared false by
             the server) and Gaussians too transparent to show a pixel.

What it deliberately does NOT measure: parse and GPU upload, which need a
real renderer in a real browser. Decision 0123 records those at ~0.6-3 s for
a 276 MB room — under 1% of the wait — measured with a Spark harness. If you
suspect that has changed, measure it in a browser rather than here.

Usage:
  python tools/measure_render_payload.py <scene_prefix>
  python tools/measure_render_payload.py a7e073ae --download --parallel 10
  python tools/measure_render_payload.py a7e073ae --waste --splat-dir ./splats
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

BUCKET = "roomstudio-perception-outputs"


def _storage():
    from google.cloud import storage  # imported late: inventory-only runs still need it

    return storage.Client(project="roomstudio")


def find_scene(client, prefix: str) -> str:
    """Resolve a short scene prefix to exactly one full scene id."""
    it = client.list_blobs(BUCKET, prefix="scenes/", delimiter="/")
    list(it)
    ids = [p.split("/")[1] for p in it.prefixes]
    matches = [i for i in ids if i.startswith(prefix)]
    if len(matches) != 1:
        raise SystemExit(f"scene prefix {prefix!r} matched {matches}")
    return matches[0]


def rendered_set(manifest: dict) -> tuple[list[dict], list[str]]:
    """Split manifest objects into (objects the browser fetches, the rest).

    Mirrors assembleScene exactly. Keeping these two in step matters: the
    gap between "signed" and "fetched" is what made the payload look larger
    than it is (12 of 22 splats on the reference scene are never fetched).
    """
    fetched, skipped = [], []
    for obj in manifest.get("objects", []) or []:
        if obj.get("placed") and obj.get("world_transform") and obj.get("splat_gcs_uri"):
            fetched.append(obj)
        else:
            skipped.append(obj.get("label", "?"))
    return fetched, skipped


def uri_to_blob(uri: str) -> str:
    prefix = f"gs://{BUCKET}/"
    if not uri.startswith(prefix):
        raise ValueError(f"not an outputs-bucket uri: {uri}")
    return uri[len(prefix):]


def local_name(blob: str) -> str:
    """Splat basenames collide across frames (two objects are both
    `00_chair.ply`), so any on-disk copy must be named from the full path."""
    parts = blob.split("/")
    frame = next((parts[i + 1] for i, p in enumerate(parts)
                  if p == "frames" and i + 1 < len(parts)), None)
    return f"f{frame}_{parts[-1]}" if frame else parts[-1]


def download(client, uri: str, out: Path | None) -> dict:
    """Transfer one object, timing first byte and last byte separately."""
    blob = client.bucket(BUCKET).blob(uri_to_blob(uri))
    dest = (out / local_name(uri_to_blob(uri))) if out else None
    t0 = time.perf_counter()
    ttfb, total = None, 0
    fh = dest.open("wb") if dest else None
    try:
        with blob.open("rb", chunk_size=1 << 20) as src:
            while chunk := src.read(1 << 20):
                if ttfb is None:
                    ttfb = time.perf_counter() - t0
                total += len(chunk)
                if fh:
                    fh.write(chunk)
    finally:
        if fh:
            fh.close()
    dt = time.perf_counter() - t0
    return {"name": local_name(uri_to_blob(uri)), "bytes": total,
            "ttfb_s": ttfb, "total_s": dt, "mbps": (total * 8 / 1e6) / dt if dt else 0.0}


def measure_waste(objects: list[dict], splat_dir: Path) -> dict:
    """Fraction of downloaded Gaussians the client discards on arrival."""
    import numpy as np

    # Quaternion math lives in one place (CLAUDE.md); never re-implement it.
    from roomstudio_schemas.pose_math import quat_to_rotmat  # type: ignore

    tot = clipped = faint = 0
    tot_bytes = waste_bytes = 0.0
    rows = []
    for obj in objects:
        blob = uri_to_blob(obj["splat_gcs_uri"])
        path = splat_dir / local_name(blob)
        if not path.exists():
            continue
        xyz, alpha, size = _read_ply(path)
        n = len(xyz)
        n_faint = int((alpha < 0.02).sum())
        n_out = 0
        clip = obj.get("splat_clip")
        if clip and clip.get("kind") == "roomplan_box":
            wt = obj["world_transform"]
            s = wt["scale"]
            s = np.asarray(s if isinstance(s, list) else [s, s, s], float)
            R = quat_to_rotmat(tuple(wt["rotation_xyzw"]))
            world = (xyz * s) @ np.asarray(R).T + np.asarray(wt["position"], float)
            d = world - np.asarray(clip["center_world"], float)
            yaw = -float(clip["yaw_rad"])
            ca, sa = np.cos(yaw), np.sin(yaw)
            local = np.stack([ca * d[:, 0] - sa * d[:, 2], d[:, 1],
                              sa * d[:, 0] + ca * d[:, 2]], 1)
            n_out = int((np.abs(local) > np.asarray(clip["half_extents_m"], float))
                        .any(axis=1).sum())
        tot += n
        clipped += n_out
        faint += n_faint
        tot_bytes += size
        waste_bytes += size * (n_out + n_faint) / n
        rows.append({"name": path.name, "gaussians": n, "outside_clip": n_out,
                     "faint": n_faint})
    return {"gaussians": tot, "outside_clip": clipped, "faint": faint,
            "bytes": tot_bytes, "wasted_bytes": waste_bytes, "rows": rows}


def _read_ply(path: Path):
    """(xyz, alpha, filesize) from a binary little-endian all-float PLY."""
    import numpy as np

    with path.open("rb") as fh:
        header = b""
        while b"end_header" not in header:
            header += fh.readline()
        text = header.decode("ascii", "replace")
        n = int(next(line for line in text.splitlines()
                     if line.startswith("element vertex")).split()[2])
        props = [line.split()[-1] for line in text.splitlines()
                 if line.startswith("property ")]
        data = np.frombuffer(fh.read(n * len(props) * 4), dtype="<f4").reshape(n, len(props))
    idx = {p: i for i, p in enumerate(props)}
    xyz = data[:, [idx["x"], idx["y"], idx["z"]]].astype(np.float64)
    logit = data[:, idx["opacity"]] if "opacity" in idx else np.zeros(n, "f4")
    return xyz, 1.0 / (1.0 + np.exp(-logit)), path.stat().st_size


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("scene", help="scene id or unique prefix")
    ap.add_argument("--download", action="store_true", help="transfer real bytes and time it")
    ap.add_argument("--parallel", type=int, default=6,
                    help="concurrent transfers (a browser uses ~6-10 streams)")
    ap.add_argument("--splat-dir", type=Path, default=None, help="save/read files here")
    ap.add_argument("--waste", action="store_true",
                    help="measure discarded Gaussians (needs --splat-dir with the files)")
    ap.add_argument("--json", type=Path, default=None)
    args = ap.parse_args()

    client = _storage()
    scene_id = find_scene(client, args.scene)
    manifest = json.loads(
        client.bucket(BUCKET).blob(f"scenes/{scene_id}/manifest.json").download_as_bytes()
    )
    fetched, skipped = rendered_set(manifest)

    sizes, signed_only = {}, 0
    for obj in manifest.get("objects", []) or []:
        uri = obj.get("splat_gcs_uri")
        if not uri:
            continue
        b = client.bucket(BUCKET).get_blob(uri_to_blob(uri))
        sizes[uri] = b.size if b else 0
    fetched_bytes = sum(sizes.get(o["splat_gcs_uri"], 0) for o in fetched)
    signed_only = sum(sizes.values()) - fetched_bytes

    print(f"scene {scene_id}")
    print(f"  RENDERED (browser fetches) : {len(fetched)} splats, {fetched_bytes/1e6:.1f} MB")
    print(f"  signed but never fetched   : {len(sizes)-len(fetched)} splats, {signed_only/1e6:.1f} MB")
    for o in sorted(fetched, key=lambda o: -sizes.get(o["splat_gcs_uri"], 0)):
        print(f"      {sizes[o['splat_gcs_uri']]/1e6:8.1f} MB  {o.get('label','?')}")

    result = {"scene_id": scene_id, "fetched": len(fetched),
              "fetched_bytes": fetched_bytes, "signed_only_bytes": signed_only,
              "unrenderable": skipped}

    if args.download:
        if args.splat_dir:
            args.splat_dir.mkdir(parents=True, exist_ok=True)
        uris = [o["splat_gcs_uri"] for o in fetched]
        print(f"\n--- transferring {len(uris)} objects, parallel={args.parallel} ---")
        t0 = time.perf_counter()
        with ThreadPoolExecutor(max_workers=max(1, args.parallel)) as ex:
            rows = list(ex.map(lambda u: download(client, u, args.splat_dir), uris))
        wall = time.perf_counter() - t0
        for r in sorted(rows, key=lambda r: -r["bytes"]):
            print(f"    {r['bytes']/1e6:8.1f} MB  ttfb {r['ttfb_s']*1000:6.0f} ms  "
                  f"{r['total_s']:6.2f} s  {r['mbps']:6.1f} Mbps  {r['name']}")
        agg = sum(r["bytes"] for r in rows)
        print(f"\n  NETWORK: {wall:.2f} s for {agg/1e6:.1f} MB "
              f"= {(agg*8/1e6)/wall:.1f} Mbps aggregate")
        result["network"] = {"parallel": args.parallel, "wall_s": wall,
                             "aggregate_mbps": (agg * 8 / 1e6) / wall, "rows": rows}

    if args.waste:
        if not args.splat_dir:
            raise SystemExit("--waste needs --splat-dir holding the downloaded files")
        w = measure_waste(fetched, args.splat_dir)
        if w["gaussians"]:
            print(f"\n  {w['gaussians']:,} Gaussians at "
                  f"{w['bytes']/w['gaussians']:.1f} B/Gaussian")
            print(f"    outside clip volume  : {w['outside_clip']:,} "
                  f"({100*w['outside_clip']/w['gaussians']:.1f}%)")
            print(f"    effectively invisible: {w['faint']:,} "
                  f"({100*w['faint']/w['gaussians']:.1f}%)")
            print(f"    DOWNLOADED THEN DISCARDED: {w['wasted_bytes']/1e6:.1f} MB "
                  f"({100*w['wasted_bytes']/w['bytes']:.1f}%)")
        result["waste"] = w

    if args.json:
        args.json.write_text(json.dumps(result, indent=2))
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
