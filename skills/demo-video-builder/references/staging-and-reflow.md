# Staging and reflow — `lib/stage.js` (`STAGE`)

A real recording looks produced when the screen sits in a frame and the vertical cut follows the action —
without a single product pixel being recoloured. `STAGE.mount` stages the footage lane; `STAGE.reflow`
writes the per-frame crop rects a 9:16, 1:1 or 4:5 export follows. Node CLI with `--selftest` and `--help`
(exit 0 ok · 1 findings · 2 usage).

## Staging — the screen in a frame

```js
const stage = F.stage ? STAGE.mount($('#stage'), F.stage) : null;   // {wallpaper:'mesh', padding:64, bezel:'window', title:'Acme Console'}
// in applyCam, after CAM.resolve: if (stage) pose = stage.pose({ s, cx, cy });
```

`STAGE.mount(stageEl, {wallpaper, padding, radius, shadow, bezel, title})` puts a wallpaper BEHIND `#camera`
and wraps `#clipWrap` in a `#stageFrame` inside `#camera`. The lane keeps its 1280x720 box and gets one
uniform scale `k = min((1280 − 2p)/1280, (720 − 2p − b)/720)` (p = 64, window bezel b = 34 → k = 0.775).
Uniform scale is what the camera already does to the recording; nothing is recoloured, warped or redrawn.

| Option | Values | Notes |
|---|---|---|
| `wallpaper` | `navy-gradient` (radial — linear bands under H.264), `mesh` (four fixed radial pools of the palette at 14–22 %), `solid` | all static |
| `padding` | 48–96 px (default 64) | breathing room around the screen |
| `radius` / `shadow` | 14 px / `0 30px 80px rgba(0,0,0,.45)` | the house card level |
| `bezel` | `none`, `hairline` (1 px outline), `window` (34 px neutral bar: hollow dots + optional title pill — no platform trade dress) | |

Camera: author poses in footage space as before and map them — `stage.pose({s, cx, cy})` →
`{s, F.x + k·cx, F.y + k·cy}`. `stage.full()` = `{s: 1/k, cx: 640, cy: 360}` is the pose where the footage
fills the stage, so "open staged, push to the whole screen" is the natural establishing move and still obeys
*full screen first, then the zoom*. Zoom budget: multiply the measured upsample by `k` (staging is gentler on
the recording's pixels). A scene that stages the lane sets `#clipWrap` visible by design; the lint exempts it
from `fullframe_overlay_starts_visible` when `STAGE.mount(` is present.

## Reflow — vertical and square cuts that follow the action

```
node lib/stage.js --reflow 9:16 --track out/camera_curves.json --total 92.5 [--fps 30] [--source 1920x1080] --out out/stage_reflow_9x16.json
python tools/export.py --preset vertical_9x16 --reflow out/stage_reflow_9x16.json
```

`STAGE.reflow('9:16' | '1:1' | '4:5', {follow, total, fps 30, tau 0.6, dead 0.18, source})` returns crop rects
on the 1280x720 stage per frame (9:16 → 405x720, 1:1 → 720x720, 4:5 → 576x720; `export.py` multiplies by 1.5 for
the 1920x1080 master and adds a `portrait_4x5` 1080x1350 preset). The window follows a track like a camera
operator: first-order follow with τ = 0.6 s (62 % of the way in 0.6 s, 95 % in 1.8 s), an 18 % dead zone of
the crop width, hard stage clamps; a jump of the subject across the whole screen moves the window at most
~53 px per frame. Deterministic frame by frame from t = 0.

Tracks (`STAGE.track(any, {source})`): `[{t, x, y}]` stage px (cursor or caret), `out/camera_curves.json`
(a pushed-in camera → the frame centre; at scale ≈ 1 → the pose's own cx, cy), or recording-px events
(`events.jsonl`) with `source: [1920, 1080]`. Safe zones per format: title-safe 10 %; player-UI bands 9:16
top 10 % / bottom 20 %, 4:5 6 % / 12 %, 1:1 bottom 10 % — captions for a reflowed cut sit inside
`reflow.safe.text`, and `export.py`'s captions note quotes it. `?guides` draws the zones in a `#stageGuides`
layer (preview only, never rendered). `STAGE.rectAt(reflow, t)`, `STAGE.cropOf(f)`, `STAGE.safeOf(f, crop)` are
the pure helpers the selftest checks.

## Rules

- Staging is a frame, not a grade: the lane's pixels pass through one uniform scale and nothing else.
- The bezel is neutral — no traffic-light colours, no platform chrome, a fictional title at most.
- Reflow follows a track you can name (cursor, caret, camera); it never guesses a subject from the pixels.
- Nested scaled layers (the staged frame, a PiP arriving) are exactly the case the renderer's compositor-sync
  flags exist for; leave `RENDER_COMPOSITOR_SYNC` on when a scene stages the lane.
- Reflow constants (τ 0.6 s, dead zone 18 %) come from camera-operator practice; validate them against a real
  cursor track before relying on them for a client cut.
