#!/usr/bin/env python3
"""PreToolUse notice: you are about to touch code that wraps a third-party model.

WHY A HOOK AND NOT ONLY A SKILL. A skill fires when the model decides it is
relevant, which is exactly the judgement that fails here — a session confident
it already knows what SAM 3 returns has no reason to reach for it. A hook fires
on the file, deterministically, whether or not anyone thought to ask.

It stays SHORT on purpose. The substance lives in the skill and in
services/perception-obj/upstream/README.md; this only has to interrupt the
assumption. A hook that lectures gets switched off.

Never blocks and never fails loudly: any unexpected input exits 0 silently, so
a malformed payload or a missing field can never stop work.
"""
from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from pathlib import Path

# Files whose subject matter is third-party model behaviour.
WATCHED = re.compile(
    r"services/perception-obj/(models/(sam3|sam3d)\.py"
    r"|mask_refine\.py"
    r"|upstream/)"
)

NOTICE = (
    "This file wraps a third-party model. Do not state what SAM 3 or SAM 3D "
    "returns, means or thresholds without citing its source: a pinned, readable "
    "copy of the entry points we call is at services/perception-obj/upstream/, "
    "and upstream/README.md already records the score formula, the 0.5 "
    "confidence threshold, the absence of NMS and of any IoU head, and that "
    "negative geometric prompts exist. Read that before re-deriving it. The "
    "`upstream-models` skill has the procedure for anything it does not cover."
)


def _already_shown(session: str) -> bool:
    """Once per session per file-set. A notice repeated on every Read is noise,
    and noisy hooks get disabled — which costs more than the repetition saves."""
    if not session:
        return False
    marker = Path(tempfile.gettempdir()) / f"upstream-notice-{re.sub(r'[^A-Za-z0-9_-]', '', session)[:64]}"
    if marker.exists():
        return True
    try:
        marker.touch()
    except OSError:
        return False
    return False


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    if not isinstance(payload, dict):
        return 0

    tool_input = payload.get("tool_input") or {}
    path = ""
    if isinstance(tool_input, dict):
        path = str(
            tool_input.get("file_path")
            or tool_input.get("path")
            or tool_input.get("notebook_path")
            or ""
        )
    if not path or not WATCHED.search(path.replace(os.sep, "/")):
        return 0

    session = str(payload.get("session_id") or os.environ.get("CLAUDE_SESSION_ID") or "")
    if _already_shown(session):
        return 0

    json.dump(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "additionalContext": NOTICE,
            }
        },
        sys.stdout,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
