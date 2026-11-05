"""The one place a Claude request leaves this service.

`ClaudeCaller.ask` is what the passes call. In order, per call it:
  1. enforces the privacy rules on the request's images (decision 0352): the
     finish stage carries atlases only, a photo crop must have been person-masked
     and capped by `images.py`, at most PHOTO_CROPS_PER_REQUEST of them;
  2. checks the scan's spend ceiling for the call's worst case (0353);
  3. sends it through a `ClaudeClient` (the real SDK, or a fake in tests and in
     the local end-to-end run: this repository's tests never reach the API);
  4. records the usage the API reported, and logs one line WITHOUT pixels;
  5. validates the answer with the caller's validator; an invalid answer is
     re-asked once with the validation error appended, then given up on.

A refusal is never retried. Nothing here reads, prints or stores an API key: the
SDK picks `ANTHROPIC_API_KEY` up from the environment of the deployed service.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol, TypeVar

from . import constants as C
from .spend import SpendLedger, Usage

log = logging.getLogger("scene_finish.claude")
T = TypeVar("T")


class ClaudeRefused(Exception):
    """The model declined; the piece or hint is skipped, never retried."""


class ClaudeUnusable(Exception):
    """No valid answer after the allowed re-asks (or the call failed outright)."""


class PrivacyViolation(Exception):
    """A request carried pixels the rules do not allow. Always a bug in a caller."""


@dataclass(frozen=True)
class Image:
    """A picture in a request. `kind` says where its pixels came from."""

    kind: str  # "atlas" (median over frames), "photo" (a person-masked crop), "render" (ours)
    png: bytes
    width: int
    height: int
    label: str = ""
    masked: bool = False  # set only by images.py, after the person mask was applied

    @property
    def est_tokens(self) -> int:
        return self.width * self.height // C.PIXELS_PER_TOKEN


@dataclass
class Request:
    stage: str  # "finish" | "spec" | "critique"
    model: str
    system: str
    content: list[str | Image]
    schema: dict
    max_tokens: int
    scene_id: str = ""
    box_id: str = ""
    iteration: int = 0

    def images(self) -> list[Image]:
        return [c for c in self.content if isinstance(c, Image)]

    def est_input_tokens(self) -> int:
        words = len(self.system) // 3 + sum(len(c) // 3 for c in self.content if isinstance(c, str))
        return words + sum(i.est_tokens for i in self.images())


@dataclass
class Reply:
    data: dict
    usage: Usage
    request_id: str = ""
    latency_ms: int = 0


class ClaudeClient(Protocol):
    def create(self, req: Request) -> Reply: ...


def check_privacy(req: Request) -> None:
    if req.model not in C.ALLOWED_MODELS:
        raise PrivacyViolation(f"model {req.model!r} is not one that may see a room (decision 0360)")
    photos = [i for i in req.images() if i.kind == "photo"]
    if req.stage == "finish" and any(i.kind not in ("atlas", "render") for i in req.images()):
        raise PrivacyViolation("the finish pass may send atlases and our renders only")
    if len(req.images()) > C.FINISH_MAX_IMAGES + C.PHOTO_CROPS_PER_REQUEST * 2:
        raise PrivacyViolation("too many images in one request")
    if len(photos) > C.PHOTO_CROPS_PER_REQUEST:
        raise PrivacyViolation(f"{len(photos)} photo crops in one request, the limit is {C.PHOTO_CROPS_PER_REQUEST}")
    for i in req.images():
        if i.kind not in ("atlas", "photo", "render"):
            raise PrivacyViolation(f"unknown image kind {i.kind!r}")
        if i.kind == "photo" and (not i.masked or max(i.width, i.height) > C.PHOTO_CROP_MAX_SIDE_PX):
            raise PrivacyViolation("a photo crop must be person-masked and at most "
                                   f"{C.PHOTO_CROP_MAX_SIDE_PX}px on its long side")
        if i.kind == "atlas" and max(i.width, i.height) > C.FINISH_IMAGE_MAX_SIDE_PX:
            raise PrivacyViolation("atlas too large")


class ClaudeCaller:
    def __init__(self, client: ClaudeClient, ledger: SpendLedger, scene_id: str = ""):
        self.client, self.ledger, self.scene_id = client, ledger, scene_id
        self.calls = 0

    def ask(self, req: Request, validate: Callable[[dict], T], *, accepted: Callable[[], bool] | None = None) -> T:
        req.scene_id = req.scene_id or self.scene_id
        check_privacy(req)
        last_error = ""
        for attempt in range(1 + C.REASK_ON_INVALID):
            r = req if not last_error else _with_error(req, last_error)
            self.ledger.check(r.model, r.est_input_tokens(), r.max_tokens)  # raises SpendCeilingReached
            t0 = time.monotonic()
            try:
                reply = self.client.create(r)
            except ClaudeRefused:
                _log(r, None, "refused", attempt)
                raise
            except Exception as exc:
                _log(r, None, f"error:{type(exc).__name__}", attempt)
                raise ClaudeUnusable(f"{type(exc).__name__}") from exc
            reply.latency_ms = reply.latency_ms or int((time.monotonic() - t0) * 1000)
            self.calls += 1
            usd = self.ledger.record(r.model, reply.usage, f"{r.stage}:{r.box_id}:{r.iteration}")
            try:
                out = validate(reply.data)
            except ValueError as exc:
                last_error = str(exc)[:1500]
                _log(r, reply, "invalid", attempt, usd)
                continue
            _log(r, reply, "ok", attempt, usd)
            return out
        raise ClaudeUnusable("answer stayed invalid: " + last_error[:200])


def _with_error(req: Request, error: str) -> Request:
    note = ("Your previous answer was rejected by the validator:\n" + error +
            "\nAnswer again, fixing exactly those problems.")
    return Request(req.stage, req.model, req.system, [*req.content, note], req.schema, req.max_tokens,
                   req.scene_id, req.box_id, req.iteration)


def _log(req: Request, reply: Reply | None, outcome: str, attempt: int, usd: float = 0.0) -> None:
    """One structured line per call: sizes and counts only, never a pixel or a prompt."""
    line = {"event": "claude_call", "stage": req.stage, "scene_id": req.scene_id, "box_id": req.box_id,
            "iteration": req.iteration, "model": req.model, "attempt": attempt, "outcome": outcome,
            "images": {k: sum(1 for i in req.images() if i.kind == k) for k in ("atlas", "photo", "render")},
            "usd": round(usd, 4)}
    if reply:
        line.update(input_tokens=reply.usage.input_tokens, output_tokens=reply.usage.output_tokens,
                    cache_read_tokens=reply.usage.cache_read_tokens, latency_ms=reply.latency_ms,
                    request_id=reply.request_id)
    log.info(json.dumps(line, sort_keys=True))


@dataclass
class FakeClient:
    """Scripted answers for tests and the local end-to-end run. Never networks.

    `script` is a list of dicts (one per call, in order) or a function
    Request -> dict. Calls are kept as SHAPES (no pixel bytes) in `shapes`.
    """

    script: list | Callable[[Request], dict]
    usage: Usage = field(default_factory=lambda: Usage(input_tokens=4000, output_tokens=1500))
    shapes: list[dict] = field(default_factory=list)

    def create(self, req: Request) -> Reply:
        self.shapes.append({"stage": req.stage, "box_id": req.box_id, "iteration": req.iteration, "model": req.model,
                            "photos": sum(1 for i in req.images() if i.kind == "photo"),
                            "atlases": sum(1 for i in req.images() if i.kind == "atlas"),
                            "renders": sum(1 for i in req.images() if i.kind == "render"),
                            "max_photo_side": max([max(i.width, i.height) for i in req.images() if i.kind == "photo"], default=0),
                            "text_hash": hashlib.sha256("".join(c for c in req.content if isinstance(c, str)).encode()).hexdigest()[:12]})
        if callable(self.script):
            out: Any = self.script(req)
        else:
            if not self.script:
                raise RuntimeError("FakeClient script exhausted")
            out = self.script.pop(0)
        if isinstance(out, Exception):
            raise out
        return Reply(data=out, usage=self.usage, request_id=f"fake-{len(self.shapes)}")


class AnthropicClient:
    """The real SDK. Not exercised by this repository's tests against the API."""

    def __init__(self, sdk_client: Any = None):
        if sdk_client is None:
            import anthropic  # deferred: tests never import the SDK

            sdk_client = anthropic.Anthropic(timeout=C.CALL_TIMEOUT_S, max_retries=C.SDK_MAX_RETRIES)
        self._sdk = sdk_client

    @staticmethod
    def _blocks(content: list[str | Image]) -> list[dict]:
        out: list[dict] = []
        for c in content:
            if isinstance(c, str):
                out.append({"type": "text", "text": c})
            else:
                out.append({"type": "text", "text": c.label} if c.label else {"type": "text", "text": f"({c.kind})"})
                out.append({"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                                        "data": base64.standard_b64encode(c.png).decode()}})
        return out

    def create(self, req: Request) -> Reply:
        t0 = time.monotonic()
        # Sonnet/Opus 5.5: no `thinking: disabled`, no forced tool_choice; JSON comes from
        # structured outputs. The vocabulary system prompt is the cache breakpoint.
        resp = self._sdk.messages.create(
            model=req.model,
            max_tokens=req.max_tokens,
            system=[{"type": "text", "text": req.system, "cache_control": {"type": "ephemeral"}}],
            output_config={"effort": C.EFFORT, "format": {"type": "json_schema", "schema": req.schema}},
            messages=[{"role": "user", "content": self._blocks(req.content)}],
        )
        if resp.stop_reason == "refusal":
            raise ClaudeRefused("refusal")
        if resp.stop_reason == "max_tokens":
            raise ClaudeUnusable("max_tokens reached before the answer finished")
        text = next(b.text for b in resp.content if b.type == "text")
        u = resp.usage
        usage = Usage(input_tokens=u.input_tokens, output_tokens=u.output_tokens,
                      cache_read_tokens=getattr(u, "cache_read_input_tokens", 0) or 0,
                      cache_write_tokens=getattr(u, "cache_creation_input_tokens", 0) or 0)
        return Reply(json.loads(text), usage, getattr(resp, "_request_id", "") or "", int((time.monotonic() - t0) * 1000))
