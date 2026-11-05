"""What Claude is told. Prompts are versioned with the vocabulary
(`constants.VOCAB_VERSION`, `PROMPT_VERSION`) and recorded in every output file.

WHAT LEAVES THE SERVICE, exactly (decision 0352):
  finish pass     up to FINISH_MAX_IMAGES rectified wall/floor atlases (medians
                  over frames) and patches cut from them around door/window
                  openings, each labelled with its size in metres; the measured
                  colours as text. No camera frame. No renders needed.
  furniture write one box's size and category, the ids and categories of the
                  other boxed pieces (so `on`/`over` can name a target), and up
                  to PHOTO_CROPS_PER_REQUEST person-masked crops of the object,
                  long side <= PHOTO_CROP_MAX_SIDE_PX.
  furniture edit  the same crops, our own renders of the current model from the
                  same views, the current spec as JSON, and the measured numbers.
Never sent: the capture bundle, depth, poses, world coordinates, user, device or
scene identifiers, location, other rooms.
"""
from __future__ import annotations

import json

from . import constants as C
from .client import Image, Request

SPEC_VOCABULARY = """\
You model ONE piece of furniture as a small parametric model, from photographs of it, so a 3D viewer can
draw it. You write parameters in metres; you never write pixels.

FRAME. The piece's own frame: origin at the centre of its footprint ON THE FLOOR, +y up, x along the box's
width, z along its depth. The model must stand inside the given box (x and z centred on 0, y from 0 to the
box height), by at most 10% over. Nothing may go below y = 0.

PARTS (kind -> fields). Every part has: kind, mat (a material name you define), name, optional at [x,y,z]
(the part's centre), optional rot [degrees x,y,z], noShadow, uvSwap.
  box      size [x,y,z], bevel (rounded edge, metres)
  cyl      r, rTop (optional, tapered), h, seg
  sphere   r (a radius) or r3 [rx,ry,rz]
  lathe    profile [[radius, y], ...] bottom to top, a surface of revolution about the part's y axis
  tube     path [[x,y,z], ...], r, closed
  extrude  outline [[x,y], ...] in the part's x/y plane, depth along z, bevel
  books    w, depth, hmin, hmax, tmin, tmax, mats [material names], seed: a shelf row, standing on at.y
  drape    w, h, folds, amp (a pleated hanging cloth); hemH, hemOff for a strip of a longer cloth
Use few, meaningful parts (at most 60): the large masses first, then legs, trim and details you can see.

MATERIALS (name, color #rrggbb, rough 0..1, metal, clearcoat, opacity, double (thin cloth), emissive +
emissive_intensity, bump 0..1). Optional texture tex: kind one of quilt, wood, weave, lattice, ribbon,
stripe, grid; tile_m (metres per repeat), palette [#rrggbb...], seed, p [{k, v}] pattern numbers.

CONVENTIONS. A lamp's shade part is named "lamp-shade" (the room lights it at night). A visible light
source that glows is a part whose name starts with "glow" and noShadow true.

PLACEMENT. place.rule: floor (stands on its box, the default), wall (a flat piece that hangs on the nearest
wall), on (stands on top of another piece; target = that piece's id), over (hangs in front of another piece,
such as a curtain over a window; target = its id). Targets must be ids from the list you are given.

Describe what you SEE, in the colours you see. If a part is hidden from every view, give it a plausible
simple form and say so in note. Answer only with the JSON the schema asks for.
"""

CRITIQUE_ADDENDUM = """\
You are now shown the photographs again beside renders of your current model from the same viewpoints, the
model itself, and numbers measured inside the render's own silhouette:
  dl   lightness difference photo vs render (after a fixed scene offset), lower is better
  dab  hue/chroma difference, lower is better
  gap  1 - overlap of the render's silhouette box and the object's box in the photo, lower is better
Name the biggest differences (proportion, colour, material, missing detail, wrong place) and edit the model
to fix them. Return the full revised model in `spec`. If the render already matches the photographs as well
as these parts can, return done = true with the reason and omit spec. Never change what you cannot see.
"""

