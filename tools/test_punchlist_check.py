"""The punchlist checker must not drift away from the punchlist it checks.

WHY THIS TEST EXISTS. `punchlist_check.py` walks the IDs the punchlist
declares, so a probe whose entry has been deleted is never called again. It
does not fail. It does not warn. It simply stops existing, while still reading
like coverage to anyone opening the file. Two probes sat that way for weeks —
G4-06 (dev-fixtures under `web/public/`) and G4-07 (the serving-rollback tag) —
both written for entries that were correctly deleted when the work closed.

That is the repo's own recurring failure in its sharpest form: the tool built
to stop documents going quietly out of date had gone quietly out of date. The
reconciliation is cheap, so it is pinned here rather than left to whoever next
reads the registry.

The second property matters as much as the first: a `Check:` line that claims
`automated` while no probe is registered is a false claim about coverage, and
it is the same mistake pointed the other way.
"""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
PUNCHLIST = REPO / "docs" / "punchlist.md"


@pytest.fixture(scope="module")
def mod():
    spec = importlib.util.spec_from_file_location(
        "punchlist_check", REPO / "tools" / "punchlist_check.py"
    )
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_every_probe_has_a_punchlist_entry(mod):
    """The one that G4-06 and G4-07 would have failed."""
    assert mod.orphaned_checks() == [], (
        "probe(s) registered for entries the punchlist no longer declares — "
        "delete the probe, or restore the entry it was written for"
    )


def test_orphan_detection_actually_detects(mod, monkeypatch):
    """A guard nobody has seen fail is not a guard."""
    monkeypatch.setitem(mod.CHECKS, "G9-99", lambda: (True, "never called"))
    assert mod.orphaned_checks() == ["G9-99"]


def test_punchlist_ids_are_unique(mod):
    ids = mod.punchlist_ids()
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    assert not dupes, f"reusing an ID is worse than skipping it: {dupes}"


def test_every_entry_declares_how_it_is_checked():
    entries = re.split(r"^### (G\d-\d\d) ", PUNCHLIST.read_text(), flags=re.M)[1:]
    missing = [
        entries[i]
        for i in range(0, len(entries), 2)
        if "**Check:**" not in entries[i + 1]
    ]
    assert not missing, f"entries with no Check line: {missing}"


def test_automated_claims_have_a_probe(mod):
    """A Check line saying `automated` with nothing registered overstates coverage."""
    entries = re.split(r"^### (G\d-\d\d) ", PUNCHLIST.read_text(), flags=re.M)[1:]
    overclaimed = []
    for i in range(0, len(entries), 2):
        pid, body = entries[i], entries[i + 1]
        m = re.search(r"\*\*Check:\*\* *(\w+)", body)
        if m and m.group(1) == "automated" and pid not in mod.CHECKS:
            overclaimed.append(pid)
    assert not overclaimed, f"claims automated, has no probe: {overclaimed}"
