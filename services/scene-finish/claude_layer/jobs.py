"""Building the context a task runs in: workspace, caller, ledger, deadline."""
from __future__ import annotations

from contextlib import contextmanager

from . import publish
from .client import ClaudeCaller
from .piece_loop import JobContext
from .scene_port import ScenePort
from .spend import SpendLedger
from .workspace import Workspace


@contextmanager
def job_context(deps, port: ScenePort, worker: str):
    """A JobContext whose workspace (every pixel the task derives) is deleted on
    exit, however the task ends."""
    job = port.read_json(publish.JOB)
    deadline = job["started_ts"] + job["deadline_s"] if job else deps.clock() + 1e9
    ws = Workspace(port, assume_no_people=deps.assume_no_people)
    try:
        caller = ClaudeCaller(deps.client, SpendLedger(port, worker), port.scene_id)
        yield JobContext(port=port, ws=ws, caller=caller, renderer=deps.renderer, code_sha=deps.code_sha,
                         deadline_ts=deadline, clock=deps.clock)
    finally:
        ws.close()
