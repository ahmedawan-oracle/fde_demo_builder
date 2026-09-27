# -*- coding: utf-8 -*-
"""extract_clips.py -- screen recording -> real-pixel footage for a clock-driven film (v3).

    python extract_clips.py [recording.mp4] [clips.json] [name ...]     (defaults: recording.mp4, clips.json)

Writes broll/<name>/ (frames, page.jpg, chrome_k.jpg, meta.json) and broll/clips.js (window.CLIPS).

Kinds (all coordinates SOURCE px of a 1920x1080 recording unless marked doc):
  still  {t | win:[t0,t1],n, crop:[x,y,w,h]}  one frame, or the per-pixel MEDIAN of n frames across a window
  seq    {t0, t1, crop}                         real motion, 30 fps
  page   {band:[x,y,w,h], layers:[{t|win,n, off, unzoom:[s,tx,ty]?, patch:[{t, box}]?}], trim, chrome?}
         a tall page stacked from the recording's own parked scroll positions (`off` = doc y of that
         position); later layers skip their top `trim` px so no half-clipped row survives a seam.
         chrome: {} (or {"fix":[...], "layers":[null, {"t":..}, ...]}) also saves the ORIGINAL full screen
         for each parked position (chrome_k.jpg), so the film can open on the whole product screen, keep
         the app's own state (TOC highlight, scrollbar) in sync with the scroll, then push in.

Why medians: the presenter's pointer wanders over every parked position. The text never moves but the
pointer does, so the per-pixel median of frames spread across the window keeps the text pixel-exact and
drops the pointer, a blinking caret and hover states.
Why unzoom: if the recording itself zooms (s, tx, ty), inverting that affine returns a 1.0x frame that
stitches against the untouched frames. Measure s/tx/ty on two landmarks.

`fix` edits run after assembly, in DOC px on pages and clip px on stills/seqs (chrome fixes: frame px):
  {"blur":[x,y,w,h,r]}           privacy only (tokens, emails, other customers) -- ask before masking code
  {"fill":[x,y,w,h,"#hex"]}      erase a baked-in pointer on blank space
  {"word":{"box":[x0,y0,x1,y1],"s":"NEW","font":"narrow","bg":"mode"?,"px":15?}}
                                 repaint one demo-authored word: measures cap height (incl. antialiasing)
                                 and ink colour from the pixels, clears, redraws. Never rewrite real code.
  {"src":{"t":..,"off":..,"band":[x,y],"box":[x,y,w,h]}}   restore a box from another frame (stray caret)
  {"text":{"r":[x,y,w,h],"s":"..","px":..,"font":"arial","fg":"#hex","bg":"#hex"}}
"""
import json, os, subprocess, sys
from io import BytesIO
import numpy as np
from PIL import Image, ImageFilter, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))

if len(sys.argv) > 1 and sys.argv[1] == "--word-ends":
    # python extract_clips.py --word-ends recording.mp4 <t> <x0> <y0> <x1> <y1> [gap_px=5]
    # prints the right edge of every word on a typed line (word-gap projection), for a REVEAL `ends` list
    src, t = sys.argv[2], float(sys.argv[3]); x0, y0, x1, y1 = [int(v) for v in sys.argv[4:8]]
    gap = int(sys.argv[8]) if len(sys.argv) > 8 else 5
    r = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-ss", "%.3f" % t, "-i", src, "-frames:v", "1",
                        "-f", "image2pipe", "-vcodec", "png", "-"], capture_output=True, check=True)
    L = np.asarray(Image.open(BytesIO(r.stdout)).convert("L"))[y0:y1, x0:x1]
    cols = [x0 + i for i in range(L.shape[1]) if (L[:, i] < 150).any()]
    ends, prev = [], None
    for x in cols:
        if prev is not None and x - prev > gap: ends.append(prev + 1)
        prev = x
    if prev is not None: ends.append(prev + 1)
    print(json.dumps({"line": [cols[0] if cols else x0, y0, (prev or x1) + 2, y1], "ends": ends}))
    sys.exit(0)

ARGS = list(sys.argv[1:])
SRC = ARGS.pop(0) if ARGS and ARGS[0].lower().endswith((".mp4", ".mov", ".mkv")) else os.path.join(HERE, "recording.mp4")
CFG = ARGS.pop(0) if ARGS and ARGS[0].lower().endswith(".json") else os.path.join(HERE, "clips.json")
OUTDIR = os.path.join(HERE, "broll")
FPS = 30
CLIPS = json.load(open(CFG, encoding="utf-8"))
_W = os.path.exists("C:/Windows/Fonts")
FONTS = {"arial": "C:/Windows/Fonts/arial.ttf", "arialbd": "C:/Windows/Fonts/arialbd.ttf",
         "narrow": "C:/Windows/Fonts/ARIALN.TTF", "narrowbd": "C:/Windows/Fonts/ARIALNB.TTF",
         "mono": "C:/Windows/Fonts/consola.ttf"} if _W else {
         "arial": "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "arialbd": "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
         "narrow": "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed.ttf", "narrowbd": "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed-Bold.ttf",
         "mono": "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"}
