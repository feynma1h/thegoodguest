"""SAM 3.1 wrapper: the video tracker, which is the half that carries object IDs.

WHY THIS IS A SEPARATE MODEL AND NOT A VERSION BUMP. SAM 3 is two components
sharing one backbone — an image-level detector answering Promptable Concept
Segmentation, and a memory-based video tracker answering Promptable Visual
Segmentation. `models/sam3.py` wraps the detector, and the detector's output
(`masks`, `masks_logits`, `boxes`, `scores`) carries no instance identity at
all: `set_image` builds a fresh state per call, so instances are rows of a
tensor and nothing relates row 3 of frame 41 to row 3 of frame 42.

Object IDs come from the tracker, and only from the tracker. SAM 3.1 is a
release OF the tracker: its single checkpoint is literally `sam3.1_multiplex.pt`
and `build_sam3_image_model` still hardcodes `download_ckpt_from_hf(
version="sam3")`. So "move to SAM 3.1" and "get stable instance IDs" are one
change, not two, and neither is reachable from the path `models/sam3.py` uses.

Read from `facebookresearch/sam3` @ main, 2026-08-30:
  - `model_builder.build_sam3_multiplex_video_predictor` — "the recommended
    entry point for SAM 3.1 multiplex video tracking"; builds tracker AND
    detector from one merged checkpoint.
  - `model_builder.download_ckpt_from_hf(version="sam3.1")` — repo
    `facebook/sam3.1`, file `sam3.1_multiplex.pt`.
  - `sam3_multiplex_tracking.Sam3MultiplexTrackingWithInteractivity` — the
    object this predictor wraps, and the one whose methods we call.
  - `io_utils.load_resource_as_video_frames` — accepts a LIST OF PIL IMAGES as
    `resource_path`, which is why this wrapper takes frames rather than a path.

THREE UPSTREAM SHAPES THIS WRAPPER WORKS AROUND. Two were read from source
before building; the first was not, and cost a candidate — it is the one that
does not show up as a signature or a default, only as a decorator on somebody
else's method:

  0. **Calling the model directly means supplying inference mode ourselves.**
     `init_state`, `add_prompt` and `propagate_in_video` each carry
     `@torch.inference_mode()`, but `reset_state` does NOT — it relies on its
     CALLER being inside it, which upstream guarantees because
     `Sam3BasePredictor.handle_request` is itself decorated. Since the state's
     tensors are created inside `init_state`'s inference mode, they are
     inference tensors, and `reset_state`'s in-place
     `text_ids[...] = 0` raises "Inplace update to inference tensor outside
     InferenceMode is not allowed" when called from ordinary code. Measured on
     a 0%-traffic candidate, 2026-08-30. So every model call here is wrapped;
     the decorators upstream carries are a floor, not the whole contract.

  1. **`Sam3BasePredictor.start_session` cannot start a multiplex session.** It
     builds `init_kwargs` containing `offload_state_to_cpu` unconditionally and
     calls `self.model.init_state(**init_kwargs)`, but
     `Sam3MultiplexTrackingWithInteractivity.init_state` takes no such
     parameter — its signature is `(resource_path, offload_video_to_cpu,
     async_loading_frames, use_torchcodec, use_cv2, input_is_mp4)`. The sibling
     dispatchers `add_prompt` and `propagate_in_video` both filter kwargs
     through `inspect.signature`; `start_session` does not. So we call the model
     directly and keep no session registry — we have one video and one process,
     and the session layer only adds expiry bookkeeping we do not want.

  2. **Constructing the predictor enters a process-global autocast that is
     never exited.** `Sam3MultiplexVideoPredictor.__init__` does
     `self.bf16_context = torch.autocast(...); self.bf16_context.__enter__()`
     with no matching exit. `models/sam3.py` scopes its autocast per call
     precisely so SAM 3D's dtype regime is not polluted; a permanent global one
     would defeat that for anything sharing the container. We exit it at
     construction and re-enter per call, which is the same discipline the
     sibling wrapper already follows.
"""
from __future__ import annotations

import logging
import os
from contextlib import ExitStack
from typing import Any

import numpy as np
import torch

# The stride of the STORED raster, defined by the receiver that writes it —
# track_receiver has to stay importable without torch (it is on the
# Dockerfile's deferred-import smoke line), so the constant lives on that side
# and the decimation happens here, where the full masks already are.
from track_receiver import MASK_STRIDE

logger = logging.getLogger(__name__)


