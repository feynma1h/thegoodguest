"""Serve ONE local scene directory over HTTP with CORS, read-only, for the
viewer's local-only previews (web/src/app/shell-finish). Real captures stay
outside web/public/; the page fetches shell.json and finish.json from here.

    python tools/serve_scene.py outputs/scene-<id>            # :8765
    python tools/serve_scene.py outputs/scene-<id> --port 9000

Binds 127.0.0.1 only. Serves only the named directory's top-level
`shell.json`, `finish.json`, `furniture.json` (parametric specs, no pixels) and
`poses.json`: nothing else (frames, bundle)
is reachable. It also accepts POST /renders/<name>.png (written to
<scene>/renders/) so the viewer's comparison harness can hand back images.
"""
from __future__ import annotations

import argparse
import functools
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ALLOWED = {"shell.json", "finish.json", "furniture.json", "poses.json"}


class Handler(BaseHTTPRequestHandler):
    def __init__(self, *a, root: Path, **kw):
        self.root = root
        super().__init__(*a, **kw)

    def _send(self, code: int, body: bytes = b"", ctype: str = "text/plain") -> None:
        self.send_response(code)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:  # noqa: N802
        self._send(204)

    def do_GET(self) -> None:  # noqa: N802
        name = self.path.split("?")[0].lstrip("/")
        f = self.root / name
        if name not in ALLOWED or not f.is_file():
            return self._send(404, b"not found")
        self._send(200, f.read_bytes(), "application/json")

    def do_POST(self) -> None:  # noqa: N802
        """Accept a rendered PNG from the viewer's comparison harness:
        POST /renders/<name>.png, written to <scene>/renders/ only."""
        import re

        name = self.path.split("?")[0].lstrip("/")
        if not re.fullmatch(r"renders/[A-Za-z0-9_.-]+\.png", name):
            return self._send(404, b"not found")
        n = int(self.headers.get("Content-Length", "0"))
        if n <= 0 or n > 32_000_000:
            return self._send(400, b"bad size")
        body = self.rfile.read(n)
        if body[:4] == b"data":  # a data: URL straight from canvas.toDataURL
            import base64

            body = base64.b64decode(body.split(b",", 1)[1])
        (self.root / "renders").mkdir(exist_ok=True)
        (self.root / name).write_bytes(body)
        self._send(200, b"ok")

    def log_message(self, *args) -> None:
        pass


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("scene", type=Path)
    ap.add_argument("--port", type=int, default=8765)
    args = ap.parse_args()
    handler = functools.partial(Handler, root=args.scene.resolve())
    print(f"serving {args.scene} on http://127.0.0.1:{args.port}/ (shell.json, finish.json, furniture.json)")
    ThreadingHTTPServer(("127.0.0.1", args.port), handler).serve_forever()


if __name__ == "__main__":
    main()
