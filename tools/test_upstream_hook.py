"""The PreToolUse notice must fire on the model wrappers and never break work.

WHY TEST A HOOK. It is the only part of the upstream-source mechanism that
fires without anyone choosing to invoke it — a skill waits to be judged
relevant, which is the judgement that fails when a session is confident it
already knows what SAM 3 returns. If the hook silently stops matching, nothing
surfaces: work continues, the notice just never appears, and the mechanism is
gone without a symptom.

So the two properties pinned here are "it fires on the right files" and "it
cannot stop work" — the second matters more. A hook that raises on a payload
shape it did not expect would block a tool call in every session.
"""
from __future__ import annotations

import json
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parents[1] / ".claude" / "hooks" / "upstream-models-notice.py"


def run(payload: str) -> tuple[int, str]:
    p = subprocess.run(
        [sys.executable, str(HOOK)], input=payload, capture_output=True, text=True
    )
    return p.returncode, p.stdout


def fire(path: str, session: str | None = None) -> str:
    session = session or f"test-{uuid.uuid4()}"
    code, out = run(json.dumps({"session_id": session, "tool_input": {"file_path": path}}))
    assert code == 0
    return out


class TestItFiresWhereItShould:
    @pytest.mark.parametrize("path", [
        "/repo/services/perception-obj/models/sam3.py",
        "/repo/services/perception-obj/models/sam3d.py",
        "/repo/services/perception-obj/mask_refine.py",
        "/repo/services/perception-obj/upstream/README.md",
        "/repo/services/perception-obj/upstream/sam3/sam3_image_processor.py",
    ])
    def test_watched_files_emit_the_notice(self, path: str) -> None:
        out = fire(path)
        assert out, f"no notice for {path}"
        assert json.loads(out)["hookSpecificOutput"]["hookEventName"] == "PreToolUse"
        assert "upstream" in json.loads(out)["hookSpecificOutput"]["additionalContext"]

    @pytest.mark.parametrize("path", [
        "/repo/services/perception-obj/fusion.py",
        "/repo/services/perception-obj/box_placement.py",
        "/repo/web/src/components/SplatViewer.tsx",
        "/repo/CLAUDE.md",
    ])
    def test_unwatched_files_stay_silent(self, path: str) -> None:
        assert fire(path) == ""

    def test_it_fires_once_per_session(self) -> None:
        s = f"test-{uuid.uuid4()}"
        assert fire("/repo/services/perception-obj/models/sam3.py", s)
        assert fire("/repo/services/perception-obj/models/sam3d.py", s) == "", (
            "the notice repeated inside one session; a noisy hook gets disabled"
        )


class TestItCannotStopWork:
    """Every one of these must exit 0. A non-zero exit from a PreToolUse hook
    can block the tool call."""

    @pytest.mark.parametrize("payload", [
        "",
        "not json",
        "[]",
        "null",
        "{}",
        '{"tool_input": null}',
        '{"tool_input": "a string"}',
        '{"tool_input": {}}',
        '{"tool_input": {"file_path": null}}',
        '{"session_id": {"not": "a string"}, "tool_input": {"file_path": "x/models/sam3.py"}}',
    ])
    def test_malformed_input_exits_zero_and_says_nothing(self, payload: str) -> None:
        code, out = run(payload)
        assert code == 0, f"hook exited {code} on {payload!r} — this blocks tool calls"
        if out:
            json.loads(out)  # if it spoke at all, it must be valid JSON


class TestItIsWiredUp:
    def test_settings_registers_the_hook_for_file_tools(self) -> None:
        settings = json.loads(
            (Path(__file__).resolve().parents[1] / ".claude" / "settings.json").read_text()
        )
        entries = settings["hooks"]["PreToolUse"]
        commands = [
            h["command"]
            for e in entries
            for h in e["hooks"]
            if "upstream-models-notice" in h.get("command", "")
        ]
        assert commands, "the notice hook is not registered in .claude/settings.json"
        matchers = [e["matcher"] for e in entries if any(
            "upstream-models-notice" in h.get("command", "") for h in e["hooks"]
        )]
        for m in matchers:
            assert "Read" in m and "Edit" in m

    def test_the_hook_is_executable(self) -> None:
        assert HOOK.is_file()
        assert HOOK.stat().st_mode & 0o111, "hook is not executable"
