#!/usr/bin/env python3
"""
make_sample_recording.py — a 16 s FICTIONAL screen recording ("Acme Console") so the v3 film pipeline can
be run end to end before you have a real capture. Everything in it is invented.

    python make_sample_recording.py            # -> recording.mp4 (1920x1080, 30 fps)

What it contains (the timings clips.example.json expects):
    0.0 – 4.0   notebook, parked at the top          (pointer wandering: the median extractor erases it)
    4.0 – 8.0   notebook, parked 760 px down
    8.0 – 12.0  notebook, parked 1520 px down
    12.0 – 16.0 assistant chat: a question is typed into the composer, then sent
"""
import subprocess
import sys

from PIL import Image, ImageDraw, ImageFont

W, H, FPS, DUR = 1920, 1080, 30, 16.0
BAND = (480, 150, 1400, 900)                     # the scrolling document area: x, y, w, h
QUESTION = "Which regions missed their on-time delivery target last week?"


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


def main(out="recording.mp4"):
    nb, chat, doc = chrome("Notebooks"), chrome("Assistant"), document()
    ff = subprocess.Popen(["ffmpeg", "-nostdin", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", "%dx%d" % (W, H),
                           "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-crf", "16", "-pix_fmt", "yuv420p", out], stdin=subprocess.PIPE)
    for i in range(int(DUR * FPS)):
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
            d.rounded_rectangle((500, 960, 1860, 1040), 12, fill="#ffffff", outline="#cfd6de")
            n = int(max(0.0, t - 12.3) * 30)
            d.text((526, 988), QUESTION[:n] if n else "Ask a question...", font=F, fill="#1c2430" if n else "#9aa4af")
            if t > 15.2:
                d.rounded_rectangle((980, 300, 1840, 360), 10, fill="#2f6fde")
                d.text((1004, 318), QUESTION, font=F, fill="#ffffff")
        ff.stdin.write(im.tobytes())
    ff.stdin.close(); ff.wait()
    print("wrote", out, "(fictional Acme Console sample, %.0f s)" % DUR)


if __name__ == "__main__":
    main(*sys.argv[1:])
