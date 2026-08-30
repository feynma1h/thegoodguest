#!/usr/bin/env python3
"""Every candidate view of every box, ranked, with the selector's own pick.

Judgment aid. Uses the shipped functions — box_visibility, box_is_whole,
frame_sharpness, select_box_whole_views — so what is drawn IS what the selector
decided, not a reimplementation that can drift from it.

    python3 tools/candidate_views.py <capture_dir> <room_json> [out_dir]

`capture_dir` holds bundle.pb and frames/NNNNNN.jpg; `room_json` is the
CapturedRoom the scene was built from. Both survive after the captures bucket
sweeps at 24 h, which is why this takes paths rather than a scene id.

Green = the selector's pick, amber = whole but not chosen, grey = cut off at
the image edge. It draws EVERY candidate including the tail, because the
question it exists to answer is whether anything good was passed over.
""" 
import os, sys
import numpy as np
from PIL import Image, ImageDraw
_here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_here, "..", "services", "perception-obj"))
sys.path.insert(0, os.path.join(_here, "..", "packages", "schemas"))
os.environ["PERCEPTION_BOX_WHOLE_VIEWS"]="1"
from roomstudio_schemas import CaptureBundle
import roomplan_room, census_sampling as cs, box_placement as bp

O   = sys.argv[1] if len(sys.argv) > 1 else "outputs/capture-90eebfc4"
ROOM= sys.argv[2] if len(sys.argv) > 2 else "outputs/selection-eyes/room.json"
OUT = sys.argv[3] if len(sys.argv) > 3 else "outputs/candidates-all"
os.makedirs(OUT, exist_ok=True)
b=CaptureBundle(); b.ParseFromString(open(O+"/bundle.pb","rb").read())
room=roomplan_room.parse_captured_room(open(ROOM,"rb").read())
boxes=list(room.objects); frames=list(b.frames)
V,_=cs.box_visibility(frames,boxes)

def rgb(fr):
    try: return np.asarray(Image.open(f"{O}/frames/{fr.frame_index:06d}.jpg").convert("RGB"))
    except Exception: return None

# the selector's own decision, via the shipped function
picks,info = cs.select_box_whole_views(frames,boxes,V,get_rgb=rgb)
chosen={f"box_{bi:02d}": info["box_whole_views"][f"box_{bi:02d}"]["frame_index"]
        for bi in range(len(boxes)) if f"box_{bi:02d}" in info["box_whole_views"]}
sharp={f.frame_index: cs.frame_sharpness(rgb(f)) for f in frames}
vals=np.array([v for v in sharp.values() if v==v])
bar=info["sharpness_bar"]

TW,TH,COLS,PAD,TOP,CAP=250,250,7,6,64,30
for bi,bx in enumerate(boxes):
    bid=f"box_{bi:02d}"; cat=getattr(bx,"category","?")
    cand=sorted((fi for fi in range(len(frames)) if V[fi,bi]>0), key=lambda fi:(-V[fi,bi],fi))
    tiles=[]
    for rank,fi in enumerate(cand,1):
        fr=frames[fi]
        im=Image.open(f"{O}/frames/{fr.frame_index:06d}.jpg").convert("RGB")
        hull,_=bp.project_box_footprint(bx,fr.intrinsics,fr.camera_pose)
        if hull is None: continue
        hu=np.asarray(hull,float)
        x0,y0,x1,y1=hu[:,0].min(),hu[:,1].min(),hu[:,0].max(),hu[:,1].max()
        mx,my=0.30*(x1-x0),0.30*(y1-y0)
        c=im.crop((max(0,int(x0-mx)),max(0,int(y0-my)),min(im.width,int(x1+mx)),min(im.height,int(y1+my))))
        if c.width<30 or c.height<30: continue
        c=c.rotate(-90,expand=True); c.thumbnail((TW,TH))
        t=Image.new("RGB",(TW,TH),(240,240,240)); t.paste(c,((TW-c.width)//2,(TH-c.height)//2))
        whole=cs.box_is_whole(bx,fr)
        s=sharp.get(fr.frame_index,float("nan"))
        pct=100*(vals<s).mean() if s==s else -1
        tiles.append((rank,fr.frame_index,whole,pct,t))
    rows=(len(tiles)+COLS-1)//COLS
    sh=Image.new("RGB",(COLS*TW+(COLS+1)*PAD, TOP+rows*(TH+CAP)+PAD),(250,250,250))
    d=ImageDraw.Draw(sh)
    d.text((10,10),f"{bid}  {cat}  —  ALL {len(tiles)} candidate views, ranked by the selector's score",fill=(20,20,20))
    d.text((10,30),f"GREEN = chosen by the algorithm (frame {chosen.get(bid)}).  AMBER = whole but not chosen.  GREY = cut off at the image edge.",fill=(110,110,110))
    d.text((10,46),f"'soft' = below this capture's median sharpness (bar {bar:.0f}).",fill=(110,110,110))
    for k,(rank,fidx,whole,pct,t) in enumerate(tiles):
        r,c_=divmod(k,COLS); x=PAD+c_*(TW+PAD); y=TOP+r*(TH+CAP)
        sh.paste(t,(x,y))
        if fidx==chosen.get(bid): col,w=(25,130,60),4
        elif whole: col,w=(205,140,30),2
        else: col,w=(200,200,200),1
        d.rectangle([x-2,y-2,x+TW+2,y+TH+2],outline=col,width=w)
        soft="" if pct<0 else ("  soft" if pct< (100*(vals<bar).mean()) else "")
        d.text((x+3,y+TH+4),f"#{rank} f{fidx}  {'whole' if whole else 'CUT'}{soft}",fill=col)
        d.text((x+3,y+TH+16),f"sharp p{pct:.0f}" if pct>=0 else "",fill=(140,140,140))
    p=f"{OUT}/all_{bid}_{cat}.png"; sh.save(p)
    print(f"  {bid} {cat:10} {len(tiles):>3} candidates, chosen f{chosen.get(bid)} -> {p.split('/')[-1]}")