_cache = {}


def grab(t):
    t = round(float(t), 3)
    if t not in _cache:
        r = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-ss", "%.3f" % t, "-i", SRC, "-frames:v", "1",
                            "-f", "image2pipe", "-vcodec", "png", "-"], capture_output=True, check=True)
        _cache[t] = Image.open(BytesIO(r.stdout)).convert("RGB")
    return _cache[t].copy()


def frame_for(L):
    """One layer's frame: a single time, or the per-pixel median across a window."""
    if "win" in L:
        t0, t1 = L["win"]; n = int(L.get("n", 5))
        ts = [t0 + 0.06 + (t1 - t0 - 0.12) * k / max(1, n - 1) for k in range(n)]
        arr = np.stack([np.asarray(grab(t), np.uint8) for t in ts])
        im = Image.fromarray(np.median(arr, axis=0).astype(np.uint8))
    else:
        im = grab(L["t"])
    for p in L.get("patch", []):                         # replace a box with the same box from another time
        x, y, w, h = p["box"]; im.paste(grab(p["t"]).crop((x, y, x + w, y + h)), (x, y))
    if L.get("unzoom"):                                  # invert x' = s*x + tx, y' = s*y + ty
        s, tx, ty = L["unzoom"]
        im = im.transform(im.size, Image.AFFINE, (s, 0, tx, 0, s, ty), resample=Image.BICUBIC)
    return im


