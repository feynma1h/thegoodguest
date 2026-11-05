"""The whole chain on one local scene folder, with a FAKE client and the STUB renderer.

    python -m claude_layer.local_run SCENE_DIR OUT_DIR

SCENE_DIR is read, never written (its photos stay where they are: they are linked
into a throw-away workspace, never copied, never uploaded, never logged). OUT_DIR gets
boxes.json, work/ (JSON only), finish.json and furniture.json.

What is fake, so nobody mistakes this for a quality result:
  * the Claude client replays specs already written for this scene (the
    scene's own furniture.json) as if Claude had answered; no API is reachable
    from here;
  * the renderer is the StubRenderer: flat silhouettes, an empty region-id
    pass. The numbers it feeds the gates mean nothing about how a model looks;
  * boxes are derived from the scene's existing furniture.json (the scene predates
    boxes.json);
  * person masks are assumed empty (`assume_no_people`): the scene has none stored.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from . import publish
from .client import FakeClient, Request
from .enqueue import TaskList
from .render import StubRenderer
from .scene_port import LocalScenePort
from .schemas import spec_extent
from .spend import Usage
from .wiring import Deps, register

SKIP = {"window", "door", "curtain-a", "curtain-b"}  # openings and hangings: not boxed pieces here


def boxes_from_furniture(furniture: dict) -> tuple[dict, dict]:
    boxes, specs = [], {}
    for o in furniture["objects"]:
        if o["key"] in SKIP:
            continue
        spec = o["spec"]
        lo, hi = spec_extent(spec)  # the old boxes were RoomPlan's; draw one that holds the whole model
        w, h, d = (2 * max(-lo[0], hi[0]), hi[1], 2 * max(-lo[2], hi[2]))
        x, y, z = o["position"]
        boxes.append({"id": o["key"], "category": o["key"].split("-")[0], "label": spec.get("label", o["key"]),
                      "center": [x, round(y + h / 2, 4), z], "yaw": o["yaw"], "size": [round(float(w), 4), round(float(h), 4), round(float(d), 4)]})
        specs[o["key"]] = spec
    return {"boxes_version": 1, "boxes": boxes}, specs


def answer_from_spec(spec: dict, ids: set[str]) -> dict:
    """A spec file back into the shape Claude's structured answer has."""
    mats = []
    for name, m in spec["materials"].items():
        m = dict(m)
        if "tex" in m:
            tex = dict(m["tex"])
            if "p" in tex:
                tex["p"] = [{"k": k, "v": v} for k, v in tex["p"].items()]
            m["tex"] = tex
        mats.append({"name": name, **m})
    parts = []
    for p in spec["parts"]:
        p = dict(p)
        if p["kind"] == "sphere" and isinstance(p["r"], list):
            p["r3"] = p.pop("r")
        p.setdefault("name", p["kind"])
        p.setdefault("mat", next(iter(spec["materials"])))
        parts.append(p)
    ans = {"label": spec.get("label", ""), "note": spec.get("note", "")[:500], "materials": mats, "parts": parts}
    pl = spec.get("place") or {}
    if pl.get("rule") in ("floor", "wall") or (pl.get("rule") in ("on", "over") and pl.get("target") in ids):
        ans["place"] = {k: v for k, v in pl.items() if k in ("rule", "target")}
    return ans


def fake_client(specs: dict) -> FakeClient:
    ids = set(specs)

    def reply(req: Request) -> dict:
        if req.stage == "finish":
            return {"baseboard": {"present": True}, "evidence": [{"claim": "baseboard", "seen": "a white strip along the floor edge"}]}
        spec = answer_from_spec(specs[req.box_id], ids)
        if req.stage == "spec":
            return spec
        if req.iteration == 1:  # one edit that changes nothing measurable, then done
            spec["note"] = (spec.get("note") or "") + " (re-checked against the views)"
            return {"done": False, "reason": "tidy the note", "spec": spec}
        return {"done": True, "reason": "matches the views as well as these parts can"}

    return FakeClient(reply, usage=Usage(input_tokens=9000, output_tokens=2500))


def main() -> int:
    scene, out = Path(sys.argv[1]), Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    boxes, specs = boxes_from_furniture(json.loads((scene / "furniture.json").read_text()))
    port = LocalScenePort(scene.name, scene, out)
    port.write_json("boxes.json", boxes)
    tasks, client = TaskList(), fake_client(specs)
    deps = Deps(port_for=lambda sid, uri: port, client=client, renderer=StubRenderer(), enqueuer=tasks,
                code_sha="local-run", assume_no_people=True)
    app = FastAPI()
    register(app, deps)
    http = TestClient(app)
    t0 = time.time()
    r = http.post("/finish", json={"scene_id": scene.name, "bundle_uri": "local"})
    print("finish", r.status_code, r.json())
    while tasks.tasks:
        due_now = [t for t in tasks.tasks if t["delay_s"] <= 0] or tasks.tasks[:1]
        t = due_now[0]
        tasks.tasks.remove(t)
        r = http.post(t["path"], json=t["payload"])
        print(t["path"], t["payload"].get("box_id", ""), r.status_code, r.json())
    summary = port.read_json(publish.SUMMARY)
    print(json.dumps({k: summary[k] for k in ("finish", "time_to_look_s", "spend_usd", "deadline_hit", "wrote")}, indent=1))
    print("pieces:", {k: v["status"] for k, v in summary["pieces"].items()})
    print("claude calls (shapes only):", len(client.shapes), "max photo side px:", max(s["max_photo_side"] for s in client.shapes),
          "max photos/request:", max(s["photos"] for s in client.shapes), f"wall {time.time() - t0:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
