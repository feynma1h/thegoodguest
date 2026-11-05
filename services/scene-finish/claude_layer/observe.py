"""Observability without pixels (decision 0358).

Every stage and every outcome is one structured JSON log line on the
`scene_finish.events` logger (Cloud Run turns it into a log entry; log-based
metrics and alerts are defined over these fields). A line carries ids, counts,
seconds and dollars. It never carries a prompt, an image, a path inside the
workspace or an API key.

Events: finish_done, piece_done (status, reason, edits, calls, usd, seconds),
render_failed, published (the job summary), alert.
"""
from __future__ import annotations

import json
import logging

from . import constants as C

log = logging.getLogger("scene_finish.events")


def emit(event: str, **fields) -> None:
    log.info(json.dumps({"event": event, **fields}, sort_keys=True, default=str))


def alerts(summary: dict) -> list[dict]:
    """The alert conditions the design names, evaluated on a published job's summary."""
    out = []
    pieces = summary.get("pieces", {})
    failed = sum(1 for p in pieces.values() if p["status"] != "passed")
    if pieces and failed / len(pieces) > C.ALERT_FAILED_PIECE_RATE:
        out.append({"alert": "failed_piece_rate", "failed": failed, "pieces": len(pieces)})
    if summary.get("spend_usd", 0) >= summary.get("spend_ceiling_usd", float("inf")):
        out.append({"alert": "spend_ceiling_reached", "usd": summary["spend_usd"]})
    if summary.get("time_to_look_s", 0) > C.ALERT_TIME_TO_LOOK_S:
        out.append({"alert": "slow_time_to_look", "seconds": summary["time_to_look_s"]})
    if summary.get("deadline_hit"):
        out.append({"alert": "deadline_hit"})
    return out
