#!/usr/bin/env python3
"""Build the screen gallery's contact sheet: one self-contained HTML page.

    python3 tools/ios_screenshot_gallery.py /tmp/shots
    python3 tools/ios_contact_sheet.py /tmp/shots /tmp/sheet.html

Every shot is embedded as a data URI, because the page is published as an
Artifact and the Artifact CSP blocks every remote host — a page that referenced
its own images by path would render as a wall of broken frames. That makes total
size the binding constraint rather than an afterthought: base64 costs a third
again on top of the bytes, and the ceiling is 16 MB.

SO IT DOWNSCALES RATHER THAN DROPPING SCREENS. A contact sheet missing the
states nobody photographs is the exact failure the gallery exists to fix, so
`--budget-mb` tunes the JPEG width and quality down until the whole set fits
instead of truncating it. What it costs is legibility of small type in the
thumbnails, which the lightbox gives back.
"""
import argparse
import base64
import html
import io
import json
import sys
from collections import OrderedDict
from pathlib import Path

from PIL import Image

PASSES = ("default", "ax5")
PASS_LABEL = {"default": "Default", "ax5": "AX5"}


def encode(path, width, quality):
    im = Image.open(path).convert("RGB")
    h = round(im.height * width / im.width)
    im = im.resize((width, h), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=quality, optimize=True, progressive=True)
    return buf.getvalue()


def encode_all(states, shots, width, quality):
    out = {}
    for s in states:
        for p in PASSES:
            f = shots / p / f"{s['id']}.png"
            if f.exists():
                out[(s["id"], p)] = encode(f, width, quality)
    return out


def fit(states, shots, budget_bytes, overhead):
    """Largest (width, quality) whose base64 payload fits the budget.

    Walked coarsest-first from a size worth having rather than binary-searched
    on quality alone: dropping width buys far more than dropping quality once
    quality is under about 70, and a 70%-quality thumbnail at a readable width
    beats a 92%-quality one too small to read.
    """
    for width, quality in ((640, 80), (560, 78), (500, 76), (460, 74),
                           (420, 72), (380, 70), (340, 68), (300, 66),
                           (260, 64), (220, 60)):
        blobs = encode_all(states, shots, width, quality)
        total = sum(len(b) for b in blobs.values()) * 4 // 3 + overhead
        print(f"  {width}px q{quality}: {total / 1e6:.1f} MB", file=sys.stderr)
        if total <= budget_bytes:
            return width, quality, blobs
    return width, quality, blobs


def build(shots, out, budget_mb, seen_ids):
    index = json.loads((shots / "index.json").read_text())

    # One record per state, carrying whichever passes were photographed. The
    # index has a row per (state, pass); the sheet is organised by state.
    states = OrderedDict()
    for row in index:
        s = states.setdefault(row["id"], {k: row[k] for k in
                                         ("id", "group", "title", "note",
                                          "delay", "reduceMotion")})
        s.setdefault("passes", []).append(row["pass"])

    states = list(states.values())
    groups = OrderedDict()
    for s in states:
        groups.setdefault(s["group"], []).append(s)

    width, quality, blobs = fit(states, shots, int(budget_mb * 1e6), 120_000)
    print(f"embedding at {width}px q{quality}", file=sys.stderr)

    # ASCII ONLY, with every other character as a numeric entity.
    #
    # The page is wrapped in a skeleton at publish time, so it cannot declare
    # its own charset — and a host that serves it as anything but UTF-8 renders
    # every em dash and middot as mojibake ("THE GOOD GUEST Â· IOS CAPTURE
    # APP"). Entities are charset-independent, and the base64 payload is
    # already ASCII, so this costs nothing.
    page = render(groups, states, blobs, width, seen_ids)
    page = page.encode("ascii", "xmlcharrefreplace").decode("ascii")
    out.write_text(page)
    mb = len(page.encode()) / 1e6
    print(f"{len(states)} states, {len(blobs)} shots -> {out} ({mb:.1f} MB)",
          file=sys.stderr)
    return mb


def shot_html(s, blobs, pass_name, width):
    b = blobs.get((s["id"], pass_name))
    if not b:
        return ""
    # ONE copy of the bytes. Carrying the same data URI in both `src` and a
    # `data-full` attribute for the lightbox doubled the page: 6.3 MB of images
    # rendered as a 12.4 MB file. The lightbox reads the img's own src.
    uri = "data:image/jpeg;base64," + base64.b64encode(b).decode()
    return f"""<figure class="shot" data-pass="{pass_name}">
<button class="plate" type="button"
        data-cap="{html.escape(s['title'])} — {PASS_LABEL[pass_name]}">
<img src="{uri}" alt="{html.escape(s['title'])}, {PASS_LABEL[pass_name]} text size" loading="lazy" width="{width}">
</button>
<figcaption>{PASS_LABEL[pass_name]}</figcaption>
</figure>"""


