"""RoomPlan co-run spike — CapturedRoom geometric adjudication (throwaway).

Reads a pulled run directory (captured_room_built.json + plane_anchors.json)
and answers Q4/Q5 quantitatively:
  - wall table: dims, height uniformity, position, yaw, and whether each wall
    lies ON the raw-anchor envelope (architecture) or interior (furniture-plane
    admission — the adjudication's #2 defect class);
  - floor polygon: area + oriented extent vs the operator-confirmed
    4.20 x 3.29 m anchor-envelope floor plan;
  - object table for the operator walk: category/attributes, dims, pos, yaw,
    yaw family relative to the wall axes;
  - top-down SVG floorplan for the operator to eyeball.

Run: python3 analyze_room.py <run_dir>
Read by: the board-7 design session (via the spike decision note).
"""

import json
import math
import sys
from pathlib import Path

run_dir = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
room = json.load(open(run_dir / "captured_room_built.json"))
anchors = json.load(open(run_dir / "plane_anchors.json"))


def cols(m):
    """Column-major flat16 -> (X, Y, Z, T) 3-vectors."""
    return (m[0:3], m[4:7], m[8:11], m[12:15])


def yaw_of(v):
    """Heading (deg) of a world vector projected on XZ."""
    return math.degrees(math.atan2(-v[2], v[0]))


def apply(m, p):
    X, Y, Z, T = cols(m)
    return [
        X[0] * p[0] + Y[0] * p[1] + Z[0] * p[2] + T[0],
        X[1] * p[0] + Y[1] * p[1] + Z[1] * p[2] + T[1],
        X[2] * p[0] + Y[2] * p[1] + Z[2] * p[2] + T[2],
    ]


def cat_name(c):
    if isinstance(c, dict) and c:
        k = next(iter(c.keys()))
        sub = c[k]
        if isinstance(sub, dict) and sub:
            return f"{k}({next(iter(sub.keys()))})" if not isinstance(next(iter(sub.values()), None), dict) else k
        return k
    return str(c)


def conf_name(c):
    return next(iter(c.keys())) if isinstance(c, dict) else str(c)


# ---------------------------------------------------------------- walls
print("=== WALLS (built) ===")
walls = room["walls"]
wall_rows = []
for i, w in enumerate(walls):
    X, Y, Z, T = cols(w["transform"])
    d = w["dimensions"]
    wall_rows.append({
        "i": i, "w": d[0], "h": d[1], "pos": T,
        "yaw": yaw_of(X), "nyaw": yaw_of(Z),
        "conf": conf_name(w["confidence"]),
        "curve": w.get("curve") is not None,
        "corners": len(w.get("polygonCorners", [])),
        "parent": w.get("parentIdentifier"),
    })
    print(f"wall_{i:02d}  {d[0]:5.2f} x {d[1]:4.2f} m  pos=({T[0]:6.2f},{T[1]:5.2f},{T[2]:6.2f})  "
          f"yaw={yaw_of(X):7.1f}  n_yaw={yaw_of(Z):7.1f}  conf={conf_name(w['confidence']):6s}  "
          f"corners={len(w.get('polygonCorners', []))}")

heights = sorted(set(round(r["h"], 2) for r in wall_rows))
print(f"wall heights: {heights}")

# ---------------------------------------------------------------- floor
print()
print("=== FLOOR ===")
floor = room["floors"][0]
fd = floor["dimensions"]
fc = floor.get("polygonCorners", [])
world_corners = [apply(floor["transform"], p) for p in fc]
xs = [p[0] for p in world_corners]
zs = [p[2] for p in world_corners]
ys = [p[1] for p in world_corners]
print(f"dims field: {fd[0]:.2f} x {fd[1]:.2f}   corners={len(fc)}")
print(f"world corner Y range: {min(ys):.3f}..{max(ys):.3f} (flat => corners are local, transform applied)")
print(f"axis-aligned XZ extent: {max(xs)-min(xs):.2f} x {max(zs)-min(zs):.2f}")


def shoelace(pts):
    n = len(pts)
    s = 0.0
    for i in range(n):
        x1, z1 = pts[i]
        x2, z2 = pts[(i + 1) % n]
        s += x1 * z2 - x2 * z1
    return abs(s) / 2


poly_xz = [(p[0], p[2]) for p in world_corners]
print(f"floor polygon area: {shoelace(poly_xz):.2f} m^2   (reference room ~13.8 m^2 = 4.20 x 3.29)")

