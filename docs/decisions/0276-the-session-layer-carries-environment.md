# 0276 — the session layer carries environment, not just dispatch

**Date:** 2026-08-30
**Status:** Decided (three read from source, one measured on a candidate)

## Context

`/track` calls SAM 3.1's tracker directly — `model.init_state`, `add_prompt`,
`propagate_in_video`, `reset_state` — rather than through
`Sam3BasePredictor.handle_request`. That was forced: `start_session` cannot
start a multiplex session at all (below), and we have one video and one process,
so the session registry adds expiry bookkeeping and nothing else.

Skipping a dispatch layer looks free. It was not, and the reason generalises
past this model.

## What we tried

Four places where upstream's convenience layer is doing something its call
signature does not show. Three were read before building; the fourth cost a
candidate, and it is the one that could not have been read from the signatures
at all.

**1. `start_session` cannot start a multiplex session.** It builds
`init_kwargs` containing `offload_state_to_cpu` unconditionally and calls
`self.model.init_state(**init_kwargs)`, but
`Sam3MultiplexTrackingWithInteractivity.init_state` takes no such parameter.
Its siblings `add_prompt` and `propagate_in_video` both filter kwargs through
`inspect.signature` — with a comment saying SAM 3 has a simpler `add_prompt`
than SAM 3.1 — and `start_session` does not.

**2. Constructing the predictor enters a process-global autocast and never
exits it.** `Sam3MultiplexVideoPredictor.__init__` does
`self.bf16_context = torch.autocast(...); self.bf16_context.__enter__()` with no
matching exit and no method that would perform one.

**3. The recommended entry point defaults to hardware we do not have.**
`build_sam3_multiplex_video_predictor` defaults `use_fa3=True` while
`build_sam3_multiplex_video_model` defaults it `False`. That path
(`sam3/perflib/fa3.py`) imports `flash_attn_interface` and casts q/k/v to
`torch.float8_e4m3fn` — FlashAttention 3 in FP8, which is Hopper. This service
runs on an L4.

**4. `reset_state` requires its CALLER to be in inference mode, and says so
nowhere.** `init_state`, `add_prompt` and `propagate_in_video` each carry
`@torch.inference_mode()`. `reset_state` carries no decorator. Because the
state's tensors are created inside `init_state`'s inference mode they are
*inference tensors*, and `reset_state`'s in-place `text_ids[...] = 0` then
raises `Inplace update to inference tensor outside InferenceMode is not
allowed`. Upstream never sees this because `Sam3BasePredictor.handle_request`
is itself `@torch.inference_mode()`, so every path through the session layer is
already inside one.

Measured on `perception-obj-00090-wey`: the model loaded in 142.0 s and the
first `reset_state` raised.

## What we chose

Keep the direct calls, and replicate the environment rather than only the
sequence: every model call is wrapped in `torch.inference_mode()` plus a scoped
bf16 autocast, the predictor's global autocast is exited at construction, and
`use_fa3=False` is passed explicitly.

## Why

**Items 1-3 are visible in signatures and defaults; item 4 is not, and that is
the finding.** Reading `reset_state` shows nothing wrong with it. Reading the
methods around it shows decorators that look like ordinary per-method
optimisation. The precondition only appears when you notice that the one method
lacking the decorator is never called except from a decorated one — a property
of the *call graph*, not of any declaration. 0264's rule is "read the model, not
the wrapper", and this is the sharper form: **read what the caller establishes,
not only what the callee accepts.**

**The general shape is that a convenience layer is often load-bearing.**
`handle_request` reads like dispatch — a type string and some kwargs — and it
is also the thing that establishes inference mode for the entire library. Any
decision to bypass a layer like that should ask what it *enters*, not just what
it *calls*, and the cheap check is to grep the layer for context managers and
decorators before deleting it from the path.

**And the local suite could not have caught it.** torch is absent from the
environment the perception tests run in, so `models/sam3_video.py` cannot be
imported there at any price. The 0%-traffic candidate is the only instrument
that reaches this class of defect, which is precisely what 0142 says it is for
— and it did its job here for the cost of one build.

## What would change this decision

**If `start_session` is fixed upstream**, item 1 disappears and using the
session layer becomes an option again — which would also fix item 4 for free,
because `handle_request` supplies the mode. That is the tidier end state and it
is one upstream patch away: filter `init_kwargs` through `inspect.signature` the
way the sibling dispatchers already do.

**If a second route ever loads this model**, the global-autocast exit becomes
load-bearing rather than defensive, because two models with different dtype
regimes would then share a process. Today `/track` is alone and the exit is
insurance.
