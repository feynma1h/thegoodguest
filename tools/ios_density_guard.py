#!/usr/bin/env python3
"""Track how much denser each screen is at AX5, against what the ceiling implies.

    python3 tools/ios_screenshot_gallery.py /tmp/shots
    python3 tools/ios_density_guard.py /tmp/shots

Exits non-zero when a screen is denser than the type ceiling can account for,
so the accessibility sizes have a measurement rather than an opinion.

WHY DENSITY AND NOT TYPE SIZE. The defect this exists to catch is not "the type
got big" — it is that the app's restraint IS its empty space, and Dynamic Type
spends empty space. Measured before the type tiers landed, the mean screen went
from 15% inked to 25%, which sounds mild; the two screens that carry the whole
design language went from 1.1% and 0.9% to 6.3% and 5.2%, or 5.7x. A per-style
size assertion would have passed all of that, because every individual size was
behaving exactly as Dynamic Type asks.

CEREMONIAL AND FULL-BLEED SCREENS ARE EXCLUDED, for the reason the layout audit
excludes them: their ink is a drawn graphic rather than type, so the ratio
measures the artwork rather than the layout. The doorway is 0.95x for that
reason alone.
"""
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

SHOTS = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/rs-all")

# The app holds Dynamic Type at `RSTypeSize.ceiling` (accessibility2), where
# body text is 33pt against 17 at the default size.
CEILING_SCALE = 33 / 17

# WHAT THE LIMIT IS, AND WHY IT IS NOT 2.
#
# Ink area for a given string scales with the SQUARE of the type size, so a
# screen showing the same content at 1.94x type is 3.76x denser — by
# arithmetic, with nothing wrong. A 2x limit was therefore unreachable for any
# screen that still showed all of its content, and the only ways to meet it
# were to shrink the type below 1.41x or to stop showing things. Both were
# ruled out.
#
# So the bound is the arithmetic itself. A screen at or just under the square
# is behaving exactly as a larger copy of itself. A screen well UNDER it has
# lost content off the bottom of the frame, which is the interesting signal and
# is why the ratio is printed for every screen rather than only the failures.
# A screen ABOVE it is drawing more than it did, which should be impossible.
LIMIT = CEILING_SCALE ** 2

# Same classification the layout audit uses, and for the same reason.
SKIP_PREFIXES = ("capture", "doorway", "splash")
SKIP = {"gotroom", "unsupported", "qr"}


def density(path):
    """Fraction of the body area that is drawn, against a per-row background.

    Per row because the parchment is a gradient — the same reason the layout
    audit samples it that way. The status bar and the home indicator are cut
    off: both are system chrome and neither scales with the app's type.
    """
    a = np.asarray(Image.open(path).convert("L")).astype(int)
    body = a[200:2480]
    bg = np.median(np.concatenate([body[:, 14:56], body[:, 1150:1192]], axis=1), axis=1)
    return float((np.abs(body - bg[:, None]) > 30).mean())


def main():
    rows, bad = [], 0
    for p in sorted((SHOTS / "default").glob("*.png")):
        sid = p.stem
        if sid.startswith(SKIP_PREFIXES) or sid in SKIP:
            continue
        ax = SHOTS / "ax5" / f"{sid}.png"
        if not ax.exists():
            continue
        d, x = density(p), density(ax)
        ratio = x / d if d else float("inf")
        over = ratio > LIMIT
        bad += over
        rows.append((sid, d, x, ratio, over))

    rows.sort(key=lambda r: -r[3])
    w = max(len(r[0]) for r in rows) + 1
    print(f"{'screen':{w}} {'default':>8} {'AX5':>8} {'ratio':>7}")
    print("-" * (w + 26))
    for sid, d, x, ratio, over in rows:
        print(f"{sid:{w}} {d*100:7.1f}% {x*100:7.1f}% {ratio:6.2f}x"
              + ("   OVER" if over else ""))
    mean_d = np.mean([r[1] for r in rows]); mean_x = np.mean([r[2] for r in rows])
    print(f"\nmean {mean_d*100:.1f}% -> {mean_x*100:.1f}%  ({mean_x/mean_d:.2f}x)")
    print(f"type ceiling {CEILING_SCALE:.2f}x  ->  same content predicts {LIMIT:.2f}x")
    print(f"{bad} of {len(rows)} screens denser than the ceiling accounts for")
    return bad


if __name__ == "__main__":
    sys.exit(0 if main() == 0 else 1)
