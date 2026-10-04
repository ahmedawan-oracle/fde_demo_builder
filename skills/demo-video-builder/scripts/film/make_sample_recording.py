#!/usr/bin/env python3
"""
make_sample_recording.py — a 20 s FICTIONAL screen recording ("Acme Console") plus its pointer telemetry, so the
v5 film pipeline can be run end to end before you have a real capture. Everything in it is invented.

    python make_sample_recording.py            # -> recording.mp4 (1920x1080, 30 fps) + events.jsonl (60 Hz telemetry)
    python make_sample_recording.py --selftest # 1 s render into the temp dir + telemetry / geometry checks (exit 0 ok)

What it contains (the timings clips.example.json expects):
    0.0 – 4.0   notebook, parked at the top          (pointer wandering: the median extractor erases it)
    4.0 – 8.0   notebook, parked 760 px down
    8.0 – 12.0  notebook, parked 1520 px down
    12.0 – 15.0 assistant chat: the question is typed into the composer (12.3 – 14.3 s)
    15.05       the Send control is clicked; the question lifts into a bubble (15.2 s)
    16.5 – 20.0 the answer card arrives under it: one figure ("3") and one sentence — the film's answer beat

The pointer is drawn into the notebook part only (that is what the median stills are for). In the chat part the
presenter's hand lives in events.jsonl instead — the file tools/record_events.py would have written on a real
take: {type:'meta'} then {t, x, y, type:'move'|'down'|'up'} in recording seconds and recording pixels. The scene
redraws it with lib/cursor.js (CURSOR.mount) and the annotate gate accepts the click as evidence for a mark.

Prints the geometry a film needs to quote (claims.json figures[], the composer and the Send control, in source px).
"""
import json
import subprocess
import sys

from PIL import Image, ImageDraw, ImageFont

W, H, FPS, DUR = 1920, 1080, 30, 20.0
BAND = (480, 150, 1400, 900)                     # the scrolling document area: x, y, w, h
QUESTION = "Which regions missed their on-time delivery target last week?"
COMPOSER = (500, 960, 1360, 80)                  # x, y, w, h of the composer box
SEND = (1738, 972, 104, 56)                      # the Send control inside it
ANSWER = (520, 400, 880, 170)                    # the answer card
ANSWER_AT, SEND_AT, TYPE_AT = 16.5, 15.05, 12.3


def font(px, bold=False, mono=False):
    names = (["consola.ttf", "DejaVuSansMono.ttf", "Menlo.ttc"] if mono else
             (["arialbd.ttf", "DejaVuSans-Bold.ttf", "Arial Bold.ttf"] if bold else ["arial.ttf", "DejaVuSans.ttf", "Arial.ttf"]))
    for n in names:
        for d in ("C:/Windows/Fonts/", "/usr/share/fonts/truetype/dejavu/", "/Library/Fonts/", "/System/Library/Fonts/"):
            try:
                return ImageFont.truetype(d + n, px)
            except OSError:
                pass
    return ImageFont.load_default()


F, FB, FM, FH = font(17), font(17, True), font(15, mono=True), font(28, True)
FIG, FA, FS = font(64, True), font(24), font(17)


def chrome(title):
    im = Image.new("RGB", (W, H), "#f5f6f8")
    d = ImageDraw.Draw(im)
    d.rectangle((0, 0, 260, H), fill="#1d2733")
    d.text((28, 30), "ACME CONSOLE", font=FB, fill="#e8eef5")
    for i, n in enumerate(["Home", "Catalog", "Notebooks", "Assistant", "Pipelines", "Settings"]):
        d.text((28, 100 + i * 44), n, font=F, fill="#9fb0c2" if n != title else "#ffffff")
    d.rectangle((260, 0, W, 64), fill="#ffffff")
    d.line((260, 64, W, 64), fill="#dde2e8")
    d.text((290, 22), "Orders workspace  /  " + title, font=F, fill="#3a4654")
    d.rounded_rectangle((W - 170, 16, W - 30, 48), 6, fill="#2f6fde")
    d.text((W - 140, 23), "Run all", font=FB, fill="#ffffff")
    d.rectangle((260, 64, 470, H), fill="#fbfbfc")
    d.text((282, 90), "Contents", font=FB, fill="#3a4654")
    for i, n in enumerate(["1  Load orders", "2  Late deliveries", "3  By region", "4  Chart"]):
        d.text((282, 130 + i * 30), n, font=F, fill="#56606b")
    return im


