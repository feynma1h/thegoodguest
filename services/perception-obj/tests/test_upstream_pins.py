"""The vendored upstream copies must match the commits the Dockerfile pins.

WHY THIS EXISTS. `services/perception-obj/upstream/` is a readable copy of the
Meta source our two model wrappers call, checked in because the running source
only exists inside the container image and no session working in this repo could
read it. Several sessions reasoned about SAM 3's behaviour from our wrapper plus
priors and were wrong; one of them was wrong because `models/sam3.py` named a
path (`/opt/sam3`) the image has never contained.

A vendored copy that silently disagrees with what the image installs is worse
than no copy at all — it is a plausible lie, and it would be believed. So this
pins the three things that must agree:

  1. the Dockerfile clones both repositories at an explicit commit, never at
     whatever `main` happens to be;
  2. upstream/README.md's table records the SAME commits;
  3. the vendored files carry the header text the pinned revision carries.

It does NOT fetch anything. A test that needed the network would be skipped in
CI and would then never run.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = ROOT / "Dockerfile"
UPSTREAM = ROOT / "upstream"
README = UPSTREAM / "README.md"

SHA_RE = re.compile(r"\b[0-9a-f]{40}\b")

REPOS = {
    "sam3": "facebookresearch/sam3.git",
    "sam3d": "facebookresearch/sam-3d-objects.git",
}

VENDORED = {
    "sam3": [
        "sam3_image_processor.py", "model_builder.py",
        # Added 2026-08-28: reading only the processor produced a claim that
        # SAM 3's image path has no mask-quality score and takes no points.
        # Both are false — predict_inst lives here — and the too-narrow vendor
        # set is what made the wrong reading easy.
        "sam3_image.py", "sam1_task_predictor.py",
        # Added 2026-08-28: the mask-prompt size is set here, and following the
        # predictor's own docstring instead cost a GPU round trip.
        "prompt_encoder.py",
        "LICENSE",
    ],
    "sam3d": ["inference.py", "LICENSE"],
}


def _dockerfile() -> str:
    return DOCKERFILE.read_text()


def _pinned_sha_for(remote: str) -> str:
    """The SHA the Dockerfile fetches for one remote.

    The pinned form is `git remote add origin <remote>` followed by
    `git fetch --depth 1 origin <sha>` in the same RUN, so the SHA is the next
    40-hex token after the remote URL.
    """
    text = _dockerfile()
    idx = text.find(remote)
    assert idx != -1, f"Dockerfile no longer references {remote}"
    m = SHA_RE.search(text, idx)
    assert m is not None, f"no commit SHA follows {remote} — is the clone unpinned?"
    return m.group(0)


class TestTheClonesArePinned:
    @pytest.mark.parametrize("remote", sorted(REPOS.values()))
    def test_a_commit_sha_follows_each_remote(self, remote: str) -> None:
        assert len(_pinned_sha_for(remote)) == 40

    @pytest.mark.parametrize("remote", sorted(REPOS.values()))
    def test_the_clone_does_not_track_a_branch(self, remote: str) -> None:
        """`git clone --depth 1 <remote>` with no revision takes whatever main
        is at build time, which is the defect this file exists to prevent."""
        text = _dockerfile()
        for line in text.splitlines():
            if remote in line and "git clone" in line:
                pytest.fail(
                    f"{remote} is cloned by branch, not by commit: {line.strip()}"
                )


class TestTheReadmeRecordsTheSamePins:
    @pytest.mark.parametrize("key", sorted(REPOS))
    def test_readme_carries_the_dockerfile_sha(self, key: str) -> None:
        sha = _pinned_sha_for(REPOS[key])
        assert sha in README.read_text(), (
            f"upstream/README.md does not record {key}'s pinned commit {sha}. "
            "Move the SHA in both places or the vendored copy becomes a "
            "plausible lie."
        )


class TestTheVendoredFilesAreThere:
    @pytest.mark.parametrize(
        ("pkg", "name"),
        [(p, n) for p, names in VENDORED.items() for n in names],
    )
    def test_file_exists_and_is_not_empty(self, pkg: str, name: str) -> None:
        path = UPSTREAM / pkg / name
        assert path.is_file(), f"vendored {pkg}/{name} is missing"
        assert path.stat().st_size > 0

    @pytest.mark.parametrize("pkg", sorted(VENDORED))
    def test_the_licence_travels_with_the_source(self, pkg: str) -> None:
        """SAM License section 1.b.i requires the Agreement to accompany any
        copy of the materials."""
        assert "SAM License" in (UPSTREAM / pkg / "LICENSE").read_text()

    def test_nothing_vendored_is_importable_by_the_service(self) -> None:
        """The copy is documentation. If it ever became an import path, the
        service would run one version and read another."""
        for pkg in VENDORED:
            assert not (UPSTREAM / pkg / "__init__.py").exists(), (
                f"upstream/{pkg}/__init__.py makes the vendored copy a package; "
                "it must stay unimportable"
            )


class TestTheProcessorFactsWeDependOn:
    """The claims `models/sam3.py` and upstream/README.md make about the score
    are quoted from this file. If upstream changes them under a new pin, these
    fail rather than the docstring quietly going stale."""

    @pytest.fixture(scope="class")
    def processor(self) -> str:
        return (UPSTREAM / "sam3" / "sam3_image_processor.py").read_text()

    def test_score_is_match_times_presence(self, processor: str) -> None:
        assert "presence_logit_dec" in processor
        assert "out_probs = (out_probs * presence_score)" in processor

    def test_confidence_threshold_defaults_to_half(self, processor: str) -> None:
        assert "confidence_threshold=0.5" in processor
        assert "keep = out_probs > self.confidence_threshold" in processor

    def test_the_text_path_returns_no_mask_quality_score(self, processor: str) -> None:
        """`set_text_prompt` has no IoU output. This is a fact about THIS file
        and must not be read as a fact about SAM 3 — `predict_inst` in
        sam3_image.py returns exactly such a score, and reading only this file
        is how that got stated the wrong way round."""
        assert "iou_pred" not in processor

    def test_the_mask_prompt_size_is_derived_not_quoted(self) -> None:
        """`mask_input_size = 4 * image_embedding_size` is the formula; the
        predictor's docstrings quote SAM 2's 256 and are stale for SAM 3."""
        enc = (UPSTREAM / "sam3" / "prompt_encoder.py").read_text()
        assert "4 * image_embedding_size[0]" in enc
        pred = (UPSTREAM / "sam3" / "sam1_task_predictor.py").read_text()
        assert "H=W=256" in pred, (
            "the stale docstring is the trap this test exists to remember; if "
            "upstream fixed it, drop this assertion and the 288 note with it"
        )

    def test_the_point_prompted_path_is_vendored_and_returns_quality(self) -> None:
        """The correction, pinned so it cannot be lost again."""
        img = (UPSTREAM / "sam3" / "sam3_image.py").read_text()
        assert "def predict_inst" in img
        assert "inst_interactive_predictor" in img

    def test_the_service_reads_the_path_the_dockerfile_installs(self) -> None:
        """The comment that sent a session to a non-existent directory."""
        wrapper = (ROOT / "models" / "sam3.py").read_text()
        assert '"/opt/sam3-repo"' in wrapper
        assert '"/opt/sam3"' not in wrapper
