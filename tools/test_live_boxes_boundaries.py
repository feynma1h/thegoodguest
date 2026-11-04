"""Live boxes' two boundaries, checked against the tree rather than trusted.

THE AGPL BOUNDARY (decision 0295). The detector live boxes runs is Ultralytics
YOLOE-26: its code and weights are AGPL-3.0, and this repository is public and
all-rights-reserved. So the model, anything exported from it, and any code that
imports `ultralytics` stay out of git. The export is dropped into
`ios/TheGoodGuest/TheGoodGuest/LiveBoxes/Model/` before a build, and that folder
is ignored. A `git add -A` in the wrong mood is all it takes to break this, and
nothing else in the repository would notice.

THE DEBUG BOUNDARY. Until the detector has a licence that allows distribution,
live boxes must be unreachable in Release builds. Every Swift file under
`LiveBoxes/` is compiled only under `#if DEBUG`, and every reference to one of
its top-level types from outside that folder sits inside an `#if DEBUG` block.
A Release build therefore contains none of it, by construction rather than by
review. The Release configuration also excludes model packages from the app
bundle, so a model left in the drop folder cannot be shipped by accident.

Read by: CI's root job, via `testpaths` in pyproject.toml.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
APP = REPO / "ios/TheGoodGuest/TheGoodGuest"
LIVE_BOXES = APP / "LiveBoxes"
MODEL_DROP = LIVE_BOXES / "Model"

TOP_LEVEL_TYPE = re.compile(
    r"^(?:(?:@\w+|nonisolated|final|private|fileprivate|internal|public)\s+)*"
    r"(?:struct|class|enum|protocol|actor)\s+([A-Z]\w*)", re.M)


def _tracked(*patterns: str) -> list[str]:
    out = subprocess.run(["git", "ls-files", "--", *patterns], cwd=REPO,
                         capture_output=True, text=True, check=True).stdout
    return [line for line in out.splitlines() if line]


def _code(text: str) -> list[str]:
    """Source lines with // comments removed: a type named in a comment is not a reference."""
    lines = []
    for line in text.splitlines():
        lines.append("" if line.lstrip().startswith("//") else line.split("//")[0])
    return lines


def _unguarded_references(text: str, names: set[str]) -> list[int]:
    """Line numbers naming one of `names` outside every #if DEBUG branch."""
    words = re.compile(r"\b(" + "|".join(sorted(names)) + r")\b")
    branches: list[bool] = []  # one per open #if: is the current branch DEBUG?
    found = []
    for number, line in enumerate(_code(text), start=1):
        s = line.strip()
        if s.startswith("#if"):
            branches.append(s == "#if DEBUG")
        elif s.startswith("#else"):
            if branches:
                branches[-1] = False
        elif s.startswith("#endif"):
            if branches:
                branches.pop()
        elif words.search(line) and not any(branches):
            found.append(number)
    return found


# ── The AGPL boundary ────────────────────────────────────────────────────────

def test_the_model_drop_folder_is_ignored():
    probe = MODEL_DROP.relative_to(REPO) / "yoloe26s_pf_app_640.mlpackage" / "Manifest.json"
    result = subprocess.run(["git", "check-ignore", "-q", str(probe)], cwd=REPO)
    assert result.returncode == 0, f"{MODEL_DROP.relative_to(REPO)} must be gitignored"


def test_no_model_checkpoint_or_text_encoder_is_tracked():
    tracked = _tracked("*.mlpackage/*", "*.mlmodel", "*.mlmodelc/*", "*.pt", "*mobileclip*",
                       str(MODEL_DROP.relative_to(REPO)))
    assert tracked == [], f"model files are tracked: {tracked}"


def test_no_tracked_code_imports_ultralytics():
    pattern = re.compile(r"^\s*(import\s+ultralytics|from\s+ultralytics\b)", re.M)
    offenders = [
        path for path in _tracked("*.py", "*.ipynb", "*.sh")
        if pattern.search((REPO / path).read_text(encoding="utf-8", errors="replace"))
    ]
    assert offenders == [], f"tracked files import ultralytics: {offenders}"


