"""The only way the guide talks to Claude: a request in, an answer out, every one priced.

Two kinds of request share one gateway:
  - `JsonRequest`: one user turn, answered with JSON matching a schema (the rules pass).
  - `TurnRequest`: a conversation turn with tools, answered with content blocks
    (text and tool calls), streamed when live (the guide).

Modes (`GUIDE_LLM`, or the `mode` argument):
  live    send to the Messages API; cache the answer; ledger the measured usage.
  replay  answer from the cache only; a miss is an error. Free.
  oracle  answer from the cache, else write the exact request to
          `<work>/queue/<stage>-<hash>/` and stop with `OracleNeeded`. Whoever
          answers writes `response.json` there; the next call reads it, caches
          it and goes on. Free, and priced as a live call would be.
  stub    a canned answer from the caller, for plumbing tests. Free.
  auto    replay if cached, else live when `GUIDE_LIVE=1`, else oracle.

Only `claude-opus-5-5` and `claude-sonnet-5-5` may see a room (decision 0360),
so the gateway refuses any other model and asks for no server-side fallback,
which could route a room to a model outside that pair. A refusal is reported,
not retried elsewhere.

The cache key hashes everything that shapes the answer: model, effort, prompt
version, system blocks, messages, image bytes, tools and schema.

Read by: rules_pass.py, guide.py, the harness.
"""
from __future__ import annotations

import base64
import hashlib
import json
import math
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

ALLOWED_MODELS = ("claude-opus-5-5", "claude-sonnet-5-5")
DEFAULT_MODEL = "claude-opus-5-5"

# USD per million tokens (claude-api reference, cached 2026-10-06). Cache writes
# are 1.25x input for the 5-minute TTL.
PRICES = {
    "claude-opus-5-5": {"in": 4.00, "out": 20.00, "cache_read": 0.20, "cache_write": 5.00},
    "claude-sonnet-5-5": {"in": 2.00, "out": 10.00, "cache_read": 0.20, "cache_write": 2.50},
}

CHARS_PER_TOKEN = 3.0       # errs high for English and JSON
MAX_LONG_EDGE = 2576
MAX_IMAGE_TOKENS = 4784


class OracleNeeded(RuntimeError):
    def __init__(self, folder: Path):
        super().__init__(f"answer needed: write {folder / 'response.json'} and ask again")
        self.folder = folder


class BudgetExceeded(RuntimeError):
    pass


class ModelNotAllowed(ValueError):
    pass


def text_tokens(text: str) -> int:
    return int(math.ceil(len(text) / CHARS_PER_TOKEN))


def image_tokens(width: int, height: int) -> int:
    s = min(1.0, MAX_LONG_EDGE / max(width, height))
    return int(math.ceil(min(MAX_IMAGE_TOKENS, width * s * height * s / 750.0)))


@dataclass
class Usage:
    input: int = 0
    cache_read: int = 0
    cache_write: int = 0
    output: int = 0
    measured: bool = False

    def cost(self, model: str) -> float:
        p = PRICES[model]
        return (self.input * p["in"] + self.cache_read * p["cache_read"]
                + self.cache_write * p["cache_write"] + self.output * p["out"]) / 1e6