def document():
    doc = Image.new("RGB", (BAND[2], 2600), "#ffffff")
    d = ImageDraw.Draw(doc)
    y = 30
    for part in range(1, 5):
        d.text((30, y), "Part %d  -  %s" % (part, ["Load orders", "Late deliveries", "By region", "Chart"][part - 1]), font=FH, fill="#1c2430")
        y += 56
        d.text((30, y), "Fictional sample data for the Acme demo. Nothing here is real.", font=F, fill="#4a5563")
        y += 44
        d.rounded_rectangle((20, y, BAND[2] - 20, y + 300), 6, fill="#f4f6f9", outline="#e1e6ec")
        for k in range(12):
            code = ["orders = spark.table(\"acme.orders\")", "late = orders.filter(\"delivered_at > promised_at\")",
                    "by_region = late.groupBy(\"region\").count()", "print(f\"late orders: {late.count():,}\")"][k % 4]
            d.text((40, y + 14 + k * 23), code, font=FM, fill="#23303f")
        y += 330
        d.text((30, y), "late orders: %s   regions over target: %d" % (["1,284", "1,284", "412", "3"][part - 1], part), font=FM, fill="#0b6b3a")
        y += 150
    return doc


def pointer(d, x, y):
    d.polygon([(x, y), (x, y + 22), (x + 6, y + 17), (x + 11, y + 27), (x + 15, y + 25), (x + 10, y + 15), (x + 17, y + 15)],
              fill="#111111", outline="#ffffff")


def answer_card(d, u):
    """The assistant's answer: a light card with one big figure and one sentence; u = 0..1 arrival (rise 10 px + fade)."""
    x, y, w, h = ANSWER
    dy = int(round((1 - u) * 10))
    if u < 1:                                    # a short fade: paint the card over the page at `u` opacity
        card = Image.new("RGB", (w, h + 12), "#f5f6f8")
        cd = ImageDraw.Draw(card)
        _answer_ink(cd, 0, 12 - dy, w, h)
        return card, (x, y - 12)
    _answer_ink(d, x, y - dy, w, h)
    return None, None


def _answer_ink(d, x, y, w, h):
    d.rounded_rectangle((x, y, x + w, y + h), 12, fill="#ffffff", outline="#dde2e8")
    d.text((x + 28, y + 18), "ASSISTANT", font=FS, fill="#6e7f80")
    d.text((x + 28, y + 48), "3", font=FIG, fill="#1c2430")
    d.text((x + 110, y + 62), "regions missed their on-time delivery target", font=FA, fill="#1c2430")
    d.text((x + 110, y + 96), "last week: West, North, Central.", font=FA, fill="#1c2430")
    d.text((x + 110, y + 134), "Grounded in the Orders workspace  ·  synthetic data", font=FS, fill="#6e7f80")


def geometry():
    """Source-px rects the film quotes: the answer figure (claims.json figures[]), the composer and the Send control."""
    x, y = ANSWER[0] + 28, ANSWER[1] + 48
    bb = FIG.getbbox("3")
    return {"figures": [{"id": "regions_over_target", "rect": [x + bb[0], y + bb[1], bb[2] - bb[0], bb[3] - bb[1]], "clip": "answer",
                         "source": "the assistant's answer card: the figure 3 (source px of recording.mp4)"}],
            "composer": list(COMPOSER), "send": list(SEND), "answer_card": list(ANSWER)}


def smooth(u):
    u = max(0.0, min(1.0, u))
    return u * u * (3 - 2 * u)


