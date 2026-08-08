# Synthetic room views

Nine rendered views of a plain synthetic bedroom, consumed by
`tools/build_test_bundle.py` to assemble a `CaptureBundle` without needing a
phone. Regenerate with:

```
python tools/make_synthetic_photos.py
```

They are committed, so the smoke path works from a fresh checkout with no
generation step:

```
python tools/build_test_bundle.py && python tools/inspect_bundle.py outputs/test_bundle/bundle.pb
```

## Why synthetic

This directory used to hold nine HEIC photographs of a real bedroom, committed
in the repo's first commit. They carried GPS EXIF pinning a precise home
location, which is not something to hand to a git remote, so they were purged
from history before the repo's first push (decision 0101).

The replacement is not merely safer, it is more correct. `build_test_bundle`
invents a camera trajectory — an arc of nine poses, radius 2.5 m, looking
inward — and the real photographs knew nothing about it, so the bundle paired
images of one room with poses from another. These views are **rendered from
those exact poses**, through the exact intrinsics the bundle records
(`fx = fy = max(w, h)`, principal point centred, rendered at 1024×768 so no
downscale intervenes). Frame *i* is now genuinely what a camera at pose *i*
would see.

## What these are not

Perception fixtures. Flat-shaded boxes will not exercise SAM 3 and are not
meant to; `build_test_bundle` is a **contract** smoke test — does a bundle
assemble, serialize, and survive ingest validation. Real-room regression data
lives in `outputs/real-capture-*/`, gitignored and never committed.

Adding your own photographs here works (any JPG/PNG/HEIC is picked up), but
think before committing them: whatever you add inherits the same permanence
problem, and phone photos carry EXIF location by default.
