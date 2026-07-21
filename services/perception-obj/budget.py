"""Request-budget tracking for the perception receiver.

Why this exists: scene 25a14caf (2026-07-21) proved what happens when the
frame loop has no notion of time. The Cloud Run request was cut at 900 s
while the handler thread kept computing on the always-allocated CPU,
holding the concurrency=1 slot — so every Cloud Tasks retry 504'd
platform-side without reaching the app, the 0011/0012 lease-reclaim
machinery never ran, and when the zombie instance was finally reaped the
scene stayed stranded in `processing` forever. Finishing INSIDE the
request — with a degraded-but-ready scene if necessary — is the invariant
this module makes enforceable.

BudgetTracker answers one question at two granularities: "does the
remaining request budget fit another frame / another object, leaving the
reserve for fusion + manifest upload + Firestore finalization?" Cost
estimates start at conservative priors (from the real capture's observed
~70-130 s/frame, ~20 s/object) and switch to the observed per-run maximum
once real durations exist — a run of cheap frames earns more frames; one
expensive frame immediately tightens the estimate. An underestimate on the
frame level is bounded by the object-level check: the loop stops
mid-frame at worst one object-cost beyond the estimate, which the reserve
absorbs.

deadline is a time.monotonic() value anchored at REQUEST ENTRY in
server.py — before the lazy model load — so a cold start's ~3.5 min load
correctly shrinks what reconstruction may spend. deadline=None disables
all limits (test/local paths that predate the budget).

Consumers: server.py (constructs the deadline), process_receiver.py
(constructs the tracker, checks it in the frame/object loops).
"""
from __future__ import annotations

import math
import os
import time
from collections.abc import Callable

# Seconds held back from the deadline for everything after the frame loop:
# fusion (CPU, ms), manifest upload, Firestore release_ready, FCM. Generous
# on purpose — it also absorbs one object-level estimate overrun.
DEFAULT_RESERVE_S: float = float(os.environ.get("PERCEPTION_BUDGET_RESERVE_S", "60"))

# Pre-observation cost priors, from the 2026-07-21 real capture: frames ran
# ~70-130 s (3-7 objects each), objects ~20 s. Priors sit at the worst end so
# the first admission decision is conservative; observed maxima take over
# after one real measurement.
DEFAULT_FRAME_COST_PRIOR_S: float = float(
    os.environ.get("PERCEPTION_FRAME_COST_PRIOR_S", "130")
)
DEFAULT_OBJECT_COST_PRIOR_S: float = float(
    os.environ.get("PERCEPTION_OBJECT_COST_PRIOR_S", "30")
)


class BudgetTracker:
    """Tracks remaining request budget and admits frames/objects against it."""

    def __init__(
        self,
        deadline: float | None,
        *,
        reserve_s: float = DEFAULT_RESERVE_S,
        frame_cost_prior_s: float = DEFAULT_FRAME_COST_PRIOR_S,
        object_cost_prior_s: float = DEFAULT_OBJECT_COST_PRIOR_S,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._deadline = deadline
        self._reserve_s = float(reserve_s)
        self._frame_prior_s = float(frame_cost_prior_s)
        self._object_prior_s = float(object_cost_prior_s)
        self._clock = clock
        self._max_frame_s: float | None = None
        self._max_object_s: float | None = None

    # -- observations --------------------------------------------------------

    def note_frame(self, seconds: float) -> None:
        """Record one completed frame's duration."""
        s = float(seconds)
        self._max_frame_s = s if self._max_frame_s is None else max(self._max_frame_s, s)

    def note_object(self, seconds: float) -> None:
        """Record one completed object reconstruction's duration."""
        s = float(seconds)
        self._max_object_s = s if self._max_object_s is None else max(self._max_object_s, s)

    # -- estimates ------------------------------------------------------------

    @property
    def frame_estimate_s(self) -> float:
        """Cost assumed for the next frame: observed max, else the prior."""
        return self._max_frame_s if self._max_frame_s is not None else self._frame_prior_s

    @property
    def object_estimate_s(self) -> float:
        """Cost assumed for the next object: observed max, else the prior."""
        return self._max_object_s if self._max_object_s is not None else self._object_prior_s

    # -- admission ------------------------------------------------------------

    def remaining(self) -> float:
        """Seconds until the deadline; +inf when unlimited."""
        if self._deadline is None:
            return math.inf
        return self._deadline - self._clock()

    def can_start_frame(self) -> bool:
        return self.remaining() - self._reserve_s >= self.frame_estimate_s

    def can_start_object(self) -> bool:
        return self.remaining() - self._reserve_s >= self.object_estimate_s

    # -- observability ---------------------------------------------------------

    def snapshot(self) -> dict:
        """One-line-loggable view of the budget state."""
        rem = self.remaining()
        return {
            "remaining_s": round(rem, 1) if math.isfinite(rem) else None,
            "reserve_s": self._reserve_s,
            "frame_estimate_s": round(self.frame_estimate_s, 1),
            "object_estimate_s": round(self.object_estimate_s, 1),
        }
