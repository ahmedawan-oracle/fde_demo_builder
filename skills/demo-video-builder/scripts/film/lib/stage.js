/* stage.js — STAGE: screen staging outside the footage lane, and aspect reflow for vertical / square cuts.

   WHY. A raw 1920x1080 recording shown edge to edge reads as "a screen recording". A produced film sets the
   screen inside a frame: a wallpaper behind it, 48–96 px of breathing room, soft corners, one deep shadow and —
   when the recording was cropped to a content pane — a neutral title bar so the eye reads "a window". None of
   that may touch the recording's pixels: the footage lane (#clipWrap, lib/footage.js) is only moved and scaled
   UNIFORMLY, which the camera does to it anyway. Nothing is recoloured, grained, warped or redrawn; the frame,
   the shadow and the bezel are our own elements around it, and the wallpaper is a sibling of #camera.

   GEOMETRY (1280x720 stage). With padding p and bezel height b (0 for 'none' and 'hairline', 34 px for 'window'):
     k  = min((1280 - 2p) / 1280, (720 - 2p - b) / 720)        uniform footage scale (p = 64, b = 34 → k = 0.775)
     frame = { x: (1280 - 1280k) / 2, y: (720 - 720k - b) / 2, w: 1280k, h: 720k + b }   centred on the stage
     footage rect F = { x: frame.x, y: frame.y + b, w: 1280k, h: 720k }
   #clipWrap keeps its native 1280x720 box and gets transform: translate(0, b) scale(k) with origin 0 0 inside the
   frame, so every lib that writes into the lane (footage.js stills/pages/reveals, camera.js poses) keeps working
   in its own 1280x720 coordinates. STAGE.pose(p) maps a footage-space camera pose onto the staged stage:
     s' = s,  cx' = F.x + k·cx,  cy' = F.y + k·cy            (the pose ladder and dwell rules are unchanged)
   STAGE.full() = { s: 1/k, cx: 640, cy: 360 } is the pose at which the footage fills the stage edge to edge —
   "open staged, push to the whole screen" is the natural establishing move. Zoom budget: the upsample that
   CAM.budget measures must be multiplied by k (a staged push is gentler on the recording's pixels).

   WALLPAPERS (all static, all deterministic): 'navy-gradient' = a radial fall-off from #204A56 at the top centre
   to #082A34 (radial, never linear: a full-frame linear gradient bands under H.264); 'mesh' = four soft radial
   pools of the palette (mint / gold / coral / navy2) at fixed positions, blended at 14–22 % over the navy, the
   look of a desktop wallpaper without a photograph; 'solid' = one colour (default #082A34).

   REFLOW. A 9:16, 1:1 or 4:5 cut is a crop of the finished 16:9 picture. Instead of a centre crop, the crop
   window follows a track — the cursor / caret track from the recording, or the camera's own subject — like a
   camera operator: a first-order follow with time constant tau = 0.6 s (62 % of the way in 0.6 s, 95 % in 1.8 s),
   a dead zone of 18 % of the crop width in which the window does not move, and the stage bounds as hard clamps.
   Evaluated frame by frame from t = 0 at `fps` (default 30), so the same track always gives the same rects.
     STAGE.reflow('9:16', { follow: track, total: END })  →  { format, out: [1080, 1920], stage: [1280, 720],
                                                               crop: [405, 720], rects: [{t, x, y, w, h}], safe }
   tools/export.py reads this as out/stage_reflow.json (one file per format) and crops the mastered film with
   it instead of its edge-energy centre. Rects are in STAGE px; multiply by 1.5 for the 1920x1080 master.
   `track` may be [{t, x, y}] (stage/screen px), camera.js's out/camera_curves.json ({shots:[{samples}]}), or
   a cursor-event list [{t, x, y}] in recording px with {source: [1920, 1080]}. When the camera is pushed in
   (s > 1) its subject is the frame centre; when it is at 1.0 the pose's own cx, cy is the subject.

   SAFE ZONES per format (fractions of the crop): title-safe = 10 % inset on every edge; vertical formats add
   the bands where social players draw their own UI — 9:16 top 10 % / bottom 20 %, 4:5 top 6 % / bottom 12 %,
   1:1 bottom 10 %. Captions and lower thirds for a reflowed cut must sit inside safe.text. In the browser,
   ?guides draws these as dashed outlines in a #stageGuides layer (never in a render).

   Node CLI (no browser):
     node lib/stage.js --reflow 9:16 --track out/camera_curves.json --total 92.5 [--fps 30] [--out out/stage_reflow.json]
     node lib/stage.js --reflow 1:1 --track events.json --source 1920x1080 --total 60
     node lib/stage.js --selftest        exit 0 ok · 1 findings · 2 usage */
