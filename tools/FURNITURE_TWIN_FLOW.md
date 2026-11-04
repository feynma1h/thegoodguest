# Furniture twins: the loop

A twin is a small parametric model of one real piece, placed in the room where its box is. Everything below
is offline and local; a twin carries parameters (parts, metres, materials), never pixels.

## Inputs
- `<scene>/boxes.json` — one box per piece: `id`, `category`, optional `label`, `center` (world metres, box centre),
  `yaw` (radians about +y), `size` (extents along the box's x, y, z). Format and loader: `furniture_boxes.py`.
  Windows and doors need no entry; they come from `shell.json`'s openings as `window_0`, `door_0`, ... in wall order.
- `<scene>/shell.json` — the floor polygon is the walls' room side.
- `<scene>/furniture/specs/<key>.json` — one parameter file per piece. `packages/room-look/tests/example/` holds an invented
  one (`specs/side-table.json`) and its `boxes.json`: the format fixture.

## The loop
1. MEASURE (code): `furniture_evidence.py <scene>` scores every frame per box (box in view, size, sharpness, viewpoint
   spread) and cuts upright crops into `<scene>/furniture/evidence/<id>/`.
2. READ (Claude): look at the crops; write the spec. Closed vocabulary: parts box/cyl/sphere/lathe/tube/extrude/books/drape,
   textures quilt/wood/weave/lattice/ribbon/stripe/grid. Parameters, never pixels. `furniture_models.py` refuses a spec
   that uses anything else.
3. BUILD (code): `furniture_models.py build <scene>` places every spec by the rules below and writes `furniture.json`.
4. CHECK (code): the build prints `WARN` lines for a spec that no longer matches its box, a part far outside it, or a twin
   that overlaps another or a wall; `furniture_clearance.py <scene>` runs the same clearance check on the file.
5. RENDER (code): `/shell-finish?shell=...&finish=...&furniture=<url>`; `furniture_compare.py poses` writes `poses.json`,
   the page runs `harness.runFrom(port)`, `furniture_compare.py sheet --iter N` writes photo|render sheets (kept per
   iteration) with dL/dE inside the render's own mask.
6. CRITIQUE (Claude): list what differs (proportion, colour, material, missing detail, wrong place); edit the spec; repeat.
   Accept a refinement when the sheet looks closer AND masked dL/bbox gap do not get worse.

## Placement rules (`furniture_placement.py`)
A spec says `"place": {"rule": ...}`; default `floor`.

| rule | meaning |
|---|---|
| `floor` | stands where its box is |
| `wall` | a flat piece: faces the room, back-most part `gap` (5 mm) off the nearest wall, place along the wall kept |
| `over` + `target` | like `wall`, in front of another twin (a curtain over a window) |
| `on` + `target` | stands on top of another twin, footprint centre kept inside it |
| `opening` | fixed at its box (a window or door slab); no invariant moves it |

For every other piece, repeated until nothing moves: nothing below the floor (raised), nothing through a wall (moved in),
no overlaps (the later `floor` piece is pushed apart along the shallowest horizontal way out; what stands on it travels
with it). A vertical overlap, or one where nothing may move, is not guessed at: it is reported. Declare `on` for a stack.

A hand correction is `place.fix = {dx, dy, dz, dyaw_deg, why}` in the box's frame, and `why` is required. Every move, by
a fix or a rule, is written into the twin's `fixes` list with its reason; `source` says `boxes+fixed` when there is one.

## Conventions the viewer reads
- A part with `"emits": true` is a light that is on at night: the viewer puts a point light inside it (intensity 5) and makes the part glow (0.55). Any number of parts may emit. Older specs named the part `lamp-shade`; the viewer still reads that name as an emitter.
- Parts named `glow...` with `noShadow` are light sources drawn emissive and ignored by the clearance check.

## Lessons
- Whites render lighter than photos (photo interiors are shadowed); flat bright light is a deliberate aesthetic choice.
- A placement error above about 10 cm is fixed by triangulating a pixel ray from two frames, not by guessing an offset.
