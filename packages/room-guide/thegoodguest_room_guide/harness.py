"""The local guide harness: one room, the diorama viewer, a chat panel, and the engine behind them.

Run it with a scene, a work folder and the diorama viewer's folder:

    python -m thegoodguest_room_guide.harness <scene.json> <work_dir> --viewer <viewer_dir> --port 8744

It serves the viewer (read-only, uncached) and the scene, injects the player into
the viewer's page, and keeps the conversation's state for one room: the
arrangement as it stands, every earlier one (so "put it back" is one step), and the
proposals on offer. Every move it sends the viewer is a motion plan that has
already passed motion.verify.

The room's needs come from the rules pass through the gateway (offline by default:
replay, else an oracle request is queued and the room runs on laws only until it
is answered). The first time the page opens, the player measures each piece's
drawn parts and posts them back; the room is then reloaded with real shapes.

Read by: a developer running the guide locally; .claude/launch.json's "guide" entry.
"""


import argparse
import json
from dataclasses import asdict
from pathlib import Path

from .analyzer import room_line, the
from .engine import Engine, Proposal, Refusal
from .gateway import Gateway, OracleNeeded
from .laws import all_poses
from .model import Arrangement, Pose, Room, load_room
from .motion import NoPath, plan, plan_json
from .needs import RoomNeeds, default_needs
from .rules_pass import run_rules_pass

WEB = Path(__file__).resolve().parent / "web"


class Session:
    """One room's state in the harness."""

    def __init__(self, scene: Path, work: Path, mode: str | None = None):
        self.scene = Path(scene)
        self.work = Path(work)
        self.work.mkdir(parents=True, exist_ok=True)
        self.gateway = Gateway(self.work / "llm", mode=mode)
        self.history: list[Arrangement] = [{}]
        self.proposals: dict[str, Proposal] = {}
        self.notes: list[str] = []
        self.load()

    # ------------------------------------------------------------ the room
    @property
    def solids_path(self) -> Path:
        return self.work / "solids.json"

    def load(self) -> None:
        self.room: Room = load_room(self.scene, self.solids_path)
        try:
            self.needs: RoomNeeds = run_rules_pass(self.room, self.gateway)
        except OracleNeeded as e:
            self.needs = default_needs(self.room)
            self.notes.append(f"the rules pass is waiting for an answer in {e.folder}")
        except KeyError:
            self.needs = default_needs(self.room)
            self.notes.append("no cached rules pass for this scene; running on laws only")
        self.engine = Engine(self.room, self.needs, self.arrangement)

    @property
    def arrangement(self) -> Arrangement:
        return self.history[-1]

    def rebuild(self) -> None:
        self.engine = Engine(self.room, self.needs, self.arrangement)

    def take_solids(self, solids: dict) -> dict:
        """Real part shapes from the viewer: kept, and the room reloaded with them."""
        clean = {pid: rows for pid, rows in solids.items() if pid in self.room.pieces and isinstance(rows, list)}
        self.solids_path.write_text(json.dumps(clean))
        self.load()
        return {"pieces": len(clean), "from_builder": sum(p.parts_from == "builder" for p in self.room.pieces.values())}

    # ------------------------------------------------------------ what the panel shows
    def state(self) -> dict:
        fs = self.engine.current_findings
        return {
            "room": room_line(self.room),
            "needs_from": self.needs.origin,
            "needs_solids": not self.solids_path.exists(),
            "notes": self.notes,
            "findings": [{"key": f.key, "kind": f.kind, "severity": f.severity, "text": f.text,
                          "standard": f.standard} for f in fs],
            "poses": {pid: asdict(p) for pid, p in self.arrangement.items()},
            "can_undo": len(self.history) > 1,
            "spend": self.gateway.report(),
        }

    def proposal_json(self, p: Proposal) -> dict:
        return {"id": p.id, "words": p.words, "effort": p.effort, "goal": p.goal,
                "fixes": [f.text for f in p.fixes], "adds": [f.text for f in p.adds],
                "leaves": [f.text for f in p.leaves if f.kind == "problem"],
                "better": round(p.score_after - p.score_before, 2)}

    # ------------------------------------------------------------ moving
    def motion(self, before: Arrangement, after: Arrangement, anchors: list[str]) -> dict:
        b, a = all_poses(self.room, before), all_poses(self.room, after)
        m = plan(self.room, b, a)
        doc = plan_json(m)
        doc["walls"] = {pid: w for pid in doc["tracks"] if (w := self._wall_of(pid, a[pid]))}
        doc["footprints"] = [self._footprint(pid, b[pid]) for pid in anchors]
        doc["methods"] = m.methods
        return doc

    def _wall_of(self, pid: str, pose: Pose) -> str | None:
        piece = self.room.pieces[pid]
        if piece.support != "wall":
            return None
        return min(self.room.walls, key=lambda w: abs(w.offset_of((pose.x, pose.z)) - piece.size[2] / 2)).id

    def _footprint(self, pid: str, pose: Pose) -> dict:
        p = self.room.pieces[pid]
        return {"x": pose.x, "z": pose.z, "hx": p.size[0] / 2, "hz": p.size[2] / 2, "yaw": pose.yaw}

    def offer(self, proposals: list[Proposal]) -> list[dict]:
        """Proposals that can be played: each one's motion is planned and checked first."""
        out = []
        for p in proposals:
            try:
                self.motion(self.arrangement, p.arrangement, p.anchors)
            except NoPath:
                continue
            self.proposals[p.id] = p
            out.append(self.proposal_json(p))
        return out

    def show(self, proposal_id: str) -> dict:
        p = self.proposals[proposal_id]
        doc = self.motion(self.arrangement, p.arrangement, p.anchors)
        self.history.append(dict(p.arrangement))
        self.rebuild()
        return {"plan": doc, "state": self.state()}

    def undo(self) -> dict:
        if len(self.history) < 2:
            return {"plan": None, "state": self.state()}
        now = self.history.pop()
        doc = self.motion(now, self.arrangement, list(set(now) - set(self.arrangement)) or list(now))
        doc["footprints"] = []
        self.rebuild()
        return {"plan": doc, "state": self.state()}