(function (root) {
  'use strict';
  const STAGE_W = 1280, STAGE_H = 720;
  const PAL = { navy: '#082A34', navy2: '#204A56', ink: '#E9F3F9', cream: '#ECDEC3', coral: '#E56B5E', mint: '#81A9AB', gold: '#E8C874' };
  const FORMATS = { '16:9': 16 / 9, '9:16': 9 / 16, '1:1': 1, '4:5': 4 / 5 };
  const OUT_PX = { '16:9': [1920, 1080], '9:16': [1080, 1920], '1:1': [1080, 1080], '4:5': [1080, 1350] };
  const UI_BANDS = { '16:9': { top: 0, bottom: 0 }, '9:16': { top: 0.10, bottom: 0.20 }, '1:1': { top: 0, bottom: 0.10 }, '4:5': { top: 0.06, bottom: 0.12 } };
  const DEFAULTS = { wallpaper: 'navy-gradient', color: PAL.navy, padding: 64, radius: 14, shadow: '0 30px 80px rgba(0,0,0,.45)', bezel: 'none', bezelHeight: 34, title: '', inset: 0 };
  const REFLOW = { fps: 30, tau: 0.6, dead: 0.18, titleSafe: 0.10 };
  const clamp = (x, a, b) => Math.max(a, Math.min(b, x));
  const px = v => v.toFixed(2) + 'px';

  /* ---------- geometry (pure) ---------- */
  function geometry(o) {
    o = Object.assign({}, DEFAULTS, o || {});
    const p = clamp(o.padding, 0, 300), b = o.bezel === 'window' ? o.bezelHeight : 0;
    const k = Math.min((STAGE_W - 2 * p) / STAGE_W, (STAGE_H - 2 * p - b) / STAGE_H);
    const fw = STAGE_W * k, fh = STAGE_H * k + b;
    const frame = { x: (STAGE_W - fw) / 2, y: (STAGE_H - fh) / 2, w: fw, h: fh };
    const footage = { x: frame.x, y: frame.y + b, w: STAGE_W * k, h: STAGE_H * k };
    return { k, bezel: b, padding: p, frame, footage, radius: o.radius, inset: o.inset };
  }
  /* footage-space camera pose → staged pose (same s; centre moved into the footage rect) */
  function poseOf(geo, p) { return { s: p.s, cx: geo.footage.x + geo.k * p.cx, cy: geo.footage.y + geo.k * p.cy }; }
  function fullOf(geo) { return { s: 1 / geo.k, cx: STAGE_W / 2, cy: STAGE_H / 2 }; }

  /* ---------- wallpaper css (pure) ---------- */
  function wallpaperCSS(kind, color) {
    const c = color || PAL.navy;
    if (kind === 'solid') return c;
    if (kind === 'mesh') return [
      'radial-gradient(ellipse 46% 42% at 18% 22%, rgba(129,169,171,.22), rgba(129,169,171,0) 70%)',
      'radial-gradient(ellipse 40% 38% at 82% 18%, rgba(232,200,116,.14), rgba(232,200,116,0) 70%)',
      'radial-gradient(ellipse 48% 44% at 78% 84%, rgba(229,107,94,.14), rgba(229,107,94,0) 70%)',
      'radial-gradient(ellipse 60% 55% at 30% 90%, rgba(32,74,86,.9), rgba(32,74,86,0) 70%)',
      c].join(',');
    return 'radial-gradient(ellipse 85% 70% at 50% 8%, ' + PAL.navy2 + ' 0%, ' + c + ' 72%)';   // navy-gradient
  }

  /* ---------- mount (DOM) ---------- */
  let mounted = null;
  function mount(stageEl, o) {
    o = Object.assign({}, DEFAULTS, o || {});
    const doc = stageEl.ownerDocument, geo = geometry(o);
    const camera = stageEl.querySelector('#camera'), wrap = (o.target && stageEl.querySelector(o.target)) || stageEl.querySelector('#clipWrap');
    if (!camera || !wrap) throw new Error('stage.js: mount needs #camera and #clipWrap inside the stage element');
    // wallpaper: a sibling BEHIND #camera (z 0), never inside the lane
    let wall = stageEl.querySelector('#stageWall');
    if (!wall) { wall = doc.createElement('div'); wall.id = 'stageWall'; stageEl.insertBefore(wall, stageEl.firstChild); }
    wall.style.cssText = 'position:absolute;inset:0;z-index:0;pointer-events:none;background:' + wallpaperCSS(o.wallpaper, o.color);
    // frame: wraps the lane inside #camera so the camera still moves frame + footage as one surface
    let frame = camera.querySelector('#stageFrame');
    if (!frame) { frame = doc.createElement('div'); frame.id = 'stageFrame'; wrap.parentNode.insertBefore(frame, wrap); frame.appendChild(wrap); }
    frame.style.cssText = 'position:absolute;overflow:hidden;left:' + px(geo.frame.x) + ';top:' + px(geo.frame.y) + ';width:' + px(geo.frame.w) + ';height:' + px(geo.frame.h) +
      ';border-radius:' + o.radius + 'px;box-shadow:' + o.shadow + ';background:' + PAL.navy2 + (o.bezel === 'hairline' ? ';outline:1px solid rgba(233,243,249,.18);outline-offset:-1px' : '');
    // the lane keeps its 1280x720 box: translate under the bezel, uniform scale k, origin 0 0
    wrap.style.left = '0px'; wrap.style.top = '0px'; wrap.style.right = 'auto'; wrap.style.bottom = 'auto';
    wrap.style.width = STAGE_W + 'px'; wrap.style.height = STAGE_H + 'px'; wrap.style.transformOrigin = '0 0';
    wrap.style.transform = 'translate(' + px(o.inset || 0) + ',' + px(geo.bezel) + ') scale(' + (geo.k * (1 - 2 * (o.inset || 0) / STAGE_W)).toFixed(5) + ')';
    // bezel: a neutral bar we draw (three hollow dots + an optional centred title pill); no platform trade dress
    let bezel = frame.querySelector('#stageBezel');
    if (geo.bezel > 0) {
      if (!bezel) { bezel = doc.createElement('div'); bezel.id = 'stageBezel'; frame.insertBefore(bezel, frame.firstChild); }
      bezel.style.cssText = 'position:absolute;left:0;top:0;right:0;height:' + geo.bezel + 'px;background:' + PAL.navy2 + ';display:flex;align-items:center;padding:0 14px;box-sizing:border-box;color:' + PAL.ink + ';font:500 12px/1 Arial,sans-serif;letter-spacing:.02em';
      const dots = '<span style="display:inline-flex;gap:7px">' + [0, 1, 2].map(() => '<i style="width:10px;height:10px;border-radius:50%;border:1.5px solid rgba(233,243,249,.45);display:inline-block"></i>').join('') + '</span>';
      const title = o.title ? '<span style="position:absolute;left:50%;top:50%;transform:translate(-50%,-50%);padding:4px 12px;border-radius:7px;background:rgba(8,42,52,.55);color:' + PAL.cream + ';white-space:nowrap">' + String(o.title).replace(/[<>&]/g, '') + '</span>' : '';
      bezel.innerHTML = dots + title;
    } else if (bezel) bezel.remove();
    mounted = { el: stageEl, frame, wrap, wall, geo, opts: o };
    if (/[?&]guides\b/.test((root.location && root.location.search) || '')) guides(stageEl, { format: o.guides || '9:16' });
    return Object.assign({ pose: p => poseOf(geo, p), full: () => fullOf(geo) }, mounted);
  }
  function unmount() {
    if (!mounted) return;
    const { frame, wrap, wall } = mounted;
    frame.parentNode.insertBefore(wrap, frame); frame.remove(); wall.remove();
    wrap.style.cssText = wrap.style.cssText.replace(/transform[^;]*;|left[^;]*;|top[^;]*;|right[^;]*;|bottom[^;]*;|width[^;]*;|height[^;]*;/g, '');
    mounted = null;
  }
  function pose(p) { return mounted ? poseOf(mounted.geo, p) : { s: p.s, cx: p.cx, cy: p.cy }; }
  function full() { return mounted ? fullOf(mounted.geo) : { s: 1, cx: STAGE_W / 2, cy: STAGE_H / 2 }; }

  /* ---------- reflow (pure) ---------- */
  function cropOf(format) {
    const r = FORMATS[format]; if (!r) throw new Error('stage.js: unknown format ' + format + ' (16:9 | 9:16 | 1:1 | 4:5)');
    const w = Math.min(STAGE_W, Math.round(STAGE_H * r)), h = Math.min(STAGE_H, Math.round(STAGE_W / r));
    return [w, h];
  }
  /* the subject of one sample in stage/screen px */
  function interest(s, source) {
    if (s.x !== undefined && s.y !== undefined) {
      const kx = source ? STAGE_W / source[0] : 1, ky = source ? STAGE_H / source[1] : 1;
      return { t: s.t, x: s.x * kx, y: s.y * ky };
    }
    if (s.cx !== undefined) return (s.s || 1) > 1.0005 ? { t: s.t, x: STAGE_W / 2, y: STAGE_H / 2 } : { t: s.t, x: s.cx, y: s.cy };
    return { t: s.t, x: STAGE_W / 2, y: STAGE_H / 2 };
  }
  /* any accepted track shape → sorted [{t,x,y}] in stage px */
  function track(any, o) {
    o = o || {};
    let list = [];
    if (!any) list = [];
    else if (Array.isArray(any)) list = any;
    else if (Array.isArray(any.shots)) any.shots.forEach(sh => (sh.samples || []).forEach(s => list.push(s)));
    else if (Array.isArray(any.events)) list = any.events;
    else if (Array.isArray(any.samples)) list = any.samples;
    else if (Array.isArray(any.track)) list = any.track;
    const src = o.source || any.source || null;
    return list.filter(s => s && typeof s.t === 'number').map(s => interest(s, src)).sort((a, b) => a.t - b.t);
  }
  function sampleAt(tr, t, fallback) {
    if (!tr.length) return fallback;
    if (t <= tr[0].t) return tr[0];
    for (let i = 1; i < tr.length; i++) if (t <= tr[i].t) {
      const a = tr[i - 1], b = tr[i], g = b.t - a.t;
      if (g > 1.5) return t - a.t < 1.5 ? a : b;                       // a hole in the track: hold, then jump to the new shot
      const u = g > 1e-6 ? (t - a.t) / g : 1; return { t, x: a.x + (b.x - a.x) * u, y: a.y + (b.y - a.y) * u };
    }
    return tr[tr.length - 1];
  }
  function safeOf(format, crop) {
    const ui = UI_BANDS[format] || UI_BANDS['16:9'], w = crop[0], h = crop[1], ts = REFLOW.titleSafe;
    const title = { x: w * ts, y: h * ts, w: w * (1 - 2 * ts), h: h * (1 - 2 * ts) };
    const top = Math.max(h * ts, h * ui.top), bottom = Math.max(h * ts, h * ui.bottom);
    return { title, text: { x: w * ts, y: top, w: w * (1 - 2 * ts), h: h - top - bottom }, ui: { top: h * ui.top, bottom: h * ui.bottom } };
  }
  function reflow(format, o) {
    o = o || {};
    const crop = cropOf(format), fps = o.fps || REFLOW.fps, tau = o.tau === undefined ? REFLOW.tau : o.tau, dead = o.dead === undefined ? REFLOW.dead : o.dead;
    const tr = track(o.follow, o), total = o.total !== undefined ? o.total : (tr.length ? tr[tr.length - 1].t : 0);
    const out = { format, out: OUT_PX[format], stage: [STAGE_W, STAGE_H], crop, fps, tau, dead, safe: safeOf(format, crop), rects: [] };
    const W = crop[0], H = crop[1], centre = { t: 0, x: STAGE_W / 2, y: STAGE_H / 2 };
    if (W >= STAGE_W && H >= STAGE_H) { out.rects.push({ t: 0, x: 0, y: 0, w: W, h: H }); return out; }
    const n = Math.max(1, Math.round(total * fps) + 1), dt = 1 / fps, a = 1 - Math.exp(-dt / tau);
    let cx = clamp(sampleAt(tr, 0, centre).x, W / 2, STAGE_W - W / 2), cy = clamp(sampleAt(tr, 0, centre).y, H / 2, STAGE_H - H / 2);
    for (let i = 0; i < n; i++) {
      const t = i * dt, s = sampleAt(tr, t, centre);
      const tx = Math.abs(s.x - cx) < dead * W / 2 ? cx : s.x, ty = Math.abs(s.y - cy) < dead * H / 2 ? cy : s.y;
      cx = clamp(cx + (tx - cx) * a, W / 2, STAGE_W - W / 2); cy = clamp(cy + (ty - cy) * a, H / 2, STAGE_H - H / 2);
      out.rects.push({ t: +t.toFixed(4), x: +(cx - W / 2).toFixed(2), y: +(cy - H / 2).toFixed(2), w: W, h: H });
    }
    return out;
  }
  function rectAt(rf, t) {
    const R = rf.rects; if (R.length === 1) return R[0];
    const i = clamp(Math.round(t * rf.fps), 0, R.length - 1); return R[i];
  }

  /* ---------- guides (DOM, preview only) ---------- */
  function guides(stageEl, o) {
    o = o || {}; const doc = stageEl.ownerDocument, format = o.format || '9:16', crop = cropOf(format), safe = safeOf(format, crop);
    let g = stageEl.querySelector('#stageGuides');
    if (!g) { g = doc.createElement('div'); g.id = 'stageGuides'; stageEl.appendChild(g); }
    g.style.cssText = 'position:absolute;inset:0;z-index:60;pointer-events:none';
    const rect = o.rect || { x: (STAGE_W - crop[0]) / 2, y: (STAGE_H - crop[1]) / 2, w: crop[0], h: crop[1] };
    const box = (r, color, label, dash) => '<div style="position:absolute;left:' + px(r.x) + ';top:' + px(r.y) + ';width:' + px(r.w) + ';height:' + px(r.h) + ';border:1px ' + (dash || 'dashed') + ' ' + color + ';box-sizing:border-box"><span style="position:absolute;left:4px;top:2px;font:600 11px/1 Arial,sans-serif;color:' + color + '">' + label + '</span></div>';
    const abs = r => ({ x: rect.x + r.x, y: rect.y + r.y, w: r.w, h: r.h });
    g.innerHTML = box(rect, PAL.gold, format + ' crop', 'solid') + box(abs(safe.title), PAL.mint, 'title-safe') + box(abs(safe.text), PAL.coral, 'text zone') +
      box({ x: STAGE_W * 0.1, y: STAGE_H * 0.1, w: STAGE_W * 0.8, h: STAGE_H * 0.8 }, 'rgba(233,243,249,.45)', '16:9 title-safe');
    return g;
  }

  /* ---------- node CLI ---------- */
  function selftest() {
    const out = [], fail = (m) => out.push('FAIL ' + m), ok = (m) => out.push('ok   ' + m);
    const g = geometry({ padding: 64, bezel: 'window' });
    (Math.abs(g.k - (720 - 128 - 34) / 720) < 1e-9 ? ok : fail)('geometry k = ' + g.k.toFixed(4) + ' for padding 64 + window bezel (expect 0.7750)');
    (Math.abs(g.frame.x + g.frame.w / 2 - 640) < 1e-6 && Math.abs(g.frame.y + g.frame.h / 2 - 360) < 1e-6 ? ok : fail)('frame centred on the stage');
    const p = poseOf(g, { s: 1.6, cx: 940, cy: 225 });
    (Math.abs(p.cx - (g.footage.x + g.k * 940)) < 1e-9 && p.s === 1.6 ? ok : fail)('pose maps centre, keeps s');
    (Math.abs(fullOf(g).s * g.k - 1) < 1e-9 ? ok : fail)('full() undoes k exactly');
    const c = cropOf('9:16'); (c[0] === 405 && c[1] === 720 ? ok : fail)('9:16 crop = 405x720 (got ' + c.join('x') + ')');
    (cropOf('1:1')[0] === 720 && cropOf('4:5')[0] === 576 && cropOf('16:9')[0] === 1280 ? ok : fail)('1:1 720 · 4:5 576 · 16:9 1280');
    // a cursor that jumps from the left edge to the right at t = 1: the window must take tau to follow, never snap
    const tr = [{ t: 0, x: 100, y: 360 }, { t: 1, x: 100, y: 360 }, { t: 1.0333, x: 1180, y: 360 }, { t: 4, x: 1180, y: 360 }];
    const rf = reflow('9:16', { follow: tr, total: 4 });
    const r0 = rectAt(rf, 0.5), r1 = rectAt(rf, 1.6), r2 = rectAt(rf, 3.9);
    (r0.x === 0 ? ok : fail)('clamped at the left edge before the jump (x=' + r0.x + ')');
    (r1.x > 200 && r1.x < 800 ? ok : fail)('0.6 s after the jump the window is mid-way (x=' + r1.x + ', 62 % rule)');
    (Math.abs(r2.x - (1280 - 405)) < 1 ? ok : fail)('settled at the right clamp by t=3.9 (x=' + r2.x + ')');
    let maxStep = 0; for (let i = 1; i < rf.rects.length; i++) maxStep = Math.max(maxStep, Math.abs(rf.rects[i].x - rf.rects[i - 1].x));
    (maxStep < 70 ? ok : fail)('largest per-frame move ' + maxStep.toFixed(1) + ' px (< 70: no snap)');
    const rf2 = reflow('9:16', { follow: tr, total: 4 });
    (JSON.stringify(rf) === JSON.stringify(rf2) ? ok : fail)('reflow is deterministic (two runs identical)');
    const cam = reflow('1:1', { follow: { shots: [{ samples: [{ t: 0, s: 1, cx: 640, cy: 360 }, { t: 2, s: 1.6, cx: 940, cy: 225 }] }] }, total: 2 });
    (Math.abs(cam.rects[cam.rects.length - 1].x - 280) < 1 ? ok : fail)('a pushed-in camera keeps the crop centred (subject = frame centre)');
    const sf = safeOf('9:16', cropOf('9:16'));
    (Math.abs(sf.ui.bottom - 144) < 1e-9 && Math.abs(sf.text.h - 504) < 1e-9 ? ok : fail)('9:16 UI bands: bottom 144 px, text zone 504 px tall');
    (wallpaperCSS('mesh').split('radial-gradient').length === 5 && wallpaperCSS('solid', '#000011') === '#000011' ? ok : fail)('wallpaper css: mesh has 4 pools, solid passes the colour');
    const bad = out.filter(l => l.startsWith('FAIL')).length;
    return { ok: bad === 0, lines: out, failures: bad };
  }
  function cli(argv) {
    const fs = require('fs'), path = require('path');
    const arg = (k, d) => { const i = argv.indexOf(k); return i >= 0 ? argv[i + 1] : d; };
    if (!argv.length || argv.includes('--help') || argv.includes('-h')) {
      console.log('stage.js — screen staging + aspect reflow\n  node lib/stage.js --reflow 9:16|1:1|4:5 --track <camera_curves.json | events.json> [--total S] [--fps 30] [--source 1920x1080] [--out out/stage_reflow.json]\n  node lib/stage.js --selftest\n  exit 0 ok · 1 findings · 2 usage');
      return argv.length ? 0 : 2;
    }
    if (argv.includes('--selftest')) { const r = selftest(); console.log(r.lines.join('\n')); console.log(JSON.stringify({ selftest: 'stage.js', ok: r.ok, failures: r.failures })); return r.ok ? 0 : 1; }
    if (argv.includes('--reflow')) {
      const format = arg('--reflow'); if (!FORMATS[format]) { console.error('unknown format ' + format); return 2; }
      const trackFile = arg('--track'); let follow = null;
      if (trackFile) { if (!fs.existsSync(trackFile)) { console.error('track not found: ' + trackFile); return 2; } follow = JSON.parse(fs.readFileSync(trackFile, 'utf8')); }
      const src = arg('--source'); const source = src ? src.split('x').map(Number) : undefined;
      const total = arg('--total') ? parseFloat(arg('--total')) : (follow && typeof follow.total === 'number' ? follow.total : undefined);
      const rf = reflow(format, { follow, total, fps: parseInt(arg('--fps', '30'), 10), source });
      const outFile = arg('--out'); const txt = JSON.stringify(rf, null, 1);
      if (outFile) { fs.mkdirSync(path.dirname(path.resolve(outFile)), { recursive: true }); fs.writeFileSync(outFile, txt); console.log(JSON.stringify({ out: outFile, format, rects: rf.rects.length, crop: rf.crop })); }
      else process.stdout.write(txt + '\n');
      return 0;
    }
    console.error('usage: --reflow <format> --track <file> | --selftest | --help'); return 2;
  }

  const STAGE = { mount, unmount, pose, full, geometry, wallpaperCSS, reflow, rectAt, track, interest, cropOf, safeOf, guides, selftest, PAL, FORMATS, OUT_PX, DEFAULTS, REFLOW };
  root.STAGE = STAGE;
  if (typeof module !== 'undefined' && module.exports) { module.exports = STAGE; if (require.main === module) process.exit(cli(process.argv.slice(2))); }
})(typeof window !== 'undefined' ? window : globalThis);
