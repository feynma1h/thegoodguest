"""The per-scan spend ceiling, checked before every Claude call (decision 0353).

Pieces run as separate tasks, possibly on separate instances, so no single
process holds the running total. Each worker therefore appends to its OWN
ledger file under `work/spend/<worker>.json` (single writer per file) and the
total is the sum of all of them. The check is `spent + worst case of this call
<= ceiling`; concurrent workers can overshoot by at most the calls in flight,
which is the bound the ceiling is documented to have. Cost is computed from the
`usage` the API returns, never from a guess, and an unpriced model is billed as
the dearest one.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass

from . import constants as C
from .scene_port import ScenePort


class SpendCeilingReached(Exception):
    """The scan's Claude budget is used up; end its Claude work, publish what passed."""


@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0


def price_of(model: str) -> tuple[float, float, float]:
    return C.PRICES.get(model, C.UNKNOWN_MODEL_PRICE)


def cost_usd(model: str, u: Usage) -> float:
    pin, pout, pcache = price_of(model)
    return (u.input_tokens * pin + u.output_tokens * pout + u.cache_read_tokens * pcache
            + u.cache_write_tokens * pin * 1.25) / 1e6


def worst_case_usd(model: str, est_input_tokens: int, max_tokens: int) -> float:
    return cost_usd(model, Usage(input_tokens=est_input_tokens, output_tokens=max_tokens))


class SpendLedger:
    """One worker's view: its own calls plus everybody else's recorded total."""

    def __init__(self, port: ScenePort, worker: str, ceiling_usd: float = C.SPEND_CEILING_USD):
        self._port, self.worker, self.ceiling = port, worker, ceiling_usd
        self._path = f"work/spend/{worker}.json"
        self._lock = threading.Lock()
        prev = port.read_json(self._path) or {}
        self._calls: list[dict] = list(prev.get("calls", []))  # a retried task keeps its history

    def others_usd(self) -> float:
        total = 0.0
        for rel in self._port.list_json("work/spend/"):
            if rel != self._path:
                total += sum(c["usd"] for c in (self._port.read_json(rel) or {}).get("calls", []))
        return total

    def own_usd(self) -> float:
        return sum(c["usd"] for c in self._calls)

    def spent_usd(self) -> float:
        return self.others_usd() + self.own_usd()

    def check(self, model: str, est_input_tokens: int, max_tokens: int) -> None:
        need = worst_case_usd(model, est_input_tokens, max_tokens)
        spent = self.spent_usd()
        if spent + need > self.ceiling:
            raise SpendCeilingReached(f"spent ${spent:.2f} + worst case ${need:.2f} > ceiling ${self.ceiling:.2f}")

    def record(self, model: str, usage: Usage, label: str) -> float:
        usd = round(cost_usd(model, usage), 6)
        with self._lock:
            self._calls.append({"label": label, "model": model, "usd": usd, "in": usage.input_tokens,
                                "out": usage.output_tokens, "cache_read": usage.cache_read_tokens})
            self._port.write_json(self._path, {"worker": self.worker, "calls": self._calls})
        return usd