# Upstream's own default is 16, and 16 instances OF ONE CONCEPT is already
# generous for a room — a pass tracks "chair", not the whole vocabulary. It is
# an env var rather than a constant because it is a CONSTRUCTOR argument: if a
# concept turns out to saturate it, changing this costs a revision (seconds)
# instead of a rebuild (8-10 minutes). Saturation is visible in the output as a
# concept reporting exactly this many objects.
#
# `multiplex_count` is deliberately NOT exposed: it sizes the per-object mask
# channels of the memory encoder, so the checkpoint's weights depend on it.
TRACK_MAX_OBJECTS = int(os.environ.get("PERCEPTION_TRACK_MAX_OBJECTS", "16"))


class SAM3VideoModel:
    """SAM 3.1 multiplex video tracker. One instance per container."""

    def __init__(self, max_num_objects: int | None = None, multiplex_count: int = 16):
        max_num_objects = (
            TRACK_MAX_OBJECTS if max_num_objects is None else max_num_objects
        )
        # Deferred exactly as models/sam3.py defers its imports: importing this
        # module must not initialise CUDA at server startup. Note there is no
        # sys.path.insert here — the "/opt/sam3" that models/sam3.py inserts has
        # never existed (the clone is /opt/sam3-repo) and the insert is a no-op;
        # imports resolve because `pip install -e` already put the package on
        # the path. Copying a known no-op into new code would propagate it.
        from sam3.model_builder import (  # noqa: PLC0415
            build_sam3_multiplex_video_predictor,
        )

        self.max_num_objects = max_num_objects
        predictor = build_sam3_multiplex_video_predictor(
            max_num_objects=max_num_objects,
            multiplex_count=multiplex_count,
            # FLASH ATTENTION 3 IS OFF, AND THAT IS NOT A PERFORMANCE CHOICE.
            # `build_sam3_multiplex_video_predictor` defaults use_fa3=True while
            # `build_sam3_multiplex_video_model` defaults it False, so the
            # recommended entry point turns it on. Its path
            # (`sam3/perflib/fa3.py`) imports `flash_attn_interface` and casts
            # q/k/v to torch.float8_e4m3fn — FlashAttention 3 in FP8, which is
            # Hopper (sm_90). This service runs on an L4 (Ada, sm_89) and the
            # image does not install that package, so the default would raise
            # at the first attention call rather than degrade. With it off,
            # `model_misc` takes the `F.scaled_dot_product_attention` branch.
            use_fa3=False,
            # Left at the entry point's own default: it selects a real-valued
            # RoPE formulation for torch.compile compatibility, is parameter
            # free, and is the shape 3.1 is exercised with upstream.
            use_rope_real=True,
            compile=False,
            warm_up=False,
        )
        # See workaround 2 in the module docstring.
        ctx = getattr(predictor, "bf16_context", None)
        if ctx is not None:
            try:
                ctx.__exit__(None, None, None)
            except Exception:  # pragma: no cover - defensive; never seen
                logger.warning("[sam3v] could not exit the predictor's global autocast")

        self.predictor = predictor
        # See workaround 1: the model, not the session layer, is our API.
        self.model = predictor.model
        self._use_bf16_autocast = torch.cuda.is_available()

    def _session(self):
        """Inference mode plus bf16 autocast — the environment upstream's own
        request layer supplies, and which calling the model directly does not.

        Inference mode is NOT optional: see workaround 0. Autocast mirrors what
        `models/sam3.py` does, scoped per call rather than entered globally.
        """
        stack = ExitStack()
        stack.enter_context(torch.inference_mode())
        if self._use_bf16_autocast:
            stack.enter_context(
                torch.autocast(device_type="cuda", dtype=torch.bfloat16)
            )
        return stack

    # -- video lifecycle -----------------------------------------------------

    def open_video(self, frames: list, *, offload_video_to_cpu: bool = True):
        """Decode a frame list into an inference state.

        `frames` is a list of PIL images in the order they should be tracked.
        Upstream stores them as float16 at `image_size` squared (1008), which is
        ~6.1 MB a frame — 1.15 GB for a 189-frame capture. That belongs in host
        RAM rather than in the L4's 24 GiB beside the model, so
        `offload_video_to_cpu` defaults True; upstream's own comment calls the
        overhead "very small".

        This is the expensive call, so it is separated from tracking: one video
        is opened once and every concept is tracked against it.
        """
        with self._session():
            return self.model.init_state(
                resource_path=frames,
                offload_video_to_cpu=offload_video_to_cpu,
                async_loading_frames=False,
            )

    def track_concept(
        self,
        state,
        concept: str,
        *,
        prompt_frame: int = 0,
        output_prob_thresh: float = 0.5,
    ) -> dict[int, list[dict[str, Any]]]:
        """Track every instance of one concept across the whole video.

        ONE CONCEPT PER PASS, because the session holds one text prompt: the
        upstream notebook resets the session before switching prompt and says
        the results are otherwise wrong. `reset_state` clears prompts and
        action history but keeps the decoded frames, so N concepts cost one
        decode and N propagations.

        The prompt is added on `prompt_frame` and propagation runs FORWARD from
        there. A concept absent from that frame is not lost: the detector runs
        on every frame during propagation and unmatched detections are given
        fresh ids (`new_det_obj_ids = max_obj_id + 1 + arange(n)` in
        `sam3_video_base.py`), which is how instances that only appear later
        enter the map.

        `output_prob_thresh` REACHES `add_prompt` AND NOT PROPAGATION, which is
        upstream's shape rather than ours:
        `Sam3MultiplexTrackingWithInteractivity.propagate_in_video` takes the
        argument and then, on the full-text-prompt path, calls
        `super().propagate_in_video(...)` without forwarding it — so the parent
        uses its own 0.5 default for every frame after the prompted one. Passing
        a different value here is therefore not a way to tune the tracker, and
        the parameter is kept only because `add_prompt` does honour it.

        Returns {frame_position: [ {obj_id, prob, bbox_px, area_px, mask_small},
        ... ]}, keyed by POSITION IN THE FRAME LIST, not by capture frame index
        — the caller owns that mapping.
        """
        with self._session():
            self.model.reset_state(state)
            self.model.add_prompt(
                state,
                prompt_frame,
                text_str=concept,
                output_prob_thresh=output_prob_thresh,
            )

            out: dict[int, list[dict[str, Any]]] = {}
            for pos, raw in self.model.propagate_in_video(
                state,
                start_frame_idx=prompt_frame,
                reverse=False,
                output_prob_thresh=output_prob_thresh,
            ):
                out[int(pos)] = _compact(raw)
        return out

    def close_video(self, state) -> None:
        """Drop the decoded frames and tracker memory."""
        try:
            with self._session():
                self.model.reset_state(state)
        except Exception:  # pragma: no cover - best effort
            logger.warning("[sam3v] reset_state failed while closing video")
        state.clear()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()


