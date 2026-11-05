"""The numbers the finish and furniture gates compare against, in one place.

Each is a named constant with where it came from. "Measured" values were taken
on the cloud's renderer (headless Chrome, SwiftShader) against the local
reference scan on 2026-11-05 (decision 0332); "proposed" ones are the design's
and have NOT been measured, because they need a spec-versus-photo loop that
does not run yet. A gate imports these, never a literal.

Lightness is CIE L (0-100); a "frame" is one capture frame rendered at its own
camera pose.
"""

# -- measured: what the renderer itself contributes ------------------------

# Largest mean |dL| between SwiftShader and a GPU renderer (ANGLE Metal) over a
# region or a furniture piece, on regions both draw identically: 0.16 L (door,
# one frame); paint/tile/floor/glass/casing <= 0.11, pieces <= 0.11 (n=17).
# Run to run on SwiftShader the same frame is byte-identical in 5 of 6 runs.
RENDER_NOISE_L = 0.16

# -- carried over from finish_compare.calibrate (code constants there) -----

# A region counts only if its id mask has this many pixels after erosion, and
# the photo's dominant colour among them has at least this share; otherwise it
# is "not measurable", never "improved".
MIN_REGION_PIXELS = 1500
MIN_DOMINANT_SHARE = 0.12

# A region delta measured on fewer frames than this is not trusted: one frame
# whose id pass tied (see decision 0332) moved the tile delta by 6.5 L in a
# three-frame median.
MIN_FRAMES_PER_REGION = 3

# -- proposed (design 4.7), kept because they are several times the noise --

# Finish gate: accept a hint when the summed |dL| over measurable regions falls
# by at least this, and no single region worsens by more than the second value.
FINISH_ACCEPT_GAIN_L = 0.5  # ~3x RENDER_NOISE_L
FINISH_REGION_WORSEN_L = 1.0  # ~6x
# Furniture gate: a new spec is accepted when masked |dL| is no worse than the
# previous plus this, and the bounding-box gap no worse than the previous plus
# the second value (a 1 - IoU fraction). The box-gap tolerance is unmeasured.
FURNITURE_L_TOLERANCE = 1.0  # ~6x
FURNITURE_BBOX_GAP_TOLERANCE = 0.02
# Per-round colour correction limits (the saturation guard).
CALIBRATION_STEP_MAX_L = 4.0
CALIBRATION_CHROMA_STEP_MAX = 3.0
