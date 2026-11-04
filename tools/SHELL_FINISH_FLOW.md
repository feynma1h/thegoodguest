# Making a room's shell look like the actual room — the flow

How a scan's flat room shell becomes a finished one, in order, with what each step is in a pipeline. Everything here is offline and local; no pipeline change, no photo bake
(only numbers and colours reach the viewer, never pixels).

| # | Step | Tool | Automatable? |
|---|---|---|---|
| 1 | Look at the scan's frames next to a first generic render. Typical finding: a generic finish (white baseboards, white casings, plain paint) is wrong for a room with a tiled band under the paint, no baseboard, wood frames or stone floors. | `shell_finish.py --debug-dir` | A vision model can do this: "list what differs". |
| 2 | Rectify every wall and the floor from all frames into per-plane analysis atlases (median over frames removes furniture). Look at them. | `shell_atlas.py` | Yes (done). Registration of RoomPlan to the camera frames is typically good to a few cm. |
| 3 | Measure what the atlases support: wainscot top edge (a long unbroken horizontal edge, accepted when two walls agree), paint and tile colours (mean-shift mode, lit lightness), door/window frame and glass colours. | `shell_structure.py`, `shell_measure.py` | Yes. |
| 4 | Things the measurements do NOT support (tile pitch, slab size, door panels, window glass, baseboard yes/no) are read off the atlases/photos by eye and written to `finish_hints.json`, marked `review`. Periodic-edge detection for tile pitch fails under furniture clutter and the floor atlas is too smeared for slab joints. | `finish_hints.json` (validated by `finish_hints.py`) | This is the step a vision model (Claude) would take over: input atlases + frames, output the hints JSON. |
| 5 | Derive `finish.json` (colours + drawing parameters + provenance). | `shell_finish.py` | Yes. |
| 6 | Render the viewer from the camera pose of real frames; set photo and render side by side. | `finish_compare.py poses/sheet` + viewer harness | Yes (needs a headless browser; here: the preview pane). |
| 7 | Numeric colour check: per region (paint, tile, floor, door, glass) the photo's dominant colour minus the render's, over the exact pixels the id pass says belong to the region. Fold into hints as offsets. Repeat until the residual is small (paint/tile/floor residual in the low single digits of L after two rounds). | `finish_compare.py calibrate --write` | Yes. Caveat: region medians include furniture and under-read saturation, so check chroma by eye too. |
| 8 | Look at the sheet again; fix what is still visibly wrong in the DRAWING (floor veins looked like zigzags, stains like polygons, joints should be light grout, window pane colour). | `shellFinishScene.ts` | A vision critic can list these; code changes are human/agent. |

## Use Claude in the loop? My independent view
- **Do the geometry and colour with code, not a model.** Step 2/3/5/6/7 are measurable, repeatable, cheap and
  cannot hallucinate. The render-vs-photo colour residual is a real objective: on the reference scan it fell from ΔL 8–11 to about 2 in two rounds.
- **Use a vision model only for the structural reading (step 4) and as a critic (step 1/8):** "what in the room
  is part of the shell that is not drawn yet?" (tiled band, no baseboard, panelled wood door), returning the closed
  vocabulary of `finish_hints.py` (below). It must return parameters, never pixels, and every section is stamped
  `source: measured|review` so the viewer/UX can tell measured from reviewed.
- **Gate its output with the same render-compare loop:** accept a hint only if the render's per-region residual and
  structural overlay (band height, door position) improve. That makes the model's claim checkable, which is what
  keeps "close to the real room" from becoming "plausible-looking room".
- What cannot be done from a RoomPlan + phone scan: real slab layout (irregular marble), stains, what is behind a
  window, door hardware, wall sockets. The finish draws none of them; a floor with a user's actual stains needs
  the (rejected) photo path or a future per-room texture capture — that is a product decision, not an engineering gap.

## The hints vocabulary (`tools/finish_hints.py`)
`finish_hints.json` is validated by `parse_hints`: a section or key outside the vocabulary, a value out of range, or a
section without `source` is refused with every problem listed, so a hand edit or a model's answer cannot reach the
renderer unchecked. Every section is optional.

| Section | Keys | Meaning |
|---|---|---|
| `baseboard` | `present`, `hex`, `height_m` | whether the walls meet the floor with a baseboard |
| `wainscot` | `height_m`, `tile_u_m`, `tile_v_m`, `joint` (`light`/`dark`) | the tiled band: its top, tile pitch, grout |
| `floor` | `slab_u_m`, `slab_v_m` | stone slab or tile size |
| `openings.door` | `casing` (`frame`/`none`/`#hex`), `panels` (`[u0,v0,u1,v1]` rectangles on the leaf, 0..1) | raised door panels |
| `openings.window` | `casing`, `glass_hex` | what the pane shows |
| `calibration` | `paint`/`tile`/`floor`/`door`/`glass` as `[dL,da,db]`, `texture_gain` | written by `finish_compare.py calibrate --write`; `source` is always `measured` |

## Run it
```
V=/Users/aubrey/projects/thegoodguest/.venv/bin/python; SC=outputs/scene-<id>
$V tools/shell_finish.py $SC --debug-dir /tmp/dbg         # finish.json (+ frames with the shell projected)
$V tools/serve_scene.py $SC --port 8791 &                 # shell.json, finish.json, POST renders
NEXT_PUBLIC_SHELL_FINISH=1 npm --prefix web run dev -- -p 3100 &
open "http://localhost:3100/shell-finish?shell=http://127.0.0.1:8791/shell.json&finish=http://127.0.0.1:8791/finish.json"
$V tools/finish_compare.py poses $SC --frames 12,80,140,200   # prints a JS call; run it in the page console
$V tools/finish_compare.py sheet $SC --frames 12,80,140,200   # $SC/renders/compare.png
$V tools/finish_compare.py calibrate $SC --frames ... --write  # folds colour errors into finish_hints.json; re-run shell_finish.py
```

## Lighting pass (archviz polish) and what calibration taught
Added after the first photo match: filmic (Khronos Neutral) tone mapping and anti-aliasing, a room-derived
reflection environment (glossy tile, varnished door, stone), bump relief (tile joints, border course, door
panels, floor joints), a hemisphere wash so walls read the same from the dollhouse orbit as from inside, and a
faint window light pool on the floor (design only; sun is not measured).
- Any lighting change shifts every colour: re-run the pose/calibrate loop after it (exposure moved by more than half on the reference scan).
- The auto-calibration under-reads saturation (region medians include furniture and pale pixels) and will bleach the
  paint if applied blindly; check the dollhouse orbit view too, not only the photo-pose views, before trusting it.
- Reflection strength on walls must stay low (0.16): at grazing angles in the dollhouse view the reflection washes
  paint to grey.