def _compact(raw: dict[str, Any]) -> list[dict[str, Any]]:
    """Reduce one frame's tracker output to what the map needs.

    Upstream's per-frame dict (`sam3_multiplex_tracking.py`) is:
        out_obj_ids       int64   (N,)
        out_probs         float32 (N,)
        out_boxes_xywh    float32 (N, 4)  -- NORMALISED; divided by W and H
        out_binary_masks  bool    (N, H, W) at ORIGINAL video resolution

    Area and bbox are taken at full resolution, so they are exact. Only the
    stored raster is decimated (see MASK_STRIDE).
    """
    obj_ids = np.asarray(raw.get("out_obj_ids", []), dtype=np.int64).reshape(-1)
    masks = raw.get("out_binary_masks")
    if masks is None or len(obj_ids) == 0:
        return []
    masks = np.asarray(masks, dtype=bool)
    if masks.ndim == 2:
        masks = masks[None, ...]
    probs = np.asarray(raw.get("out_probs", []), dtype=np.float32).reshape(-1)
    boxes = np.asarray(raw.get("out_boxes_xywh", []), dtype=np.float32).reshape(-1, 4)

    n = min(len(obj_ids), len(masks))
    if not (len(obj_ids) == len(masks) == len(probs) == len(boxes)):
        # A length mismatch is an upstream anomaly. Say so and keep the rows
        # that are jointly present rather than silently misindexing ids onto
        # the wrong masks — the failure this whole exercise exists to prevent.
        logger.warning(
            "[sam3v] parallel array mismatch ids=%d masks=%d probs=%d boxes=%d",
            len(obj_ids), len(masks), len(probs), len(boxes),
        )
        n = min(n, len(probs), len(boxes))

    h, w = masks.shape[-2:]
    rows: list[dict[str, Any]] = []
    for i in range(n):
        m = masks[i]
        x, y, bw, bh = (float(v) for v in boxes[i])
        rows.append({
            "obj_id": int(obj_ids[i]),
            "prob": float(probs[i]),
            # Denormalised to pixels; upstream divides by W and H on the way out.
            "bbox_px": [x * w, y * h, bw * w, bh * h],
            "area_px": int(m.sum()),
            "mask_small": np.packbits(m[::MASK_STRIDE, ::MASK_STRIDE]),
            "mask_small_shape": list(m[::MASK_STRIDE, ::MASK_STRIDE].shape),
        })
    return rows