# ---------------------------------------------------------------- the web app

def make_app(session: Session, viewer: Path):
    from fastapi import FastAPI, HTTPException, Request
    from fastapi.responses import FileResponse

    app = FastAPI()
    no_store = {"Cache-Control": "no-store"}

    def file(path: Path, kind: str | None = None):
        if not path.is_file():
            raise HTTPException(404)
        return FileResponse(path, media_type=kind, headers=no_store)

    @app.get("/")
    def index():
        return file(WEB / "harness.html", "text/html")

    @app.get("/guide/{name}")
    def guide_file(name: str):
        return file(WEB / Path(name).name)

    @app.get("/viewer/{rest:path}")
    def viewer_file(rest: str):
        target = (viewer / rest).resolve()
        if viewer.resolve() not in target.parents and target != viewer.resolve():
            raise HTTPException(404)
        return file(target)

    @app.get("/scene.json")
    def scene():
        return file(session.scene, "application/json")

    @app.get("/api/state")
    def state():
        return session.state()

    @app.post("/api/solids")
    async def solids(request: Request):
        return session.take_solids(await request.json())

    @app.post("/api/explore")
    async def explore(request: Request):
        body = await request.json()
        props = session.engine.explore(body.get("goal", "general"))
        return {"proposals": session.offer(props)}

    @app.post("/api/place")
    async def place(request: Request):
        body = await request.json()
        try:
            p = session.engine.place(**body)
        except Refusal as r:
            return {"refused": r.reason, "code": r.code}
        except TypeError as e:
            raise HTTPException(400, str(e))
        offered = session.offer([p])
        if not offered:
            return {"refused": f"there's no clear way to move {the(session.room, body.get('piece', ''))} there",
                    "code": "no_path"}
        return {"proposal": offered[0]}

    @app.post("/api/show")
    async def show(request: Request):
        body = await request.json()
        if body.get("id") not in session.proposals:
            raise HTTPException(404, "no such proposal")
        return session.show(body["id"])

    @app.post("/api/undo")
    def undo():
        return session.undo()

    try:
        from .guide import mount
        mount(app, session)
    except ImportError:
        pass
    return app


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("scene")
    ap.add_argument("work")
    ap.add_argument("--viewer", required=True)
    ap.add_argument("--port", type=int, default=8744)
    ap.add_argument("--llm", default=None, help="gateway mode: live, replay, oracle, stub, auto")
    args = ap.parse_args(argv)
    import uvicorn
    session = Session(Path(args.scene), Path(args.work), args.llm)
    uvicorn.run(make_app(session, Path(args.viewer)), host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