def telemetry(path):
    """events.jsonl: 60 Hz pointer samples + the Send click, in recording seconds / pixels (the record_events.py shape)."""
    sx, sy = SEND[0] + SEND[2] / 2, SEND[1] + SEND[3] / 2
    park = (1500.0, 820.0)
    rows = [{"type": "meta", "tool": "make_sample_recording.py", "source": [W, H], "hz": 60, "aligned": True, "fictional": True}]
    for i in range(int(DUR * 60) + 1):
        t = round(i / 60.0, 4)
        if t < 12.0:                                        # the wandering pointer the notebook part draws
            x, y = 900 + 300 * ((t * 0.37) % 1), 400 + 220 * ((t * 0.23) % 1)
        elif t < 13.9:
            x, y = park
        elif t < 14.5:                                      # the hand moves to Send
            u = smooth((t - 13.9) / 0.6)
            x, y = park[0] + (sx - park[0]) * u, park[1] + (sy - park[1]) * u
        else:
            x, y = sx, sy
        rows.append({"t": t, "x": round(x, 1), "y": round(y, 1), "type": "move"})
    rows.append({"t": SEND_AT, "x": sx, "y": sy, "type": "down", "button": "left"})
    rows.append({"t": round(SEND_AT + 0.08, 3), "x": sx, "y": sy, "type": "up", "button": "left"})
    rows.sort(key=lambda r: (r.get("t", -1), 0 if r["type"] == "meta" else 1))
    with open(path, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
    return len(rows)


def main(out="recording.mp4", dur=None):
    dur = DUR if dur is None else float(dur)
    nb, chat, doc = chrome("Notebooks"), chrome("Assistant"), document()
    ff = subprocess.Popen(["ffmpeg", "-nostdin", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", "%dx%d" % (W, H),
                           "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-crf", "16", "-pix_fmt", "yuv420p", out], stdin=subprocess.PIPE)
    cx, cy, cw, ch = COMPOSER
    bx, by, bw, bh = SEND
    for i in range(int(dur * FPS)):
        t = i / FPS
        if t < 12:
            im = nb.copy()
            off = 0 if t < 4 else (760 if t < 8 else 1520)
            im.paste(doc.crop((0, off, BAND[2], off + BAND[3])), (BAND[0], BAND[1]))
            d = ImageDraw.Draw(im)
            pointer(d, 900 + int(300 * ((t * 0.37) % 1)), 400 + int(220 * ((t * 0.23) % 1)))
        else:
            im = chat.copy()
            d = ImageDraw.Draw(im)
            d.rounded_rectangle((520, 170, 1300, 240), 10, fill="#ffffff", outline="#e1e6ec")
            d.text((544, 194), "Hi! Ask me anything about the Orders workspace.", font=F, fill="#3a4654")
            d.rounded_rectangle((cx, cy, cx + cw, cy + ch), 12, fill="#ffffff", outline="#cfd6de")
            n = int(max(0.0, t - TYPE_AT) * 30)
            typed = QUESTION[:n]
            sent = t > 15.2
            d.text((526, 988), typed if (n and not sent) else "Ask a question...", font=F, fill="#1c2430" if (n and not sent) else "#9aa4af")
            pressed = SEND_AT <= t < SEND_AT + 0.15
            d.rounded_rectangle((bx, by, bx + bw, by + bh), 8, fill="#245bb8" if pressed else ("#2f6fde" if n else "#b9c4d2"))
            d.text((bx + 28, by + 18), "Send", font=FB, fill="#ffffff")
            if sent:
                d.rounded_rectangle((980, 300, 1840, 360), 10, fill="#2f6fde")
                d.text((1004, 318), QUESTION, font=F, fill="#ffffff")
            if t >= ANSWER_AT:
                u = min(1.0, (t - ANSWER_AT) / 0.25)
                card, pos = answer_card(d, u)
                if card is not None:
                    im.paste(Image.blend(im.crop((pos[0], pos[1], pos[0] + card.size[0], pos[1] + card.size[1])), card, u), pos)
        ff.stdin.write(im.tobytes())
    ff.stdin.close(); ff.wait()
    ev = out.rsplit(".", 1)[0] + ".events.jsonl" if out != "recording.mp4" else "events.jsonl"
    n = telemetry(ev)
    print("wrote", out, "(fictional Acme Console sample, %.0f s) + %s (%d rows)" % (dur, ev, n))
    print("geometry (source px):", json.dumps(geometry()))
    return out, ev


def selftest():
    """A 1 s render into the temp dir: the file decodes at 1920x1080, the telemetry has the meta line, 60 Hz samples and
    one click on the Send control, and the figure rect sits inside the answer card. Prints OK / FAIL, exit 0 / 1."""
    import os
    import tempfile
    tmp = tempfile.mkdtemp(prefix="acme_rec_")
    out, ev = main(os.path.join(tmp, "sample.mp4"), 1.0)
    probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height,nb_frames",
                            "-of", "csv=p=0", out], capture_output=True, text=True).stdout.strip().split(",")
    rows = [json.loads(l) for l in open(ev, encoding="utf-8") if l.strip()]
    meta, clicks = rows[0], [r for r in rows if r["type"] == "down"]
    g = geometry()
    fig, card = g["figures"][0]["rect"], g["answer_card"]
    checks = [
        ("1920x1080 video", probe[:2] == ["1920", "1080"]),
        ("30 frames for 1 s", probe[2] == "30"),
        ("meta line first", meta["type"] == "meta" and meta["source"] == [W, H] and meta["fictional"] is True),
        ("60 Hz samples", sum(1 for r in rows if r["type"] == "move") == int(DUR * 60) + 1),
        ("one Send click inside the control", len(clicks) == 1 and SEND[0] <= clicks[0]["x"] <= SEND[0] + SEND[2] and SEND[1] <= clicks[0]["y"] <= SEND[1] + SEND[3]),
        ("click at the send time", clicks and abs(clicks[0]["t"] - SEND_AT) < 1e-6),
        ("figure rect inside the answer card", card[0] < fig[0] and fig[0] + fig[2] < card[0] + card[2] and card[1] < fig[1] and fig[1] + fig[3] < card[1] + card[3]),
        ("telemetry sorted by time", all(rows[i]["t"] <= rows[i + 1]["t"] for i in range(1, len(rows) - 1))),
    ]
    ok = True
    for name, cond in checks:
        print("  %-38s %s" % (name, "PASS" if cond else "FAIL"))
        ok = ok and bool(cond)
    print("SELFTEST", "OK" if ok else "FAIL", tmp)
    return 0 if ok else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    main(*sys.argv[1:])