@dataclass
class Image:
    """A PNG to show the model, held as bytes, with its pixel size."""

    png: bytes
    width: int
    height: int
    label: str = ""

    def block(self) -> dict:
        return {"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                            "data": base64.standard_b64encode(self.png).decode()}}


@dataclass
class JsonRequest:
    stage: str
    prompt_version: str
    system: str
    text: str
    schema: dict
    images: list[Image] = field(default_factory=list)
    model: str = DEFAULT_MODEL
    effort: str = "medium"
    max_tokens: int = 32000

    def key(self) -> str:
        h = hashlib.sha256(json.dumps({"kind": "json", "model": self.model, "effort": self.effort,
                                       "v": self.prompt_version, "system": self.system,
                                       "text": self.text, "schema": self.schema},
                                      sort_keys=True).encode())
        for im in self.images:
            h.update(hashlib.sha256(im.png).digest())
        return h.hexdigest()

    def estimate_input(self) -> int:
        return (text_tokens(self.system) + text_tokens(self.text) + text_tokens(json.dumps(self.schema))
                + sum(image_tokens(i.width, i.height) for i in self.images))


@dataclass
class TurnRequest:
    stage: str
    prompt_version: str
    system: list[dict]              # system blocks, cache_control already placed
    messages: list[dict]
    tools: list[dict]
    model: str = DEFAULT_MODEL
    effort: str = "medium"
    max_tokens: int = 16000

    def key(self) -> str:
        return hashlib.sha256(json.dumps({"kind": "turn", "model": self.model, "effort": self.effort,
                                          "v": self.prompt_version, "system": self.system,
                                          "messages": self.messages, "tools": self.tools},
                                         sort_keys=True).encode()).hexdigest()

    def estimate_input(self) -> int:
        return text_tokens(json.dumps({"s": self.system, "m": self.messages, "t": self.tools}))


class Gateway:
    def __init__(self, work: Path, cache_dir: Path | None = None, mode: str | None = None,
                 budget_usd: float | None = None, stub: Callable[[object], object] | None = None):
        self.work = Path(work)
        self.cache_dir = Path(cache_dir) if cache_dir else self.work / "cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.mode = mode or os.environ.get("GUIDE_LLM", "auto")
        self.budget = budget_usd if budget_usd is not None else float(os.environ.get("GUIDE_BUDGET_USD", "1.00"))
        self.stub = stub
        self.ledger = self.work / "ledger.jsonl"
        self.spent = 0.0

    # ------------------------------------------------------------ public
    def ask_json(self, req: JsonRequest) -> dict:
        return self._ask(req, kind="json")

    def ask_turn(self, req: TurnRequest, on_text: Callable[[str], None] | None = None) -> dict:
        """The assistant's answer: {"content": [blocks], "stop_reason": ...}."""
        return self._ask(req, kind="turn", on_text=on_text)

    def report(self) -> dict:
        """Totals from the ledger: calls by mode, and dollars billed and estimated."""
        rows = [json.loads(line) for line in self.ledger.read_text().splitlines()] if self.ledger.exists() else []
        return {"calls": len(rows), "billed_usd": round(sum(r["billed_usd"] for r in rows), 4),
                "priced_usd": round(sum(r["cost_usd"] for r in rows), 4),
                "by_mode": {m: sum(1 for r in rows if r["mode"] == m) for m in {r["mode"] for r in rows}}}

    # ------------------------------------------------------------ core
    def _ask(self, req, kind: str, on_text=None):
        if req.model not in ALLOWED_MODELS:
            raise ModelNotAllowed(f"{req.model} may not see a room; allowed: {', '.join(ALLOWED_MODELS)}")
        key = req.key()
        cached = self._cache_get(key)
        if cached is not None and self.mode != "live":
            self._log(req, key, "replay", Usage(**cached["usage"]), billed=0.0)
            if on_text and kind == "turn":
                for b in cached["response"].get("content", []):
                    if b.get("type") == "text":
                        on_text(b["text"])
            return cached["response"]
        if self.mode == "replay":
            raise KeyError(f"no cached answer for {req.stage} ({key[:12]})")
        if self.mode == "stub":
            if self.stub is None:
                raise RuntimeError("stub mode needs a stub answer")
            data = self.stub(req)
            self._log(req, key, "stub", self._estimate(req, data), billed=0.0)
            return data
        if self.mode == "live" or (self.mode == "auto" and os.environ.get("GUIDE_LIVE") == "1"):
            return self._live(req, key, kind, on_text)
        return self._oracle(req, key, kind, on_text)

    def _estimate(self, req, data) -> Usage:
        return Usage(input=req.estimate_input(), output=text_tokens(json.dumps(data)) * 2)

    def _cache_get(self, key: str) -> dict | None:
        p = self.cache_dir / f"{key}.json"
        return json.loads(p.read_text()) if p.exists() else None

    def _cache_put(self, key: str, req, data, usage: Usage, mode: str) -> None:
        doc = {"stage": req.stage, "model": req.model, "prompt_version": req.prompt_version,
               "mode": mode, "usage": asdict(usage), "response": data}
        (self.cache_dir / f"{key}.json").write_text(json.dumps(doc, indent=1))

    def _log(self, req, key: str, mode: str, u: Usage, billed: float) -> None:
        self.ledger.parent.mkdir(parents=True, exist_ok=True)
        with self.ledger.open("a") as f:
            f.write(json.dumps({"t": round(time.time(), 1), "stage": req.stage, "mode": mode,
                                "model": req.model, "key": key[:16], "usage": asdict(u),
                                "cost_usd": round(u.cost(req.model), 5), "billed_usd": round(billed, 5)}) + "\n")

    # ------------------------------------------------------------ oracle
    def _oracle(self, req, key: str, kind: str, on_text):
        folder = self.work / "queue" / f"{req.stage}-{key[:12]}"
        resp = folder / "response.json"
        if resp.exists():
            data = json.loads(resp.read_text())
            if kind == "turn" and "content" not in data:
                raise ValueError(f"{resp}: a turn answer is {{\"content\": [...]}}")
            u = self._estimate(req, data)
            self._cache_put(key, req, data, u, "oracle")
            self._log(req, key, "oracle", u, billed=0.0)
            if on_text and kind == "turn":
                for b in data["content"]:
                    if b.get("type") == "text":
                        on_text(b["text"])
            return data
        folder.mkdir(parents=True, exist_ok=True)
        if kind == "json":
            lines = ["# System", "", req.system, "", "# User", "", req.text]
            (folder / "schema.json").write_text(json.dumps(req.schema, indent=1))
            for i, im in enumerate(req.images, 1):
                (folder / f"image_{i:02d}_{im.label or 'image'}.png").write_bytes(im.png)
        else:
            lines = ["# System", ""] + [b["text"] for b in req.system] + ["", "# Messages", "",
                                                                         json.dumps(req.messages, indent=1)]
            (folder / "tools.json").write_text(json.dumps(req.tools, indent=1))
        (folder / "request.md").write_text("\n".join(lines))
        (folder / "meta.json").write_text(json.dumps({
            "stage": req.stage, "model": req.model, "effort": req.effort, "key": key,
            "estimated_input_tokens": req.estimate_input(),
            "estimated_input_usd": round(req.estimate_input() * PRICES[req.model]["in"] / 1e6, 4)}, indent=1))
        raise OracleNeeded(folder)

    # ------------------------------------------------------------ live
    def _live(self, req, key: str, kind: str, on_text):
        import anthropic

        est = Usage(input=req.estimate_input(), output=min(req.max_tokens, 6000))
        if self.spent + est.cost(req.model) > self.budget:
            raise BudgetExceeded(f"{req.stage}: about ${est.cost(req.model):.2f} would pass the "
                                 f"${self.budget:.2f} ceiling (spent ${self.spent:.2f})")
        client = anthropic.Anthropic()
        if kind == "json":
            content = [im.block() for im in req.images] + [{"type": "text", "text": req.text}]
            params = dict(model=req.model, max_tokens=req.max_tokens,
                          system=[{"type": "text", "text": req.system, "cache_control": {"type": "ephemeral"}}],
                          messages=[{"role": "user", "content": content}],
                          output_config={"effort": req.effort,
                                         "format": {"type": "json_schema", "schema": req.schema}})
        else:
            params = dict(model=req.model, max_tokens=req.max_tokens, system=req.system,
                          messages=req.messages, tools=req.tools,
                          output_config={"effort": req.effort})
        with client.messages.stream(**params) as stream:
            if on_text is not None:
                for text in stream.text_stream:
                    on_text(text)
            msg = stream.get_final_message()
        if msg.stop_reason == "refusal":
            raise RuntimeError(f"{req.stage}: declined ({getattr(msg, 'stop_details', None)})")
        if msg.stop_reason == "max_tokens":
            raise RuntimeError(f"{req.stage}: cut off at max_tokens={req.max_tokens}")
        mu = msg.usage
        u = Usage(input=mu.input_tokens, cache_read=mu.cache_read_input_tokens or 0,
                  cache_write=mu.cache_creation_input_tokens or 0, output=mu.output_tokens, measured=True)
        if kind == "json":
            data = json.loads(next(b.text for b in msg.content if b.type == "text"))
        else:
            data = {"content": [_block(b) for b in msg.content if b.type in ("text", "tool_use", "thinking")],
                    "stop_reason": msg.stop_reason}
        c = u.cost(req.model)
        self.spent += c
        self._cache_put(key, req, data, u, "live")
        self._log(req, key, "live", u, billed=c)
        return data


def _block(b) -> dict:
    if b.type == "text":
        return {"type": "text", "text": b.text}
    if b.type == "tool_use":
        return {"type": "tool_use", "id": b.id, "name": b.name, "input": b.input}
    return {"type": "thinking", "thinking": getattr(b, "thinking", ""), "signature": getattr(b, "signature", "")}
