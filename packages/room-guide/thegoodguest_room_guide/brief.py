"""THE ROOM: everything the guide knows about one room, in words, and a plan of it.

The brief is the guide's whole world. It carries the room's line, its walls by
the names a person would use, every piece with its id (for tools only: the guide
never says an id) and what it needs, the findings in the analyzer's own words
with the standard each is measured against, the questions worth asking, what the
person has said, and what has changed on screen. Every number in it was worked
out by the room, so the guide can quote it.

The plan is drawn from the model, never from a camera frame: walls, the door's
swing, windows, and each floor piece as a labelled rectangle with a tick on its
front edge.

Read by: guide.py.
"""
from __future__ import annotations

import io

from PIL import Image, ImageDraw, ImageFont

from .analyzer import Finding, room_line, the, wall_name
from .assess import backing_wall
from .gateway import Image as PlanImage
from .model import Arrangement, Room
from .needs import RoomNeeds
from .laws import all_poses


def _needs_words(needs: RoomNeeds, pid: str) -> str:
    entry = needs.pieces.get(pid)
    if entry is None:
        return ""
    bits = []
    for n in entry.needs:
        side = "" if n.need in ("reach", "pass", "light") else f" ({n.side})"
        bits.append(f"{n.need}{side}, {n.strength}: {n.why}")
    for b in entry.bonds:
        bits.append(f"goes {b.how} {b.piece}: {b.why}")
    return "; ".join(bits)


def brief(room: Room, needs: RoomNeeds, arrangement: Arrangement, fs: list[Finding],
          told: list[str], changes: list[str]) -> str:
    poses = all_poses(room, arrangement)
    lines = ["THE ROOM", room_line(room), "", "Walls:"]
    for w in room.walls:
        on = [the(room, p.id) for p in room.pieces.values() if p.wall == w.id and p.support in ("wall", "ceiling")]
        against = [the(room, pid) for pid, p in room.pieces.items()
                   if p.support == "floor" and backing_wall(room, pid, poses[pid]) == w.id]
        bits = []
        if on:
            bits.append("on it: " + ", ".join(on))
        if against:
            bits.append("standing against it: " + ", ".join(against))
        lines.append(f"- {wall_name(room, w.id)} ({w.id}): " + ("; ".join(bits) if bits else "bare"))

    lines += ["", "Pieces (id: name; where; moves; what it needs):"]
    for pid, p in room.pieces.items():
        if p.support == "object":
            where = f"on {the(room, p.on)}"
        elif p.support in ("wall", "ceiling"):
            where = f"on {wall_name(room, p.wall)}" if p.wall else "on the ceiling"
        else:
            w = backing_wall(room, pid, poses[pid])
            where = f"back to {wall_name(room, w)}" if w else "free-standing"
        entry = needs.pieces.get(pid)
        moves = entry.moves if entry else "yes"
        why = f" ({entry.why})" if entry and entry.why else ""
        what = _needs_words(needs, pid)
        lines.append(f"- {pid}: {the(room, pid)}; {where}; moves {moves}{why}" + (f"; {what}" if what else ""))

    problems = [f for f in fs if f.kind in ("problem", "tight", "light")]
    good = [f for f in fs if f.kind == "good"]
    lines += ["", "WHAT THE ROOM SHOWS (worked out by the room; quote these words)"]
    for f in problems:
        std = f" [measured against: {f.standard}]" if f.standard else ""
        lines.append(f"- ({f.kind}, finding {f.key}) {f.text}{std}")
    if not problems:
        lines.append("- Nothing stands in the way of how this room is used.")
    for f in good:
        lines.append(f"- (works) {f.text}")
    other = [f for f in fs if f.kind == "light" and f.key == "pref:open_floor"]
    for f in other:
        if f not in problems:
            lines.append(f"- {f.text}")

    questions = [f for f in fs if f.kind == "question"]
    if questions:
        lines += ["", "WHAT THE SCAN CAN'T KNOW (ask only when the answer would change your advice)"]
        for q in questions:
            lines.append(f"- {q.text} ({q.numbers.get('why', '')})")
    if told:
        lines += ["", "WHAT THE PERSON HAS TOLD YOU"] + [f"- {t}" for t in told]
    lines += ["", "ON THEIR SCREEN NOW"]
    lines += [f"- {c}" for c in changes] if changes else ["- The room as it was scanned."]
    return "\n".join(lines)


def plan_image(room: Room, arrangement: Arrangement, *, px: int = 900) -> PlanImage:
    """A top-down plan of the room as it stands, labelled with each floor piece's name."""
    poses = all_poses(room, arrangement)
    xs, zs = room.footprint[:, 0], room.footprint[:, 1]
    margin = 40
    scale = (px - 2 * margin) / max(xs.max() - xs.min(), zs.max() - zs.min())
    w = int((xs.max() - xs.min()) * scale) + 2 * margin
    h = int((zs.max() - zs.min()) * scale) + 2 * margin

    def to_px(x: float, z: float) -> tuple[float, float]:
        return (margin + (x - xs.min()) * scale, margin + (z - zs.min()) * scale)

    img = Image.new("RGB", (w, h), (249, 242, 236))
    d = ImageDraw.Draw(img)
    font = ImageFont.load_default(size=14)
    small = ImageFont.load_default(size=11)
    d.polygon([to_px(x, z) for x, z in room.footprint], outline=(40, 39, 35), width=5)
    for op in room.openings:
        wall = room.wall(op.wall)
        a, b = to_px(*wall.point(op.u0)), to_px(*wall.point(op.u1))
        if op.kind == "door":
            d.line([a, b], fill=(249, 242, 236), width=7)
            r = op.width * scale
            hinge = a
            d.arc([hinge[0] - r, hinge[1] - r, hinge[0] + r, hinge[1] + r], 0, 360, fill=(190, 180, 170), width=1)
            d.text(((a[0] + b[0]) / 2, (a[1] + b[1]) / 2), "door", fill=(165, 66, 53), font=small, anchor="mm")
        else:
            d.line([a, b], fill=(120, 160, 200), width=7)
            d.text(((a[0] + b[0]) / 2, (a[1] + b[1]) / 2), "window", fill=(60, 90, 130), font=small, anchor="mm")
    for pid, p in room.pieces.items():
        if p.support != "floor" or p.opening:
            continue
        box = p.box(poses[pid])
        corners = [to_px(float(cx), float(cz)) for cx, cz in box.corners()]
        d.polygon(corners, outline=(40, 39, 35), fill=(232, 222, 210), width=2)
        f = box.front
        mid = to_px(box.x + f[0] * box.hz, box.z + f[1] * box.hz)
        tip = to_px(box.x + f[0] * (box.hz + 0.12), box.z + f[1] * (box.hz + 0.12))
        d.line([mid, tip], fill=(165, 66, 53), width=3)
        d.text(to_px(box.x, box.z), the(room, pid)[4:], fill=(40, 39, 35), font=font, anchor="mm")
    for pid, p in room.pieces.items():
        if p.support == "wall" and not p.opening and p.wall:
            box = p.box(poses[pid])
            d.text(to_px(box.x, box.z), "·" + the(room, pid)[4:], fill=(110, 100, 90), font=small, anchor="lm")
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return PlanImage(buf.getvalue(), w, h, "plan")