def render(groups, states, blobs, width, seen_ids):
    nav, sections = [], []
    for group, members in groups.items():
        slug = "g-" + group.lower().replace(" ", "-").replace("'", "")
        fresh = sum(1 for m in members if m["id"] not in seen_ids)
        nav.append(f'<li><a href="#{slug}"><span>{html.escape(group)}</span>'
                   f'<span class="n">{len(members)}</span></a></li>')

        cards = []
        for s in members:
            tags = []
            if s["id"] not in seen_ids:
                tags.append('<span class="tag new">first look</span>')
            if s["reduceMotion"]:
                tags.append('<span class="tag rm">reduce motion</span>')
            cards.append(f"""<article class="card" id="s-{s['id']}">
<div class="shots">{shot_html(s, blobs, 'default', width)}{shot_html(s, blobs, 'ax5', width)}</div>
<div class="meta">
<h3>{html.escape(s['title'])}</h3>
<p class="note">{html.escape(s['note'])}</p>
<p class="id"><code>{html.escape(s['id'])}</code><span class="at">{s['delay']:g}s</span>{''.join(tags)}</p>
</div>
</article>""")

        sections.append(f"""<section class="group" id="{slug}">
<header class="grouphead">
<h2>{html.escape(group)}</h2>
<p class="count">{len(members)} state{'s' if len(members) != 1 else ''}"""
                        + (f" · {fresh} never photographed" if fresh else "")
                        + f"""</p>
</header>
<div class="grid">{''.join(cards)}</div>
</section>""")

    total_fresh = sum(1 for s in states if s["id"] not in seen_ids)
    return TEMPLATE.format(
        nav="".join(nav),
        sections="".join(sections),
        n_states=len(states),
        n_groups=len(groups),
        n_shots=len(blobs),
        n_fresh=total_fresh,
    )


