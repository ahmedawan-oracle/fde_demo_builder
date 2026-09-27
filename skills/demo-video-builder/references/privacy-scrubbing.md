# Privacy scrubbing

> **Mask private data, not the product.** Blur secrets, personal data and other customers — but leave real
> code, API names and tool labels as recorded unless the owner asks otherwise (many reviewers want the
> product untouched). v3 repaints demo-authored words instead of blurring them (`references/real-pixel-footage.md`).

Real screen recordings leak sensitive data everywhere. **Every shipped frame must be clean.** This is the
single most common way a demo video goes out with something it shouldn't. Treat it as a hard gate, not a
nicety.

## The leak checklist (scan the whole recording for each)

- **Address bar** — full URLs, dev/host prefixes, and especially `?token=`/`id_token=`/`access_token=`
  JWTs and tenancy/account identifiers embedded in the URL.
- **Bookmarks bar** — personal/work bookmarks, ticket numbers, internal tool names.
- **Browser extension badges** — e.g. a grammar/AI extension icon in a text field or toolbar.
- **Tabs** — other open tabs' titles; "update available" banners.
- **Usernames / emails / avatars** — app header, account menu, chat composer, OS taskbar.
- **Internal names typed into fields** — engineer names, internal project/dataset names in a
  Description/Name/Instructions box (these are easy to miss because they're *content*, not chrome).
- **Other customers / other data** — list pages that show unrelated agents, schemas, or customer names.
  Prefer to **avoid** these screens entirely rather than mask a dozen rows.
- **OS chrome** — taskbar with app icons, notifications, clock revealing timezone/location.

## Techniques

### 1) Cover the browser chrome with a color-matched bar (preferred)
Keeps the app at native scale. Draw a filled box over the top strip:
```
drawbox=x=0:y=0:w=1920:h=98:color=0x111318:t=fill   # dark, for dark app headers
drawbox=x=0:y=0:w=1920:h=98:color=0xFFFFFF:t=fill    # white, for light UIs
```
Pick the color to match the app's top edge so the bar reads as part of the window, not a black letterbox.
`build.py` does this via each beat's `chrome=` setting.

### 2) Mask a specific leak with a filled box
For residual leaks *inside* the content (a subtitle line with an internal name, an extension badge, a
username in a rail):
```
drawbox=x=216:y=214:w=756:h=36:color=white:t=fill     # match the local background color
```
White over a white area / a matching hex over a colored area is invisible — it just looks like empty space.

### 3) Time-gated masks (critical when the page scrolls)
A fixed-position box is only correct while the leak stays at that position. If the page **scrolls mid-beat**,
a fixed box will later cover the wrong content. Gate the mask to the exact window where the leak is visible:
```
drawbox=x=236:y=330:w=1220:h=88:color=white:t=fill:enable='between(t,5.5,12)'
```
Times are **concat-relative seconds** (after your spans are joined, before time-fit). In `demo_config.py`
use `box(..., enable="between(t,5.5,12)")`.

### 4) Avoidance beats crop
The cleanest fix is often not to record/keep the leaky frame at all. Restructure your `spans` to skip the
unscrolled moment where a name is visible, or the list page that shows other customers. In practice: end a
"create" beat *before* the Description field renders the typed internal name; start the next span *after*
the page has scrolled past it.

## Verify (do not trust that it worked)
After building, sample frames across the whole video and **look**:
```
ffmpeg -v error -ss <t> -i out/demo.mp4 -frames:v 1 -q:v 3 out/qa/check_<t>.jpg
```
Check the beginning, middle, and end of every beat, and any moment the UI scrolls or a field gets focus.
The `demo-qa-reviewer` agent automates this sweep. Re-verify after every rebuild — masks are in native
coordinates and a framing change can shift what's visible.