FINISH_VOCABULARY = """\
You read the rectified, face-on pictures of a room's walls and floor (each is a median over many photos, so
furniture and people have mostly dropped out; magenta means never seen) and report ONLY the structure a
colour measurement cannot see. Report a section only when you can see it clearly; omit the rest.

  baseboard   present (true/false); hex colour and height_m if present
  wainscot    a tiled or panelled band along the lower wall: height_m of its top edge, tile_u_m x tile_v_m
              (one tile, metres), joint "light" or "dark" (the grout against the tile)
  floor       slab_u_m x slab_v_m: the floor's tile or plank repeat in metres
  door        casing "frame" | "none" | #rrggbb; panels: raised panels as [u0,v0,u1,v1] fractions of the door
  window      casing as above; glass_hex: the colour of the pane

For each section give one short `evidence` entry naming what you saw (at most 200 characters).
Heights are measured up from the floor edge, which is the bottom row of a wall picture. Answer only with
the JSON the schema asks for.
"""


def _text(d: dict) -> str:
    return json.dumps(d, sort_keys=True)


def spec_request(box: dict, others: list[dict], crops: list[Image], scene_id: str) -> Request:
    meta = {"id": box["id"], "category": box["category"], "label": box.get("label", ""),
            "box_size_m": [round(float(x), 3) for x in box["size"]],
            "other_pieces": [{"id": o["id"], "category": o["category"]} for o in others]}
    content: list = [f"The piece to model: {_text(meta)}. Photographs of it follow (people are blacked out)."]
    content += crops
    content.append("Write the model.")
    return Request("spec", C.FURNITURE_MODEL, SPEC_VOCABULARY, content, _schema("spec"), C.MAX_TOKENS_SPEC,
                   scene_id=scene_id, box_id=box["id"], iteration=0)


def critique_request(box: dict, others: list[dict], spec: dict, pairs: list[tuple[Image, Image]], numbers: dict,
                     history: list[dict], iteration: int, scene_id: str) -> Request:
    meta = {"id": box["id"], "category": box["category"], "box_size_m": [round(float(x), 3) for x in box["size"]],
            "other_pieces": [{"id": o["id"], "category": o["category"]} for o in others]}
    content: list = [f"Piece: {_text(meta)}. Edit {iteration} of at most {C.MAX_EDITS}.",
                     "Current model:\n" + json.dumps({k: v for k, v in spec.items() if k not in ("key", "object", "box_dims", "revision")}, sort_keys=True),
                     "Measured now: " + _text(numbers), "Earlier edits (accepted or rejected, with numbers): " + _text(history[-4:])]
    for photo, render in pairs:
        content += [photo, render]
    content.append("Critique and edit, or finish.")
    return Request("critique", C.FURNITURE_MODEL, SPEC_VOCABULARY + "\n" + CRITIQUE_ADDENDUM, content,
                   _schema("critique"), C.MAX_TOKENS_CRITIQUE, scene_id=scene_id, box_id=box["id"], iteration=iteration)


def finish_request(images: list[Image], measured: dict, scene_id: str) -> Request:
    content: list = ["Pictures of the room's surfaces follow, each labelled with what it is and how large."]
    content += images
    content.append("Measured colours (for context only): " + _text(measured) + "\nReport the structure you see.")
    return Request("finish", C.FINISH_MODEL, FINISH_VOCABULARY, content, _schema("finish"), C.MAX_TOKENS_FINISH, scene_id=scene_id)


def _schema(which: str) -> dict:
    from . import schemas

    return {"spec": schemas.SPEC_SCHEMA, "critique": schemas.CRITIQUE_SCHEMA, "finish": schemas.FINISH_SCHEMA}[which]