TEMPLATE = """<title>Every Screen, Every State</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Archivo:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap">
<style>
:root {{
  --ground:#e9e6df; --panel:#f6f4ef; --raised:#fffdf9;
  --ink:#1a1815; --dim:#6d6659; --faint:#918a7b;
  --rule:rgba(26,24,21,.13); --rule-firm:rgba(26,24,21,.24);
  --brass:#8a6a1f; --flag:#a8412b;
  /* Fixed in BOTH themes: every screenshot is judged against one ground, so a
     parchment screen and a capture screen can be compared without the page's
     own theme having moved underneath them. */
  --plate:#0b0a08; --plate-edge:rgba(255,255,255,.10);
  --shadow:0 1px 2px rgba(26,24,21,.10), 0 8px 24px -12px rgba(26,24,21,.22);
}}
@media (prefers-color-scheme: dark) {{
  :root:not([data-theme="light"]) {{
    --ground:#141310; --panel:#1c1a17; --raised:#232019;
    --ink:#ece7dd; --dim:#9b9384; --faint:#736c5f;
    --rule:rgba(236,231,221,.13); --rule-firm:rgba(236,231,221,.26);
    --brass:#c9a24f; --flag:#d4694f;
    --shadow:0 1px 2px rgba(0,0,0,.5), 0 10px 30px -14px rgba(0,0,0,.7);
  }}
}}
:root[data-theme="dark"] {{
  --ground:#141310; --panel:#1c1a17; --raised:#232019;
  --ink:#ece7dd; --dim:#9b9384; --faint:#736c5f;
  --rule:rgba(236,231,221,.13); --rule-firm:rgba(236,231,221,.26);
  --brass:#c9a24f; --flag:#d4694f;
  --shadow:0 1px 2px rgba(0,0,0,.5), 0 10px 30px -14px rgba(0,0,0,.7);
}}

* {{ box-sizing:border-box; }}
body {{
  margin:0; background:var(--ground); color:var(--ink);
  font-family:"Archivo","Helvetica Neue",Arial,sans-serif;
  font-size:15px; line-height:1.5;
  -webkit-font-smoothing:antialiased;
}}
code, .mono {{ font-family:"JetBrains Mono",ui-monospace,SFMono-Regular,Menlo,monospace; }}

.wrap {{ display:grid; grid-template-columns:210px minmax(0,1fr); gap:40px;
        max-width:1500px; margin:0 auto; padding:0 28px 96px; }}
@media (max-width:900px) {{ .wrap {{ grid-template-columns:minmax(0,1fr); gap:0; }} .rail {{ display:none; }} }}

/* ── Masthead ─────────────────────────────────────────────────────── */
.masthead {{ grid-column:1/-1; padding:56px 0 30px; border-bottom:1px solid var(--rule-firm); }}
.eyebrow {{ font-family:"JetBrains Mono",monospace; font-size:11px; letter-spacing:.16em;
           text-transform:uppercase; color:var(--brass); margin:0 0 14px; }}
h1 {{ font-size:clamp(30px,4.4vw,46px); line-height:1.06; letter-spacing:-.022em;
     font-weight:700; margin:0; text-wrap:balance; max-width:20ch; }}
.standfirst {{ margin:16px 0 0; max-width:62ch; color:var(--dim); font-size:16.5px; }}
.figures {{ display:flex; flex-wrap:wrap; gap:0; margin:28px 0 0; }}
.figure {{ padding-right:26px; margin-right:26px; border-right:1px solid var(--rule); }}
.figure:last-child {{ border-right:0; }}
.figure b {{ display:block; font-family:"JetBrains Mono",monospace; font-size:23px;
            font-weight:500; font-variant-numeric:tabular-nums; letter-spacing:-.02em; }}
.figure span {{ font-size:12px; color:var(--faint); letter-spacing:.03em; }}

/* ── Controls ─────────────────────────────────────────────────────── */
.controls {{ grid-column:1/-1; position:sticky; top:0; z-index:20;
            display:flex; align-items:center; gap:14px; flex-wrap:wrap;
            padding:12px 0; margin-bottom:10px;
            background:color-mix(in srgb, var(--ground) 92%, transparent);
            backdrop-filter:blur(10px); border-bottom:1px solid var(--rule); }}
.seg {{ display:inline-flex; border:1px solid var(--rule-firm); border-radius:7px; overflow:hidden; }}
.seg button {{ appearance:none; border:0; background:transparent; color:var(--dim);
              font:inherit; font-size:13px; padding:6px 13px; cursor:pointer;
              border-right:1px solid var(--rule); }}
.seg button:last-child {{ border-right:0; }}
.seg button[aria-pressed="true"] {{ background:var(--ink); color:var(--ground); }}
.seg button:focus-visible, .rail a:focus-visible, .plate:focus-visible {{
  outline:2px solid var(--brass); outline-offset:2px; }}
.ctl-label {{ font-family:"JetBrains Mono",monospace; font-size:11px; letter-spacing:.13em;
             text-transform:uppercase; color:var(--faint); }}

/* ── Rail ─────────────────────────────────────────────────────────── */
.rail {{ position:sticky; top:62px; align-self:start; padding-top:22px; }}
.rail ul {{ list-style:none; margin:0; padding:0; }}
.rail a {{ display:flex; justify-content:space-between; gap:10px; align-items:baseline;
          text-decoration:none; color:var(--dim); font-size:13.5px;
          padding:5px 0; border-bottom:1px solid var(--rule); }}
.rail a:hover {{ color:var(--ink); }}
.rail .n {{ font-family:"JetBrains Mono",monospace; font-size:11px; color:var(--faint);
           font-variant-numeric:tabular-nums; }}

/* ── Groups ───────────────────────────────────────────────────────── */
main {{ padding-top:22px; min-width:0; }}
.group {{ margin-bottom:52px; scroll-margin-top:74px; }}
.grouphead {{ display:flex; align-items:baseline; gap:14px; flex-wrap:wrap;
             padding-bottom:10px; margin-bottom:20px;
             border-bottom:2px solid var(--brass); }}
.grouphead h2 {{ font-size:21px; font-weight:600; letter-spacing:-.012em; margin:0; }}
.count {{ margin:0; font-family:"JetBrains Mono",monospace; font-size:11px;
         letter-spacing:.09em; text-transform:uppercase; color:var(--faint); }}

.grid {{ display:grid; gap:22px;
        grid-template-columns:repeat(auto-fill, minmax(268px,1fr)); }}
body[data-view="both"] .grid {{ grid-template-columns:repeat(auto-fill, minmax(400px,1fr)); }}

.card {{ background:var(--panel); border:1px solid var(--rule);
        border-radius:10px; padding:12px; box-shadow:var(--shadow);
        display:flex; flex-direction:column; gap:11px; }}
.shots {{ display:flex; gap:9px; }}
.shot {{ margin:0; flex:1 1 0; min-width:0; display:flex; flex-direction:column; gap:5px; }}
body[data-view="default"] .shot[data-pass="ax5"],
body[data-view="ax5"] .shot[data-pass="default"] {{ display:none; }}

.plate {{ appearance:none; padding:0; border:1px solid var(--plate-edge);
         border-radius:7px; overflow:hidden; background:var(--plate);
         cursor:zoom-in; display:block; line-height:0; }}
.plate img {{ width:100%; height:auto; display:block; }}
figcaption {{ font-family:"JetBrains Mono",monospace; font-size:9.5px;
             letter-spacing:.13em; text-transform:uppercase; color:var(--faint); }}

.meta h3 {{ margin:0 0 5px; font-size:15px; font-weight:600; letter-spacing:-.008em;
           text-wrap:balance; }}
.note {{ margin:0; font-size:13.5px; line-height:1.48; color:var(--dim); }}
.id {{ margin:9px 0 0; display:flex; align-items:center; gap:8px; flex-wrap:wrap; }}
.id code {{ font-size:11px; color:var(--faint); }}
.at {{ font-family:"JetBrains Mono",monospace; font-size:10px; color:var(--faint);
      font-variant-numeric:tabular-nums; }}
.tag {{ font-family:"JetBrains Mono",monospace; font-size:9px; letter-spacing:.11em;
       text-transform:uppercase; padding:2px 6px; border-radius:3px; }}
.tag.new {{ color:var(--brass); border:1px solid color-mix(in srgb, var(--brass) 45%, transparent); }}
.tag.rm {{ color:var(--flag); border:1px solid color-mix(in srgb, var(--flag) 42%, transparent); }}

/* ── Lightbox ─────────────────────────────────────────────────────── */
dialog.lb {{ border:0; padding:0; background:transparent; max-width:100vw; max-height:100vh; }}
dialog.lb::backdrop {{ background:rgba(8,7,6,.88); }}
.lb-inner {{ display:flex; flex-direction:column; align-items:center; gap:12px; padding:18px; }}
.lb-inner img {{ max-height:84vh; width:auto; border-radius:10px;
                background:var(--plate); box-shadow:0 24px 70px -20px rgba(0,0,0,.8); }}
.lb-cap {{ font-family:"JetBrains Mono",monospace; font-size:11px; letter-spacing:.1em;
          text-transform:uppercase; color:#cdc6b8; }}
@media (prefers-reduced-motion:no-preference) {{
  .card {{ transition:border-color .15s ease; }}
  .card:hover {{ border-color:var(--rule-firm); }}
}}
</style>

<div class="wrap">
<header class="masthead">
  <p class="eyebrow">The Good Guest · iOS capture app</p>
  <h1>Every screen, in every state it can reach</h1>
  <p class="standfirst">The app's surfaces photographed from the shipping layout, one frame per
  distinct state rather than one per screen — each enum case, and each combination of the values
  those cases carry that changes what is drawn. Every frame is shown at the default text size and
  at accessibility&nbsp;XXXL, which is where this app's layout defects have actually lived.</p>
  <div class="figures">
    <div class="figure"><b>{n_states}</b><span>states</span></div>
    <div class="figure"><b>{n_groups}</b><span>screens</span></div>
    <div class="figure"><b>{n_shots}</b><span>frames</span></div>
    <div class="figure"><b>{n_fresh}</b><span>never photographed before</span></div>
  </div>
</header>

<div class="controls">
  <span class="ctl-label">Text size</span>
  <div class="seg" role="group" aria-label="Which text size to show">
    <button type="button" data-view="both" aria-pressed="true">Both</button>
    <button type="button" data-view="default" aria-pressed="false">Default</button>
    <button type="button" data-view="ax5" aria-pressed="false">AX5</button>
  </div>
  <span class="ctl-label" style="margin-left:auto">Click any frame to enlarge</span>
</div>

<nav class="rail" aria-label="Screens"><ul>{nav}</ul></nav>
<main>{sections}</main>
</div>

<dialog class="lb"><div class="lb-inner"><img alt=""><p class="lb-cap"></p></div></dialog>

<script>
document.body.dataset.view = "both";
document.querySelectorAll(".seg button").forEach(function (b) {{
  b.addEventListener("click", function () {{
    document.querySelectorAll(".seg button").forEach(function (o) {{
      o.setAttribute("aria-pressed", String(o === b));
    }});
    document.body.dataset.view = b.dataset.view;
  }});
}});

var lb = document.querySelector("dialog.lb");
var lbImg = lb.querySelector("img");
var lbCap = lb.querySelector(".lb-cap");
document.querySelectorAll(".plate").forEach(function (p) {{
  p.addEventListener("click", function () {{
    lbImg.src = p.querySelector("img").src;
    lbImg.alt = p.dataset.cap;
    lbCap.textContent = p.dataset.cap;
    lb.showModal();
  }});
}});
lb.addEventListener("click", function () {{ lb.close(); }});
</script>
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("shots", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--budget-mb", type=float, default=13.0,
                    help="ceiling for the rendered page; the Artifact limit is 16")
    ap.add_argument("--seen", type=Path, default=None,
                    help="file of ids already photographed before this pass, one per line")
    a = ap.parse_args()
    seen = set()
    if a.seen and a.seen.exists():
        seen = {l.strip() for l in a.seen.read_text().splitlines() if l.strip()}
    build(a.shots, a.out, a.budget_mb, seen)


if __name__ == "__main__":
    main()