def test_release_builds_exclude_model_packages():
    """EXCLUDED_SOURCE_FILE_NAMES is set on the Release app target and not on Debug."""
    pbx = (REPO / "ios/TheGoodGuest/TheGoodGuest.xcodeproj/project.pbxproj").read_text(encoding="utf-8")
    app = {m.group(1): m.group(0)
           for m in re.finditer(r"/\* (Debug|Release) \*/ = \{.*?\n\t\t\};", pbx, flags=re.S)
           if "PRODUCT_BUNDLE_IDENTIFIER = com.thegoodguest.TheGoodGuest;" in m.group(0)}
    assert {"Debug", "Release"} <= app.keys()
    assert 'EXCLUDED_SOURCE_FILE_NAMES = "*.mlpackage *.mlmodel";' in app["Release"]
    assert "EXCLUDED_SOURCE_FILE_NAMES" not in app["Debug"]
    assert "COREML_CODEGEN_LANGUAGE = None;" in app["Release"]


# ── The DEBUG boundary ───────────────────────────────────────────────────────

def _live_boxes_sources() -> list[Path]:
    return sorted(LIVE_BOXES.rglob("*.swift"))


def test_every_live_boxes_file_compiles_only_in_debug():
    for path in _live_boxes_sources():
        code = [line.strip() for line in _code(path.read_text(encoding="utf-8")) if line.strip()]
        assert code[0] == "#if DEBUG", f"{path.name} has code before #if DEBUG"
        assert code[-1] == "#endif", f"{path.name} has code after its closing #endif"
        depth, closed_early = 0, False
        for i, line in enumerate(code):
            if line.startswith("#if"):
                depth += 1
            elif line.startswith("#endif"):
                depth -= 1
                closed_early |= depth == 0 and i != len(code) - 1
        assert not closed_early, f"{path.name} leaves #if DEBUG before its end"


def _declared_types() -> set[str]:
    names: set[str] = set()
    for path in _live_boxes_sources():
        names.update(TOP_LEVEL_TYPE.findall("\n".join(_code(path.read_text(encoding="utf-8")))))
    return names


def test_the_app_names_live_boxes_types_only_inside_debug_blocks():
    names = _declared_types()
    if not names:  # no sources yet: nothing to reference
        return
    offenders = []
    for path in sorted(APP.rglob("*.swift")):
        if LIVE_BOXES in path.parents:
            continue
        for number in _unguarded_references(path.read_text(encoding="utf-8"), names):
            offenders.append(f"{path.relative_to(REPO)}:{number}")
    assert offenders == [], "live-boxes types referenced outside #if DEBUG:\n" + "\n".join(offenders)


def test_the_reference_check_sees_an_unguarded_reference():
    text = ("#if DEBUG\nlet a = LiveBoxesView.self\n#else\nlet b = LiveBoxesView.self\n#endif\n"
            "let c = LiveBoxesEntry.self // LiveBoxesView in a comment\n// LiveBoxesView\n")
    assert _unguarded_references(text, {"LiveBoxesView", "LiveBoxesEntry"}) == [4, 6]


def test_the_capture_flow_reaches_live_boxes_only_inside_debug_blocks():
    """Live boxes ride the capture (decision 0301): CaptureManager forwards frames to the
    frame driver and RootFlowView builds the camera layer. Both name LiveBoxes types, and
    both do it inside #if DEBUG. The references must exist, or the check above is vacuous
    for the two files that matter most."""
    names = _declared_types()
    assert {"BoxFusion", "LiveBoxesFrameDriver", "LiveBoxesCamera"} <= names
    for relative, name in [("Capture/CaptureManager.swift", "LiveBoxesFrameDriver"),
                           ("RootFlowView.swift", "LiveBoxesCamera")]:
        text = (APP / relative).read_text(encoding="utf-8")
        assert re.search(rf"\b{name}\b", "\n".join(_code(text))), f"{relative} no longer names {name}"
        assert _unguarded_references(text, {name}) == [], f"{relative} names {name} outside #if DEBUG"