# Oriented extent along the dominant wall axis.
dom = max(wall_rows, key=lambda r: r["w"])
ang = math.radians(dom["yaw"])
ca, sa = math.cos(ang), math.sin(ang)
us = [x * ca - z * sa for (x, z) in poly_xz]
vs = [x * sa + z * ca for (x, z) in poly_xz]
print(f"oriented extent (along wall_{dom['i']:02d} axis): {max(us)-min(us):.2f} x {max(vs)-min(vs):.2f}")

# ---------------------------------------------------------------- anchors envelope
print()
print("=== RAW ANCHOR ENVELOPE (same session) ===")
verts = [a for a in anchors["plane_anchors"] if a["alignment"] == "vertical"]
print(f"vertical anchors: {len(verts)}  (total {len(anchors['plane_anchors'])}, mesh {anchors['mesh_anchor_count']})")
fams = {}
for a in verts:
    X, Y, Z, T = cols(a["transform"])
    center_w = apply(a["transform"], a["center"])
    ny = yaw_of(Y) % 180.0  # plane anchor local Y is the normal for vertical planes? verify below
    a["_center_w"] = center_w
    a["_area"] = a["extent_w"] * a["extent_h"]

# ARPlaneAnchor: local X x Z spans the plane, Y is normal. For vertical planes the
# normal is horizontal -> family by normal heading mod 180.
big = [a for a in verts if a["_area"] >= 1.0]
for a in big:
    X, Y, Z, T = cols(a["transform"])
    ny = yaw_of(Y) % 180.0
    key = round(ny / 10) * 10 % 180
    fams.setdefault(key, []).append(a)
print("large (>=1 m^2) vertical anchors by normal-heading family:")
for k in sorted(fams):
    rows = fams[k]
    print(f"  family {k:3d}deg: {len(rows)} anchors, areas {[round(a['_area'],1) for a in rows]}")
    for a in rows:
        X, Y, Z, T = cols(a["transform"])
        n = (Y[0], Y[2])
        c = a["_center_w"]
        off = c[0] * n[0] + c[2] * n[1]
        print(f"    {a['id']}  {a['extent_w']:.2f}x{a['extent_h']:.2f}  cls={a['classification']:<12s} plane-offset {off:6.2f}")

# ---------------------------------------------------------------- wall vs envelope
print()
print("=== WALL <-> ANCHOR-PLANE ASSOCIATION ===")
for r in wall_rows:
    best = None
    for a in verts:
        if a["_area"] < 0.5:
            continue
        X, Y, Z, T = cols(a["transform"])
        n = (Y[0], Y[1], Y[2])
        c = a["_center_w"]
        dist = abs((r["pos"][0] - c[0]) * n[0] + (r["pos"][1] - c[1]) * n[1] + (r["pos"][2] - c[2]) * n[2])
        angdiff = abs(((yaw_of(n) - r["nyaw"]) + 90) % 180 - 90)
        if angdiff < 15:
            if best is None or dist < best[0]:
                best = (dist, a)
    if best:
        print(f"wall_{r['i']:02d} ({r['w']:.2f}x{r['h']:.2f}) -> anchor {best[1]['id']} cls={best[1]['classification']:<12s} plane-dist {best[0]:.2f} m")
    else:
        print(f"wall_{r['i']:02d} ({r['w']:.2f}x{r['h']:.2f}) -> NO parallel anchor")

# ---------------------------------------------------------------- objects
print()
print("=== OBJECTS (walk table) ===")
objs = room["objects"]
rows = []
for i, o in enumerate(objs):
    X, Y, Z, T = cols(o["transform"])
    d = o["dimensions"]
    att = o.get("attributes") or {}
    att_s = ",".join(f"{k}={v}" for k, v in att.items()) if isinstance(att, dict) else str(att)
    upright = abs(Y[1] - 1.0) < 1e-3
    rows.append((i, o, T, d))
    print(f"obj_{i}  {cat_name(o['category']):<14s} {att_s:<22s} {d[0]:.2f}x{d[1]:.2f}x{d[2]:.2f}  "
          f"pos=({T[0]:6.2f},{T[1]:5.2f},{T[2]:6.2f})  yaw={yaw_of(X):7.1f}  upright={upright}  conf={conf_name(o['confidence'])}")

# Yaw families relative to dominant wall.
print()
wall_yaw = dom["yaw"] % 90
print(f"dominant wall yaw mod 90: {wall_yaw:.1f}")
for i, o, T, d in rows:
    rel = (yaw_of(cols(o["transform"])[0]) - dom["yaw"]) % 90
    rel = min(rel, 90 - rel)
    print(f"obj_{i} {cat_name(o['category']):<14s} off-wall-axis by {rel:5.1f} deg")

