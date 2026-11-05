"""The Claude layer of scene-finish: what Claude is asked, what it may see,
what it costs, and when its answers are accepted (decisions 0350-0359).

  constants      every tunable, named, with the reason for its value
  spend          the per-scan spend ceiling, checked before each call
  client         the one place a Claude request leaves this service (+ fake)
  schemas        JSON Schemas of the answers, over the closed vocabularies
  prompts        the system prompts and request builders
  images         the privacy gate for pixels: masked, capped, counted
  workspace      the throw-away folder a job's pixels live in
  scene_port     where a scene's JSON lives (local folder or GCS)
  gates          the accept/reject arithmetic
  finish_pass    /finish: measured finish + Claude hints, gated by renders
  piece_loop     /furniture-piece: spec, build, render, compare, critique
  publish        /furniture-merge: all-at-once publishing with a deadline
  redrive        rebuild furniture.json from cached specs, no pixels needed
"""
