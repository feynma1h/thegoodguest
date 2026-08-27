# 0264 — the upstream source is vendored, pinned, and enforced

**Date:** 2026-08-28
**Status:** Decided and built

## Context

This investigation reached a wrong conclusion about SAM 3's per-instance
`score` and carried it for two turns. The claim — that it is a detection
confidence rather than a mask-quality measure — turned out to be right, but it
was a guess dressed as a fact, and the operator caught it by asking what the
number was supposed to mean. It was not the first time: the pattern is a
plausible statement about a third-party model, never checked, propagated into a
decision.

The cause is structural rather than careless. **The source we run lives inside
the container image**, at `/opt/sam3-repo` and `/opt/sam3d`, so no session
working in a worktree could read it at any price. Reasoning from our own wrapper
plus priors was the only option available.

Three things made it worse.

**Our own comment pointed at a directory that has never existed.**
`models/sam3.py` said "SAM 3 is installed as an editable package at /opt/sam3"
and did `sys.path.insert(0, "/opt/sam3")`. The Dockerfile clones to
`/opt/sam3-repo`. The insert was a silent no-op — imports work because
`pip install -e` had already put the package on the path — so nothing failed,
and anyone who went looking for the source found an empty path and stopped.

**Neither clone was pinned.** Both were `git clone --depth 1 <url>` with no
revision, so every build took whatever `main` was at that moment. Two builds of
identical repo source could install different model code with nothing recording
which — and SAM 3.1 shares that `main` and needs different checkpoints from the
`facebook/sam3` weights we download.

**And upstream documents almost none of it.** The README specifies neither the
score's meaning, nor the confidence threshold, nor what to do with duplicate
instances. Checked, not assumed. The authority is the source and the twelve
notebooks in `examples/`.

## What we chose

Three layers, weakest last.

**1. Vendor and pin.** `services/perception-obj/upstream/` holds verbatim copies
of the entry points our two wrappers call — SAM 3's image processor and model
builder, SAM 3D's `Inference` class — plus Meta's LICENSE, whose §1.b.i requires
the Agreement to travel with any copy. The Dockerfile now fetches both
repositories by commit. The pins are **the commits the serving image was built
from**, not upstream HEAD: `8f0b7f4d` was `sam3`'s HEAD on 2026-08-24 when
`perception-obj-00074-var` was built, and the three commits since are all "Fix
B001: Replace bare except with except Exception". So the pin reproduces what
runs and changes nothing.

`tests/test_upstream_pins.py` asserts the Dockerfile, the README's table and the
vendored files agree, and that the vendored copy stays unimportable.

**2. A hook.** `.claude/hooks/upstream-models-notice.py` fires `PreToolUse` on
the wrappers, `mask_refine.py` and `upstream/`, and injects one short paragraph:
do not assert what these models do without citing the vendored source.
`tools/test_upstream_hook.py` pins that it fires on the right files, once per
session, and — the property that matters more — exits 0 on every malformed
payload, because a non-zero exit from a `PreToolUse` hook blocks the tool call.

**3. A skill.** `.claude/skills/upstream-models/` carries the procedure: where
the source is, how to fetch a file at the pin rather than from `main`, that the
notebooks are the real documentation, and the traps already paid for.

## Why

**A skill alone would have failed here, and the reason is precise.** A skill
fires when the model judges it relevant — and the judgement that fails is
exactly "do I already know what SAM 3 returns?" A session confident in a wrong
premise has no reason to reach for it. The hook does not ask; it fires on the
file. So the deterministic trigger carries the interruption and the skill
carries the substance, which is also why the hook's text is four sentences: a
hook that lectures gets switched off, and then there is no trigger at all.

**Neither of them substitutes for the source being present.** The strongest
layer is the least clever one — a copy in the repo that `grep` can reach. The
Claude-specific machinery exists to stop that copy going stale and to point at
it, not to replace it.

**A vendored copy that disagrees with the image is worse than none**, because it
is a plausible lie and it would be believed. That is the whole reason the pin
test exists, and why `upstream/README.md` records settled facts — the score
formula, the 0.5 threshold, the absence of NMS and of any IoU head, the
availability of negative geometric prompts — beside the commit they were read
at. A fact without its pin is a rumour.

**The absence of upstream documentation is itself the finding.** Because the
README specifies none of this, there is no document to be diligent about. The
rule has to be "read the source", and that rule is unenforceable while the
source is only inside a container — which is what makes vendoring the fix rather
than a convenience.

## What would change this decision

**If the vendored set grows past the entry points, stop.** It is documentation,
not a mirror. The moment someone vendors a subtree to avoid a fetch, it becomes
a second copy of the model that drifts silently; the test only guards the files
it knows about.

**If a pin refresh becomes routine, the cost has moved.** Editing the SAM 3D
clone line invalidates the layer cache from near the top of the Dockerfile — the
50-60 minute build, not the 8-10 minute one. That cost is what keeps a refresh
deliberate. If upstream starts moving in ways we need, the answer is to reorder
the Dockerfile so the clone sits below the expensive layers, not to unpin.

**If the hook proves noisy, shrink its file list before switching it off.** Once
per session across five paths was chosen to be ignorable; if it still grates,
`models/sam3.py` and `models/sam3d.py` alone would carry most of the value.
