# 0352 — What leaves the service is built in one place, and its pixels are deleted at job end

**Date:** 2026-11-05
**Status:** Decided — the privacy limits are PROPOSED to the operator and built as named constants

## Context

Photographs of a home go to a third-party model. The only person filter is the SAM 3 `suppressed` mask, which misses anything SAM 3 did not label (screens, documents, photos on walls).

## What we chose

Exactly what is sent (also stated in `prompts.py`):
- **Finish pass:** up to 8 rectified wall/floor atlases (a median over frames, so furniture and people mostly drop out) and patches cut from them around door/window openings, each labelled with its size in metres; the measured colours as text. Never a camera frame. The request check refuses any other image kind at this stage.
- **Furniture pass:** one box's size and category, the ids and categories of the other boxed pieces, and at most 6 photo crops (`PHOTO_CROPS_PER_REQUEST`) cut around the object with a 12% margin, long side at most 768 px (`PHOTO_CROP_MAX_SIDE_PX`) so text cannot be read, plus our own renders of the model.
- A crop is built only by `images.photo_crop`: person pixels are blacked out BEFORE the crop is shrunk, a crop that is more than 35% person is dropped, and a frame whose mask is unknown is never used (it fails closed; a piece with no usable frame fails and calls nothing). The request check refuses a photo that was not built that way.
- Never sent: the bundle, depth, poses or world coordinates, user, device or scene identifiers, location, other rooms. No pixel, prompt or path is logged.

Everything derived from pixels (the materialised captures, crops, renders, atlases) lives in a `Workspace`, a temp folder deleted on exit however the task ends (published, failed, deadline, exception). A link to a read-only source is removed as a link. Only JSON is ever written back (0357).

## Why

Making the rules the only way to build an image turns a privacy review into reading one file. Failing closed on the mask costs recall (a piece may fail) and is the right side to err on.

## What would change this decision

The operator's ruling on the proposed limits (whole masked frames? zero data retention?); the product's privacy page must say that room photographs are processed by a third-party model before launch. The mask file's location (`scenes/<id>/frames/<idx>/masks.npz`, frame index as the key) was read in `shell_receiver.py` and is not yet verified against a real bucket.