# ---------------------------------------------------------------- doors/windows/openings
print()
print("=== DOORS / WINDOWS / OPENINGS ===")
for kind in ("doors", "windows", "openings"):
    for i, s in enumerate(room[kind]):
        X, Y, Z, T = cols(s["transform"])
        d = s["dimensions"]
        print(f"{kind[:-1]}_{i}  {d[0]:.2f}x{d[1]:.2f}  pos=({T[0]:6.2f},{T[1]:5.2f},{T[2]:6.2f})  parent={str(s.get('parentIdentifier'))[:8]}")

# ---------------------------------------------------------------- SVG floorplan
svg = []
allx = xs + [r["pos"][0] for r in wall_rows]
allz = zs + [r["pos"][2] for r in wall_rows]
minx, maxx = min(allx) - 0.5, max(allx) + 0.5
minz, maxz = min(allz) - 0.5, max(allz) + 0.5
S = 120


def sx(x):
    return (x - minx) * S


def sz(z):
    return (z - minz) * S


W, H = sx(maxx), sz(maxz)
svg.append(f'<svg xmlns="http://www.w3.org/2000/svg" width="{W:.0f}" height="{H:.0f}" viewBox="0 0 {W:.0f} {H:.0f}">')
svg.append(f'<rect width="{W:.0f}" height="{H:.0f}" fill="#faf7f0"/>')
pts = " ".join(f"{sx(x):.1f},{sz(z):.1f}" for x, z in poly_xz)
svg.append(f'<polygon points="{pts}" fill="#e8e2d2" stroke="#b0a890" stroke-width="2"/>')
for r in wall_rows:
    ang = math.radians(r["yaw"])
    dx, dz = math.cos(ang) * r["w"] / 2, -math.sin(ang) * r["w"] / 2
    x0, z0 = r["pos"][0] - dx, r["pos"][2] - dz
    x1, z1 = r["pos"][0] + dx, r["pos"][2] + dz
    svg.append(f'<line x1="{sx(x0):.1f}" y1="{sz(z0):.1f}" x2="{sx(x1):.1f}" y2="{sz(z1):.1f}" stroke="#5a4632" stroke-width="4"/>')
    svg.append(f'<text x="{sx(r["pos"][0]):.1f}" y="{sz(r["pos"][2]):.1f}" font-size="11" fill="#5a4632">w{r["i"]}</text>')
for kind, color in (("doors", "#c05f2e"), ("windows", "#3e7cb1"), ("openings", "#888888")):
    for s in room[kind]:
        X, Y, Z, T = cols(s["transform"])
        ang = math.radians(yaw_of(X))
        d = s["dimensions"]
        dx, dz = math.cos(ang) * d[0] / 2, -math.sin(ang) * d[0] / 2
        svg.append(f'<line x1="{sx(T[0]-dx):.1f}" y1="{sz(T[2]-dz):.1f}" x2="{sx(T[0]+dx):.1f}" y2="{sz(T[2]+dz):.1f}" stroke="{color}" stroke-width="7" opacity="0.8"/>')
for i, o, T, d in rows:
    ang = math.radians(yaw_of(cols(o["transform"])[0]))
    ca, sa2 = math.cos(ang), math.sin(ang)
    hw, hd = d[0] / 2, d[2] / 2
    corners = [(-hw, -hd), (hw, -hd), (hw, hd), (-hw, hd)]
    wpts = []
    for (u, v) in corners:
        x = T[0] + u * ca + v * sa2
        z = T[2] + (-u * sa2 + v * ca)
        wpts.append(f"{sx(x):.1f},{sz(z):.1f}")
    svg.append(f'<polygon points="{" ".join(wpts)}" fill="#c9a86a" fill-opacity="0.55" stroke="#7a5f36" stroke-width="1.5"/>')
    # facing arrow: local +Z
    fz = (T[0] + hd * sa2, T[2] + hd * ca)
    svg.append(f'<line x1="{sx(T[0]):.1f}" y1="{sz(T[2]):.1f}" x2="{sx(fz[0]):.1f}" y2="{sz(fz[1]):.1f}" stroke="#7a5f36" stroke-width="2"/>')
    svg.append(f'<text x="{sx(T[0]):.1f}" y="{sz(T[2]):.1f}" font-size="12" font-weight="bold" fill="#3a2c14">o{i}:{cat_name(o["category"])[:7]}</text>')
svg.append("</svg>")
out = run_dir / "floorplan.svg"
out.write_text("\n".join(svg))
print(f"\nSVG floorplan -> {out}")
