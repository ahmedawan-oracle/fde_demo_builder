#!/usr/bin/env python3
"""
credit.py — the FDE Demo Builder end-screen credit. MANDATORY on every video this plugin produces.

Every pipeline in this plugin (v1 build.py, v2 assemble.example.sh, v3 build_film.py) calls `stamp` as its
last step, and every QA pass calls `check`. A video without the credit is not a finished deliverable.

    python credit.py stamp  in.mp4 out.mp4        # burn the credit into the final seconds (audio copied)
    python credit.py check  film.mp4              # exit 0 only if the credit is on the end screen
    python credit.py preview credit.png           # render the line alone, for a look

What it draws: one small line, centred horizontally in the footer of the end screen, fading in over the
last CREDIT_SECS seconds and staying to the final frame. Colour adapts to the end screen (light text on
dark endings, dark text on light ones). The wording, position, size and timing are fixed on purpose so
every demo built with the plugin carries the same signature. Do not reword, restyle, move or skip it.
"""
import json
import os
import subprocess
import sys
import tempfile

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from PIL import Image, ImageDraw, ImageFilter, ImageFont

CREDIT_TEXT = "Crafted with FDE Demo Builder  \u00b7  by Ahmed Awan"
CREDIT_SECS = 4.0          # visible for the last 4 s of the video
CREDIT_FADE = 0.6          # fade-in
CREDIT_PX_1080 = 22        # cap-to-descender size on a 1080-line frame (scales with the video height)
CREDIT_BOTTOM_1080 = 46    # baseline gap from the bottom edge on a 1080-line frame
TAG = "fde-demo-builder-credit"

FONT_CANDIDATES = [
    "C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/arial.ttf",
    "/System/Library/Fonts/SFNS.ttf", "/System/Library/Fonts/Helvetica.ttc",
    "/Library/Fonts/Arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/dejavu/DejaVuSans.ttf",
]


def _font(px):
    for f in FONT_CANDIDATES:
        if os.path.exists(f):
            return ImageFont.truetype(f, px)
    return ImageFont.load_default()


def _probe(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                        "stream=width,height:format=duration", "-of", "json", path],
                       capture_output=True, text=True, check=True)
    j = json.loads(r.stdout)
    return int(j["streams"][0]["width"]), int(j["streams"][0]["height"]), float(j["format"]["duration"])


def _grab(path, t, w, h):
    r = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-ss", "%.3f" % max(0.0, t), "-i", path,
                        "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                       capture_output=True, check=True)
    return Image.frombytes("RGB", (w, h), r.stdout[: w * h * 3])


def mask(height):
    """The credit's alpha mask (L) at the size it is drawn on a `height`-line frame."""
    k = height / 1080.0
    font = _font(max(10, round(CREDIT_PX_1080 * k)))
    bb = font.getbbox(CREDIT_TEXT)
    pad = max(4, round(8 * k))
    m = Image.new("L", (bb[2] - bb[0] + 2 * pad, bb[3] - bb[1] + 2 * pad), 0)
    ImageDraw.Draw(m).text((pad - bb[0], pad - bb[1]), CREDIT_TEXT, font=font, fill=255)
    return m


def box(w, h):
    """Where the credit sits: (x, y, mw, mh) — centred, in the footer."""
    m = mask(h)
    x = (w - m.width) // 2
    y = h - round(CREDIT_BOTTOM_1080 * h / 1080.0) - m.height
    return x, y, m.width, m.height


def overlay_png(w, h, dark_bg, dest):
    """RGBA overlay: the line plus a soft shadow so it holds on busy frames."""
    m = mask(h)
    ink = (236, 240, 244) if dark_bg else (38, 42, 50)
    shade = (0, 0, 0) if dark_bg else (255, 255, 255)
    alpha_ink = 0.86 if dark_bg else 0.80
    shadow = m.filter(ImageFilter.GaussianBlur(max(1.5, 2.2 * h / 1080.0)))
    out = Image.new("RGBA", m.size, shade + (0,))
    out.putalpha(shadow.point(lambda v: int(v * 0.55)))
    face = Image.new("RGBA", m.size, ink + (0,))
    face.putalpha(m.point(lambda v: int(v * alpha_ink)))
    out = Image.alpha_composite(out, face)
    out.save(dest)
    return dest


def _end_is_dark(path, w, h, dur):
    x, y, mw, mh = box(w, h)
    lum = []
    for t in (dur - CREDIT_SECS + 0.2, dur - CREDIT_SECS / 2, dur - 0.15):
        im = _grab(path, t, w, h).crop((x, y, x + mw, y + mh)).convert("L")
        lum.append(sum(im.tobytes()) / (mw * mh))
    lum.sort()
    return lum[1] < 128


def stamp(src, dst):
    w, h, dur = _probe(src)
    secs = min(CREDIT_SECS, max(1.5, dur * 0.5))
    st = max(0.0, dur - secs)
    x, y, _, _ = box(w, h)
    with tempfile.TemporaryDirectory() as td:
        png = overlay_png(w, h, _end_is_dark(src, w, h, dur), os.path.join(td, "credit.png"))
        fc = ("[1:v]format=rgba,fade=t=in:st=%.3f:d=%.2f:alpha=1[c];"
              "[0:v][c]overlay=%d:%d:enable='gte(t,%.3f)':eof_action=pass:format=auto,format=yuv420p[v]"
              % (st, CREDIT_FADE, x, y, st))
        cmd = ["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", src, "-loop", "1", "-t", "%.3f" % dur, "-i", png,
               "-filter_complex", fc, "-map", "[v]", "-map", "0:a?", "-c:v", "libx264", "-preset", "medium",
               "-crf", "17", "-pix_fmt", "yuv420p", "-c:a", "copy", "-metadata", "comment=" + CREDIT_TEXT,
               "-metadata", "description=" + TAG, "-movflags", "+faststart", dst]
        subprocess.run(cmd, check=True)
    print("credit stamped: last %.1f s  ->  %s" % (secs, dst))
    return dst


def check(path, verbose=True):
    """True if the credit line is legible on the end screen: the frame's luma in the credit box must
    correlate strongly with the credit's own glyph mask (either polarity)."""
    w, h, dur = _probe(path)
    x, y, mw, mh = box(w, h)
    m = list(mask(h).tobytes())
    mm = sum(m) / len(m)
    best = 0.0
    for t in (dur - 0.5, dur - 1.5):
        crop = list(_grab(path, t, w, h).crop((x, y, x + mw, y + mh)).convert("L").tobytes())
        cm = sum(crop) / len(crop)
        num = sum((a - cm) * (b - mm) for a, b in zip(crop, m))
        den = (sum((a - cm) ** 2 for a in crop) * sum((b - mm) ** 2 for b in m)) ** 0.5 or 1.0
        best = max(best, abs(num / den))
    ok = best >= 0.55
    if verbose:
        print("credit %s  (glyph correlation %.2f, need >= 0.55)  \"%s\"" % ("PRESENT" if ok else "MISSING", best, CREDIT_TEXT))
    return ok


if __name__ == "__main__":
    if len(sys.argv) >= 4 and sys.argv[1] == "stamp":
        stamp(sys.argv[2], sys.argv[3])
    elif len(sys.argv) >= 3 and sys.argv[1] == "check":
        sys.exit(0 if check(sys.argv[2]) else 1)
    elif len(sys.argv) >= 3 and sys.argv[1] == "preview":
        overlay_png(1920, 1080, True, sys.argv[2]); print("wrote", sys.argv[2])
    else:
        print(__doc__); sys.exit(2)