def apply_fixes(im, fixes):
    d = ImageDraw.Draw(im)
    for f in fixes:
        if "blur" in f:
            x, y, w, h = [int(v) for v in f["blur"][:4]]; r = f["blur"][4] if len(f["blur"]) > 4 else 5
            im.paste(im.crop((x, y, x + w, y + h)).filter(ImageFilter.GaussianBlur(r)), (x, y))
        elif "src" in f:
            # restore a doc box from another frame/scroll position (e.g. before a stray click left a caret)
            S = f["src"]; x, y, w, h = S["box"]; bx, by = S["band"][:2]
            sy = y - S["off"] + by; sx = x + bx
            im.paste(grab(S["t"]).crop((sx, sy, sx + w, sy + h)), (x, y))
        elif "fill" in f:
            x, y, w, h = [int(v) for v in f["fill"][:4]]; c = f["fill"][4]
            d.rectangle((x, y, x + w - 1, y + h - 1), fill=c)
        elif "word" in f:
            # repaint one word: measure its cap height and ink on the page, clear it, draw the replacement
            W = f["word"]; x0, y0, x1, y1 = W["box"]
            L = im.convert("L")
            ink = [(x, y) for y in range(y0, y1) for x in range(x0, x1) if L.getpixel((x, y)) < 150]
            edge = [(x, y) for y in range(y0, y1) for x in range(x0, x1) if L.getpixel((x, y)) < 215]   # include antialiasing
            top = min(p[1] for p in edge); base = max(p[1] for p in edge) + 1
            dark = sorted(ink, key=lambda p: L.getpixel(p))[:max(4, len(ink) // 6)]
            fg = tuple(int(sum(im.getpixel(p)[c] for p in dark) / len(dark)) for c in range(3))
            bg = im.getpixel((max(0, x0 - 4), (y0 + y1) // 2))
            if W.get("bg") == "mode":                    # the box's own most common colour (row highlights, tight words)
                from collections import Counter
                bg = Counter(im.getpixel((x, y)) for y in range(y0, y1) for x in range(x0, x1)).most_common(1)[0][0]
            d.rectangle((x0 - 1, y0 - 1, x1 + 1, y1 + 1), fill=bg)
            cap = base - top
            font = ImageFont.truetype(FONTS[W.get("font", "narrow")], int(W["px"]) if W.get("px") else max(6, int(round(cap / 0.716))))
            bb = font.getbbox(W["s"])
            d.text((x0 - bb[0] + W.get("dx", 0), top - bb[1]), W["s"], font=font, fill=fg)
        elif "text" in f:
            T = f["text"]; x, y, w, h = [int(v) for v in T["r"]]
            bg = T.get("bg") or im.getpixel((max(0, x - 3), y + h // 2))
            d.rectangle((x, y, x + w - 1, y + h - 1), fill=bg)
            font = ImageFont.truetype(FONTS[T.get("font", "arial")], int(T["px"]))
            d.text((x + T.get("dx", 0), y + T.get("dy", 0)), T["s"], font=font, fill=T.get("fg", "#1b1b1b"))
    return im


def out_dir(name):
    p = os.path.join(OUTDIR, name); os.makedirs(p, exist_ok=True)
    for f in os.listdir(p):
        if f.endswith(".jpg"): os.remove(os.path.join(p, f))
    return p


def do_still(c):
    p = out_dir(c["name"]); x, y, w, h = c["crop"]
    im = apply_fixes(frame_for(c).crop((x, y, x + w, y + h)), c.get("fix", []))
    im.save(os.path.join(p, "f_001.jpg"), quality=94)
    return {"kind": "still", "frames": 1, "fps": FPS, "w": w, "h": h, "crop": c["crop"]}


def do_seq(c):
    p = out_dir(c["name"]); x, y, w, h = c["crop"]
    t0, t1 = float(c["t0"]), float(c["t1"]); n = int(round((t1 - t0) * FPS))
    r = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-ss", "%.3f" % t0, "-i", SRC, "-t", "%.3f" % (t1 - t0),
                        "-vf", "fps=%d" % FPS, "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True, check=True)
    fs = 1920 * 1080 * 3; got = min(n, len(r.stdout) // fs)
    for k in range(got):
        im = Image.frombytes("RGB", (1920, 1080), r.stdout[k * fs:(k + 1) * fs]).crop((x, y, x + w, y + h))
        apply_fixes(im, c.get("fix", [])).save(os.path.join(p, "f_%03d.jpg" % (k + 1)), quality=92)
    return {"kind": "seq", "frames": got, "fps": FPS, "dur": round(got / FPS, 3), "w": w, "h": h, "crop": c["crop"], "t0": t0}


def do_page(c):
    p = out_dir(c["name"]); bx, by, bw, bh = c["band"]
    doc_h = bh + max(int(L["off"]) for L in c["layers"])
    page = Image.new("RGB", (bw, doc_h), tuple(c.get("paper", [255, 255, 255])))
    trim = int(c.get("trim", 30))
    for k, L in enumerate(c["layers"]):
        band = frame_for(L).crop((bx, by, bx + bw, by + bh))
        cut = trim if k else 0
        page.paste(band.crop((0, cut, bw, bh)), (0, int(L["off"]) + cut))
    page = apply_fixes(page, c.get("fix", []))
    page.save(os.path.join(p, "page.jpg"), quality=94)
    meta = {"kind": "page", "frames": 1, "fps": FPS, "w": bw, "h": doc_h, "band": c["band"],
            "offsets": [int(L["off"]) for L in c["layers"]], "bg": c.get("bg", "#fff")}
    if "chrome" in c:
        # the original, full product screen around the scroll area (nav, header, table of contents),
        # one per parked scroll position so the app's own state (TOC highlight) follows the scroll
        C = c["chrome"] or {}; over = C.get("layers", [])
        for k, L in enumerate(c["layers"]):
            spec = over[k] if k < len(over) and over[k] else L
            apply_fixes(frame_for(spec), C.get("fix", [])).save(os.path.join(p, "chrome_%d.jpg" % k), quality=93)
        meta["chrome"] = len(c["layers"])
    return meta


if __name__ == "__main__":
    want = set(ARGS); metas = {}
    for c in CLIPS:
        mp = os.path.join(OUTDIR, c["name"], "meta.json")
        if want and c["name"] not in want:
            if os.path.exists(mp): metas[c["name"]] = json.load(open(mp))
            continue
        m = {"still": do_still, "seq": do_seq, "page": do_page}[c["kind"]](c)
        if c.get("bg"): m["bg"] = c["bg"]
        m["shows"] = c.get("shows", "")
        json.dump(m, open(mp, "w"), indent=1); metas[c["name"]] = m
        print("%-8s %-5s %4d fr  %4dx%-5d %s" % (c["name"], c["kind"], m["frames"], m["w"], m["h"], c.get("shows", "")[:60]))
    with open(os.path.join(OUTDIR, "clips.js"), "w", encoding="utf-8") as f:
        f.write("/* generated by extract_clips.py -- do not edit */\nwindow.CLIPS = " + json.dumps(metas, indent=1) + ";\n")
    print("broll/clips.js:", len(metas), "clips")
