"""Every tunable of the Claude layer, named. Values marked [proposed] come from
the phase-2 design (section 4.7) and must be calibrated on the cloud renderer
against real scenes before launch; [operator] values are product decisions."""
from __future__ import annotations

import os

# --- Privacy: exactly what may leave the service (decision 0352) -------------
# Finish pass: rectified wall/floor ATLASES (a median over frames, so people and
# furniture drop out) and patches cut from them around door/window openings.
# NEVER a camera frame. [operator, proposed to operator]
FINISH_MAX_IMAGES = 8
FINISH_IMAGE_MAX_SIDE_PX = 1024
# Furniture pass: crops cut around one boxed object, person-masked (suppressed
# pixels blacked out), at most 6 photo crops per request, long side <= 768 px so
# text cannot be read. Our own renders are not photos and are not counted.
PHOTO_CROPS_PER_REQUEST = 6
PHOTO_CROP_MAX_SIDE_PX = 768
CROP_PAD = 0.12  # margin around the projected box, share of its size
# A frame whose person-mask share inside the crop exceeds this is not evidence.
MAX_SUPPRESSED_SHARE = 0.35
# Pixels for a crop whose person mask is unavailable are never sent (fail closed).
SUPPRESSED_FILL_RGB = (0, 0, 0)

# --- Time and money -----------------------------------------------------------
JOB_DEADLINE_S = 40 * 60  # [operator] publish what passed this long after the job began
SPEND_CEILING_USD = float(os.environ.get("FINISH_MAX_USD", "12"))  # per scan
# A call is refused unless ceiling - spent covers its worst case; the worst case
# is this many output tokens at the model's output price plus its input estimate.
MAX_TOKENS_FINISH = 6000
MAX_TOKENS_SPEC = 8000
MAX_TOKENS_CRITIQUE = 8000
CALL_TIMEOUT_S = 300.0
SDK_MAX_RETRIES = 2
REASK_ON_INVALID = 1  # one re-ask with the validation error appended, then give up
# [USD per million tokens] (input, output, cache read). List prices, design 4.6.
PRICES = {
    "claude-opus-5-5": (4.0, 20.0, 0.4),
    "claude-sonnet-5-5": (2.0, 10.0, 0.2),
    "claude-haiku-5-5": (0.10, 0.50, 0.01),
}
UNKNOWN_MODEL_PRICE = max(PRICES.values())  # an unpriced model is billed as the dearest
FINISH_MODEL = os.environ.get("FINISH_HINT_MODEL", "claude-sonnet-5-5")
FURNITURE_MODEL = os.environ.get("FURNITURE_SPEC_MODEL", "claude-opus-5-5")
EFFORT = os.environ.get("FINISH_EFFORT", "medium")
# Estimated input tokens per image (width*height/750, design 4.6 [ASSUMED]).
PIXELS_PER_TOKEN = 750

# --- Furniture loop (design 4.3 / 4.7) -----------------------------------------
MAX_EVIDENCE_FRAMES = 4
MAX_EDITS = 6  # critique/edit calls per piece, after the initial write [doc]
MAX_REJECTED_IN_A_ROW = 2
MIN_GAIN_L = 0.3  # two accepted edits gaining less than this end the loop
TOL_DL = 1.0  # [proposed] renderer noise allowance, lightness and chroma
TOL_BBOX_GAP = 0.02  # [proposed] 1 - IoU of render mask bbox vs the box's projection
SPEC_OUTSIDE_BOX = 0.10  # parts may exceed the box by this share in any dimension
PLACEMENT_UNCERTAIN_GAP = 0.35  # [proposed] iteration-0 bbox gap above this: failed
MIN_MASK_PX = 800  # a render mask smaller than this is "no usable overlap"
MASK_ERODE_PX = 3
MIN_USABLE_FRAMES = 1

# --- Finish gate (design 4.7) ---------------------------------------------------
GATE_MIN_GAIN_L = 0.5  # [proposed] summed |dL| over measurable regions must fall by this
GATE_MAX_REGION_WORSE_L = 1.0  # [proposed] and no region may worsen by more
GATE_WAINSCOT_EDGE_M = 0.05  # [proposed] claimed band top vs the atlas edge
CALIBRATION_ROUNDS = 2
CALIBRATION_MAX_STEP_L = 4.0  # clamp each round's colour fold-in
CALIBRATION_MAX_STEP_AB = 3.0
CALIBRATION_STRENGTH = 0.9
FINISH_EVIDENCE_FRAMES = 6
RENDER_RETRIES = 1  # one retry in a fresh browser, then the piece/hint fails

# --- Observability alerts (design 4.6) -------------------------------------------
ALERT_FAILED_PIECE_RATE = 0.30
ALERT_TIME_TO_LOOK_S = 30 * 60
VOCAB_VERSION = 1
PROMPT_VERSION = 1
