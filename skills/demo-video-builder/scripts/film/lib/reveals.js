/* reveals.js — REVEAL: opener and closer reveals of REAL stills, on MOTION (GSAP timelines driven by the film clock).

   The first and last three seconds decide whether a film reads as designed. These helpers bring the first median
   still of a recording onto the stage (and take the last one off) with motion that ends on the exact pixels the
   footage lane draws next, so the lane can take over on one frame and nobody sees the join.

   What is here. Defaults are the measured numbers. Every `at` is in the timeline's own seconds (with a block mounted
   at start 0 that is film time); `land` may be given instead of `at` to key the landing frame to a spoken word.
     REVEAL.mount(host, {still, target, line})   a plate: an <img> of the still at the footage lane's establish rect,
                                                 a 1 px hairline and a soft shadow as SIBLINGS of the image
     REVEAL.heroDive(tl, {el, at, dur .9})       the plate opens at scale .62, perspective 1400, rotationX 6°,
                                                 rotationY −8°, and flattens on power3.inOut onto the target rect; the
                                                 hairline + shadow fade over the last 25 %; the plate cuts out on the
                                                 hand-over frame, where the lane draws the same file at scale 1
     REVEAL.pullBack(tl, {el, at, dur .9})       the reverse for the close: cut in on the frame the lane stops, lift to
                                                 the same pose, hairline back over the first 25 %; exit 'hold' | 'fade'
     REVEAL.assemble(tl, {el, at, dur 1.2, particles 6000 (4000–9000), seed})
                                                 the still compiles out of noise on a 2D canvas (no WebGL): one particle
                                                 per grid cell (cell = sqrt(w·h/N) ≈ 12.4 px at N = 6000 on 1280×720),
                                                 colour = the still box-filtered to that grid by the browser's downsample;
                                                 each flies in from 0.55–1.45 stage half-diagonals away along a quadratic
                                                 path (curl ±0.30), power3.out over 50 % of the window, size .35 → 1,
                                                 launched by distance from the focus (65 %) + seed (35 %) within the first
                                                 40 %; every particle has landed by 90 %; the last 10 % cross-fades the
                                                 canvas to the real <img> so the final pixels are the file's own
     REVEAL.irisFrom(tl, {el, at, dur .5, origin {x,y} in %, feather 24, shape 'circle'|'squircle', ring})
                                                 a circular reveal (feathered radial mask) or a superellipse (clip-path
                                                 polygon, n = 4, 64 points) from a clicked control; radius grows to the
                                                 farthest corner on power2.inOut; a 44 px click ring (0.36 s) starts on
                                                 the same frame as the iris — the cause and its effect share the frame
     REVEAL.lightWipe(tl, {host, el, at, dur .7, angle −14°, width 220, peak .85})
                                                 a soft cream band (screen blend, opacity sin(πu)^0.6 · peak) sweeps the
                                                 stage left → right on power2.inOut; the still is uncovered along the
                                                 band's trailing edge by a slanted clip-path, so the edge is never seen
     REVEAL.matchCutHandover(tl, {from, to, at, settle 0})
                                                 on frame `at` `from` cuts out and `to` cuts in, transformed so its rect
                                                 covers from's rect (uniform scale, centred; 'stretch' on request); with
                                                 `settle` the transform eases to identity on power3.inOut
     REVEAL.fit / snap / frameOf / irisRadius / squircle / grid / particleTable / particleAt / plan / pending / list

   The sanctioned exception. "Real footage is sacred" lets a transition pass over product pixels for at most 0.5 s;
   reveals are the ONE exception, and only on the FIRST still as the film opens (heroDive 0.9 s, assemble 1.2 s,
   irisFrom 0.5 s, lightWipe 0.7 s) and the LAST still as it closes (pullBack 0.9 s). Inside that window the still is
   displaced, masked or assembled — never recoloured, grained or redrawn — and on the hand-over frame the footage lane
   shows the file plain; gates/reveal_gate.py measures that frame (pixel-exact join) and fails the film otherwise.
   One reveal in, one reveal out, none between shots.

   Hand-over contract. Every helper returns { kind, at, dur, end, frame } with `end` snapped to the frame grid (fps 30)
   and frame = round(end · fps). The footage shot that follows a dive / assemble / wipe starts at `end`
   (FILM.openEnd = dive.end); the shot before a pullBack stops at its `at`. Measured on the synthetic Acme still at
   1920×1080 (DPR 1.5): the join dive → lane differs by a mean |Δ| of 0.0 luma levels (identical frames), the join
   assemble → lane by 0.0; the frame before each join is already within 0.2 % of identity on power3.inOut.

   Real footage is sacred. The still is only DISPLACED (transform, mask, clip, particle positions) during the reveal
   window; nothing recolours, blurs or regrains it, and on the last frame of every reveal the <img> is drawn plain.
   Hairlines, shadows, rings and the light band are siblings in the reveals host — a stage layer above the footage
   lane and below #ovl — never children of #clipWrap. assemble reads the still's pixels through a canvas: a file://
   page needs Chrome's --allow-file-access-from-files (render_frames.js sets it); if the canvas is tainted the
   particles fall back to cream at 0.5 alpha and the receipt (REVEAL.list()) says `sampled: false`.

   Determinism. No wall clock, no Math.random (MOTION.rng(seed) only), no CSS transitions, no zero-duration tweens:
   a cut is a 1/60 s tween with a step ease that is 1 on the cut frame (30 fps frames never sample its interior).
   Particle, iris and wipe frames are written by GSAP plugins whose render(ratio) is a pure function of the ratio,
   so they survive the suppressed-event seeks MOTION.seek performs; the particle table is built once per mount from
   the seed, and a late image decode repaints the last ratio through the same function.

   Node CLI (no DOM, no gsap needed):
     node lib/reveals.js --selftest [--json]       synthetic fixture: table determinism, coverage, fit, snapping, iris
     node lib/reveals.js --plan '{"kind":"assemble","at":1.4}' | --plan plan.json     → the timing receipt as JSON
     exit 0 ok · 1 findings · 2 usage */
(function (root) {
  'use strict';
  const M = root.MOTION || null, G = M ? M.gsap : (root.gsap || null);
  const HAS_DOM = typeof document !== 'undefined';

  /* ------------------------------------------------------------ measured defaults ---------------------------- */
  const N = {
    fps: 30, cut: 1 / 60, stage: [1280, 720],
    dive: { dur: 0.9, scale: 0.62, perspective: 1400, rx: 6, ry: -8, ease: 'power3.inOut', dress: 0.25,
      line: 'rgba(236,222,195,0.42)', shadow: '0 40px 90px -20px rgba(5,22,28,0.72)', fade: 0.35 },
    assemble: { dur: 1.2, particles: 6000, min: 4000, max: 9000, flight: 0.5, spread: 0.4, xfade: 0.1, scatter: [0.55, 1.45],
      size0: 0.35, grow: 1.06, curl: 0.3, jitter: 0.35, orderMix: 0.65, fadeIn: 0.2, order: 'centre', fallback: 'rgb(236,222,195)' },
    iris: { dur: 0.5, feather: 24, ease: 'power2.inOut', shape: 'circle', points: 64, n: 4, ring: { size: 44, dur: 0.36, width: 2, colour: '#E56B5E' } },
    wipe: { dur: 0.7, angle: -14, width: 220, peak: 0.85, colour: '236,222,195', ease: 'power2.inOut', blend: 'screen', soft: 0.6 },
    match: { settle: 0, ease: 'power3.inOut', mode: 'uniform', aspectWarn: 0.01 }
  };
  const HARD = p => (p >= 1 ? 1 : 0);                           // step ease: 0 until the tween's last tick, 1 on it
  const clamp = (x, a, b) => Math.max(a, Math.min(b, x));
  const lerp = (a, b, x) => a + (b - a) * x;
  const P3O = x => 1 - Math.pow(1 - clamp(x, 0, 1), 3);
  const P2IO = x => { x = clamp(x, 0, 1); return x < 0.5 ? 2 * x * x : 1 - Math.pow(-2 * x + 2, 2) / 2; };
  const SMOOTH = x => { x = clamp(x, 0, 1); return x * x * (3 - 2 * x); };
  const hash = s => { let h = 2166136261; s = String(s); for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); } return h >>> 0; };
  /* the same mulberry32 MOTION.rng uses, so the CLI and the browser draw identical tables */
  function rng(seed) { let s = (seed >>> 0) || 1; return () => { s = (s + 0x6D2B79F5) >>> 0; let x = Math.imul(s ^ (s >>> 15), 1 | s); x ^= x + Math.imul(x ^ (x >>> 7), 61 | x); return ((x ^ (x >>> 14)) >>> 0) / 4294967296; }; }
  const receipts = [], loads = [];

  /* ------------------------------------------------------------ pure helpers ---------------------------------- */
  const frameOf = (t, fps) => Math.round(t * (fps || N.fps));
  const snap = (t, fps) => frameOf(t, fps) / (fps || N.fps);
  const rectOf = r => (Array.isArray(r) ? { x: r[0], y: r[1], w: r[2], h: r[3] } : (r || { x: 0, y: 0, w: N.stage[0], h: N.stage[1] }));
  /* resolve at / land / dur / end on the frame grid: end is a frame, `at` keeps its authored value when given */
  function timing(o, dflt) {
    const fps = o.fps || N.fps, dur = o.dur === undefined ? dflt : o.dur;
    let at = o.at; if (at === undefined && o.land !== undefined) at = +(o.land - dur).toFixed(6); if (at === undefined) at = 0;
    const end = snap(at + dur, fps);
    return { at, dur, end, frame: frameOf(end, fps), fps };
  }
  /* transform that lays `to` over `from` (both {x,y,w,h} in stage px), origin at to's top-left */
  function fit(from, to, mode) {
    from = rectOf(from); to = rectOf(to); mode = mode || N.match.mode;
    const sx = from.w / to.w, sy = from.h / to.h, aspect = Math.abs(sx / sy - 1);
    const s = mode === 'stretch' ? null : Math.min(sx, sy);
    const w = s === null ? from.w : to.w * s, h = s === null ? from.h : to.h * s;
    return { x: +(from.x - to.x + (from.w - w) / 2).toFixed(3), y: +(from.y - to.y + (from.h - h) / 2).toFixed(3),
      scaleX: +(s === null ? sx : s).toFixed(5), scaleY: +(s === null ? sy : s).toFixed(5), aspect: +aspect.toFixed(4), uniform: s !== null,
      ok: mode === 'stretch' ? aspect <= N.match.aspectWarn : true };
  }
  /* distance from the origin (in % of w×h) to the farthest corner, in px: the radius at which an iris is complete */
  function irisRadius(origin, w, h) {
    const ox = (origin.x / 100) * w, oy = (origin.y / 100) * h;
    return Math.max(Math.hypot(ox, oy), Math.hypot(w - ox, oy), Math.hypot(ox, h - oy), Math.hypot(w - ox, h - oy));
  }
  /* superellipse |x/a|^n + |y/b|^n = 1 sampled as a polygon (k points) around (cx, cy) */
  function squircle(cx, cy, a, b, n, k) {
    n = n || N.iris.n; k = k || N.iris.points; const pts = [], e = 2 / n;
    for (let i = 0; i < k; i++) { const th = (i / k) * 2 * Math.PI, c = Math.cos(th), s = Math.sin(th);
      pts.push([cx + a * Math.sign(c) * Math.pow(Math.abs(c), e), cy + b * Math.sign(s) * Math.pow(Math.abs(s), e)]); }
    return pts;
  }
  const polygonCSS = pts => 'polygon(' + pts.map(p => p[0].toFixed(2) + 'px ' + p[1].toFixed(2) + 'px').join(',') + ')';
  /* the particle grid for a rect and a requested count: square-ish cells, N clamped to [4000, 9000] */
  function grid(rect, particles) {
    rect = rectOf(rect); const want = clamp(particles || N.assemble.particles, N.assemble.min, N.assemble.max);
    const cell = Math.sqrt(rect.w * rect.h / want), cols = Math.max(1, Math.round(rect.w / cell)), rows = Math.max(1, Math.round(rect.h / cell));
    return { cols, rows, n: cols * rows, cw: rect.w / cols, ch: rect.h / rows, cell: +cell.toFixed(3), rect };
  }
  /* the particle table: pure in (rgba of the still downsampled to cols×rows, the grid, options, a seeded rng).
     Row-major cells; one rng draw order; typed arrays. focus in stage px (default rect centre). */
  function particleTable(rgba, g, o, rnd) {
    o = Object.assign({}, N.assemble, o || {}); rnd = rnd || rng(hash(o.seed === undefined ? 'assemble' : o.seed));
    const R = g.rect, n = g.n, fx = o.focus ? o.focus.x : R.x + R.w / 2, fy = o.focus ? o.focus.y : R.y + R.h / 2;
    const W = o.stage ? o.stage[0] : N.stage[0], H = o.stage ? o.stage[1] : N.stage[1], half = Math.hypot(W, H) / 2;
    const x0 = new Float32Array(n), y0 = new Float32Array(n), qx = new Float32Array(n), qy = new Float32Array(n), x1 = new Float32Array(n), y1 = new Float32Array(n), delay = new Float32Array(n);
    const col = new Array(n); let maxKey = 1e-6; const key = new Float32Array(n);
    for (let r = 0; r < g.rows; r++) for (let c = 0; c < g.cols; c++) {
      const i = r * g.cols + c, cx = R.x + (c + 0.5) * g.cw, cy = R.y + (r + 0.5) * g.ch; x1[i] = cx; y1[i] = cy;
      key[i] = o.order === 'top' ? (cy - R.y) / R.h : o.order === 'left' ? (cx - R.x) / R.w : o.order === 'random' ? 0 : Math.hypot(cx - fx, cy - fy);
      if (key[i] > maxKey) maxKey = key[i];
      const p = rgba ? i * 4 : -1;
      col[i] = p >= 0 ? 'rgb(' + rgba[p] + ',' + rgba[p + 1] + ',' + rgba[p + 2] + ')' : o.fallback;
    }
    const spreadT = o.spread * (o.dur || N.assemble.dur);
    for (let i = 0; i < n; i++) {
      const a0 = Math.atan2(y1[i] - fy, x1[i] - fx), ang = a0 + (rnd() * 2 - 1) * o.jitter, d = half * lerp(o.scatter[0], o.scatter[1], rnd());
      x0[i] = fx + Math.cos(ang) * d; y0[i] = fy + Math.sin(ang) * d;
      const mx = (x0[i] + x1[i]) / 2, my = (y0[i] + y1[i]) / 2, dx = x1[i] - x0[i], dy = y1[i] - y0[i], L = Math.hypot(dx, dy) || 1, k = (rnd() * 2 - 1) * o.curl;
      qx[i] = mx - dy / L * L * k; qy[i] = my + dx / L * L * k;          // control point off the chord by curl·length
      const ok = o.order === 'random' ? 0 : key[i] / maxKey;
      delay[i] = spreadT * (o.orderMix * ok + (1 - o.orderMix) * rnd());
    }
    return { n, cols: g.cols, rows: g.rows, cw: g.cw, ch: g.ch, x0, y0, qx, qy, x1, y1, delay, col, flight: o.flight * (o.dur || N.assemble.dur), dur: o.dur || N.assemble.dur,
      size0: o.size0, grow: o.grow, fadeIn: o.fadeIn, xfade: o.xfade, sampled: !!rgba };
  }
  /* one particle at ratio ρ of the window → {x, y, size (× cell), alpha, u} — pure */
  function particleAt(T, i, rho) {
    const tau = rho * T.dur, u = clamp((tau - T.delay[i]) / T.flight, 0, 1);
    if (u <= 0) return { u: 0, alpha: 0, x: T.x0[i], y: T.y0[i], size: T.size0 };
    const e = P3O(u), a = 1 - e;
    return { u, alpha: Math.min(1, u / T.fadeIn), size: T.grow * lerp(T.size0, 1, e),
      x: a * a * T.x0[i] + 2 * a * e * T.qx[i] + e * e * T.x1[i], y: a * a * T.y0[i] + 2 * a * e * T.qy[i] + e * e * T.y1[i] };
  }
  /* the canvas ↔ image cross-fade at ratio ρ: {canvas, img} opacities */
  const xfadeAt = (rho, xf) => { const u = SMOOTH((rho - (1 - xf)) / xf); return { canvas: 1 - u, img: u }; };
  /* timing receipt without a DOM: what the CLI prints and what a gate can check against the ledger */
  function plan(o) {
    o = o || {}; const kind = o.kind || 'heroDive';
    const d = kind === 'assemble' ? N.assemble.dur : kind === 'irisFrom' ? N.iris.dur : kind === 'lightWipe' ? N.wipe.dur : kind === 'matchCutHandover' ? (o.settle || 0) : N.dive.dur;
    const T = timing(o, d), out = Object.assign({ kind }, T);
    if (kind === 'assemble') { const g = grid(o.target, o.particles); Object.assign(out, { particles: g.n, cols: g.cols, rows: g.rows, cell: g.cell, landedBy: +(T.at + T.dur * (1 - N.assemble.xfade)).toFixed(4), seed: o.seed === undefined ? 'assemble' : o.seed }); }
    if (kind === 'irisFrom') { const R = rectOf(o.target); out.radius = +irisRadius(o.origin || { x: 50, y: 50 }, R.w, R.h).toFixed(2); out.feather = o.feather === undefined ? N.iris.feather : o.feather; }
    if (kind === 'pullBack') { out.frame = frameOf(T.at, T.fps); out.handover = 'lane stops at `at`'; } else out.handover = 'lane starts at `end`';
    if (kind === 'matchCutHandover' && o.from && o.to) out.transform = fit(o.from, o.to, o.mode);
    return out;
  }

  /* ------------------------------------------------------------ DOM: tween helpers ---------------------------- */
  function tw(tl, el, from, to, at) { return tl.fromTo(el, from, Object.assign({ immediateRender: false, lazy: false }, to), at); }
  /* a cut is one 1/60 s tween with the step ease; at (or before) time 0 the initial inline state is the cut */
  function cutIn(tl, el, at) { if (at < N.cut) { el.style.opacity = '1'; return; } tw(tl, el, { opacity: 0 }, { opacity: 1, duration: N.cut, ease: HARD }, at - N.cut); }
  function cutOut(tl, el, at) { if (at < N.cut) { el.style.opacity = '0'; return; } tw(tl, el, { opacity: 1 }, { opacity: 0, duration: N.cut, ease: HARD }, at - N.cut); }
  const mk = (tag, parent, st) => { const e = document.createElement(tag); if (st) e.style.cssText = st; if (parent) parent.appendChild(e); return e; };
  const px = v => v.toFixed(2) + 'px';
  function record(r) { receipts.push(r); return r; }
  /* the host layer: a stage sibling above the footage lane, below #ovl */
  function host(stage, id) {
    id = id || 'reveals'; let h = document.getElementById(id);
    if (!h) { h = mk('div', stage || document.getElementById('stage') || document.body, 'position:absolute;inset:0;z-index:9;pointer-events:none;overflow:hidden'); h.id = id; }
    return h;
  }
  /* a plate: the still at the target rect; hairline + shadow are siblings so the image element stays plain */
  function mount(h, o) {
    o = o || {}; const R = rectOf(o.target);
    const el = mk('div', h, 'position:absolute;left:' + px(R.x) + ';top:' + px(R.y) + ';width:' + px(R.w) + ';height:' + px(R.h) + ';opacity:' + (o.visible ? 1 : 0) + ';transform-origin:50% 50%');
    if (o.id) el.id = o.id;
    const shade = mk('div', el, 'position:absolute;inset:0;box-shadow:' + N.dive.shadow + ';opacity:0');
    const img = mk('img', el, 'position:absolute;left:0;top:0;width:100%;height:100%;display:block');
    img.alt = ''; img.setAttribute('src', o.still); loads.push(img.decode().catch(() => {}));
    const line = mk('div', el, 'position:absolute;inset:-1px;border:1px solid ' + N.dive.line + ';opacity:0;pointer-events:none');
    if (o.line === false) { line.style.display = 'none'; shade.style.display = 'none'; }
    return { el, img, line, shade, rect: R, still: o.still };
  }
  /* the hero pose both dive and pullBack share */
  const pose = o => ({ scale: o.scale === undefined ? N.dive.scale : o.scale, rotationX: o.rx === undefined ? N.dive.rx : o.rx, rotationY: o.ry === undefined ? N.dive.ry : o.ry, transformPerspective: o.perspective || N.dive.perspective });

  /* ------------------------------------------------------------ 1. heroDive / pullBack ------------------------ */
  function heroDive(tl, o) {
    const p = o.el, T = timing(o, N.dive.dur), P = pose(o), ease = o.ease || N.dive.ease, dress = T.dur * (o.dress === undefined ? N.dive.dress : o.dress);
    cutIn(tl, p.el, T.at);
    tw(tl, p.el, P, { scale: 1, rotationX: 0, rotationY: 0, transformPerspective: P.transformPerspective, duration: T.end - T.at, ease }, T.at);
    tw(tl, p.line, { opacity: 1 }, { opacity: 0, duration: dress, ease: 'power2.in' }, T.end - dress);
    tw(tl, p.shade, { opacity: 1 }, { opacity: 0, duration: dress, ease: 'power2.in' }, T.end - dress);
    cutOut(tl, p.el, T.end);
    return record(Object.assign({ kind: 'heroDive', target: p.rect, handover: 'lane starts at end' }, T));
  }
  function pullBack(tl, o) {
    const p = o.el, fps = o.fps || N.fps, at = snap(o.at === undefined ? 0 : o.at, fps), dur = o.dur === undefined ? N.dive.dur : o.dur, P = pose(o), ease = o.ease || N.dive.ease, dress = dur * (o.dress === undefined ? N.dive.dress : o.dress);
    if (o.cut !== false) cutIn(tl, p.el, at);
    tw(tl, p.el, { scale: 1, rotationX: 0, rotationY: 0, transformPerspective: P.transformPerspective }, Object.assign({ duration: dur, ease }, P), at);
    tw(tl, p.line, { opacity: 0 }, { opacity: 1, duration: dress, ease: 'power2.out' }, at);
    tw(tl, p.shade, { opacity: 0 }, { opacity: 1, duration: dress, ease: 'power2.out' }, at);
    let end = at + dur;
    if (o.exit === 'fade') { tw(tl, p.el, { opacity: 1 }, { opacity: 0, duration: N.dive.fade, ease: 'power2.in' }, end); end += N.dive.fade; }
    return record({ kind: 'pullBack', at, dur, end: +end.toFixed(6), frame: frameOf(at, fps), fps, target: p.rect, exit: o.exit || 'hold', handover: 'lane stops at at' });
  }

  /* ------------------------------------------------------------ 2. assemble ----------------------------------- */
  /* plugin values are looked up by key: GSAP evaluates function-valued properties of a value object, a key it leaves alone */
  const STATES = {}; let stateN = 0; const keep = st => { const k = 'rv' + (++stateN); STATES[k] = st; return k; };
  if (G) G.registerPlugin({ name: 'rvAssemble', headless: true, init(t, v) { this.v = STATES[v]; }, render(r, d) { d.v.ratio = r; d.v.draw(r); } });
  function assemble(tl, o) {
    const p = o.el, T = timing(o, N.assemble.dur), R = p.rect, g = grid(R, o.particles), dpr = o.dpr || 1.5;
    const seed = o.seed === undefined ? hash(p.still || 'assemble') : (typeof o.seed === 'number' ? o.seed : hash(o.seed));
    const canvas = mk('canvas', p.el, 'position:absolute;left:0;top:0;width:100%;height:100%;display:block;opacity:1');
    canvas.width = Math.round(R.w * dpr); canvas.height = Math.round(R.h * dpr);
    p.el.insertBefore(canvas, p.img.nextSibling); p.img.style.opacity = '0';
    const ctx = canvas.getContext('2d'), opts = Object.assign({}, o, { dur: T.end - T.at, seed, stage: o.stage || N.stage, focus: o.focus });
    const st = { ratio: null, table: null, sampled: false, draw: null };
    st.draw = function (r) {
      const Tb = st.table, xf = xfadeAt(r, opts.xfade === undefined ? N.assemble.xfade : opts.xfade);
      p.img.style.opacity = xf.img.toFixed(4); canvas.style.opacity = xf.canvas.toFixed(4);
      ctx.setTransform(1, 0, 0, 1, 0, 0); ctx.clearRect(0, 0, canvas.width, canvas.height);
      if (!Tb || r <= 0 || xf.canvas <= 0.002) return;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0); const cell = Math.max(Tb.cw, Tb.ch);
      for (let i = 0; i < Tb.n; i++) {
        const q = particleAt(Tb, i, r); if (q.alpha <= 0) continue;
        const s = q.size * cell; ctx.globalAlpha = q.alpha; ctx.fillStyle = Tb.col[i];
        ctx.fillRect(q.x - R.x - s / 2, q.y - R.y - s / 2, s, s);
      }
      ctx.globalAlpha = 1;
    };
    /* sample the still once it has decoded: the browser's downsample box-filters each cell's colour */
    const ready = p.img.decode().catch(() => {}).then(() => {
      let rgba = null;
      try { const c = document.createElement('canvas'); c.width = g.cols; c.height = g.rows; const cx = c.getContext('2d');
        cx.imageSmoothingEnabled = true; cx.imageSmoothingQuality = 'high'; cx.drawImage(p.img, 0, 0, g.cols, g.rows); rgba = cx.getImageData(0, 0, g.cols, g.rows).data; st.sampled = true; }
      catch (e) { rgba = null; st.sampled = false; }             // tainted canvas (file:// without --allow-file-access-from-files)
      st.table = particleTable(rgba, g, opts, rng(seed)); rec.sampled = st.sampled;
      if (st.ratio !== null) st.draw(st.ratio);                 // a late decode repaints the current frame through the same function
    });
    loads.push(ready);
    cutIn(tl, p.el, T.at);
    tl.to({}, { rvAssemble: keep(st), duration: T.end - T.at, ease: 'none', lazy: false }, T.at);
    cutOut(tl, p.el, T.end);
    const rec = record(Object.assign({ kind: 'assemble', target: R, particles: g.n, cols: g.cols, rows: g.rows, cell: g.cell, seed, sampled: null,
      landedBy: +(T.at + (T.end - T.at) * (1 - N.assemble.xfade)).toFixed(4), handover: 'lane starts at end' }, T));
    rec.ready = ready; return rec;
  }

  /* ------------------------------------------------------------ 3. irisFrom ----------------------------------- */
  if (G) G.registerPlugin({ name: 'rvIris', headless: true, init(t, v) { this.v = STATES[v]; }, render(r, d) { d.v.draw(r); } });
  function irisFrom(tl, o) {
    const el = o.el.el || o.el, R = o.el.rect || rectOf(o.target), T = timing(o, N.iris.dur), origin = o.origin || { x: 50, y: 50 }, ease = o.ease || N.iris.ease;
    const shape = o.shape || N.iris.shape, feather = o.feather === undefined ? N.iris.feather : o.feather, Rmax = irisRadius(origin, R.w, R.h) + feather;
    const ox = origin.x / 100 * R.w, oy = origin.y / 100 * R.h, E = G.parseEase(ease);
    const st = { draw(r) {
      if (r >= 1) { el.style.webkitMaskImage = ''; el.style.maskImage = ''; el.style.clipPath = ''; return; }
      const rad = Rmax * E(r);
      if (shape === 'squircle') { el.style.clipPath = polygonCSS(squircle(ox, oy, Math.max(0.01, rad), Math.max(0.01, rad), o.n, o.points)); return; }
      const inner = Math.max(0, rad - feather), m = 'radial-gradient(circle ' + px(Math.max(0.01, rad)) + ' at ' + px(ox) + ' ' + px(oy) + ', #000 ' + px(inner) + ', rgba(0,0,0,0) ' + px(Math.max(inner + 0.01, rad)) + ')';
      el.style.webkitMaskImage = m; el.style.maskImage = m;
    } };
    st.draw(0);                                                 // initial state = fully masked
    cutIn(tl, el, T.at);
    tl.to({}, { rvIris: keep(st), duration: T.end - T.at, ease: 'none', lazy: false }, T.at);
    let ring = null;
    if (o.ring !== false) {
      const rg = Object.assign({}, N.iris.ring, o.ring || {}), h = o.host || el.parentNode;
      ring = mk('div', h, 'position:absolute;left:' + px(R.x + ox) + ';top:' + px(R.y + oy) + ';width:0;height:0;border:' + rg.width + 'px solid ' + rg.colour + ';border-radius:50%;opacity:0;box-sizing:border-box');
      tw(tl, ring, { width: 0, height: 0, xPercent: -50, yPercent: -50, opacity: 0.9 }, { width: rg.size, height: rg.size, xPercent: -50, yPercent: -50, opacity: 0, duration: rg.dur, ease: 'power2.out' }, T.at);
    }
    return record(Object.assign({ kind: 'irisFrom', target: R, origin, shape, feather, radius: +Rmax.toFixed(2), ring: !!ring, handover: 'optional: lane may start at end' }, T));
  }

  /* ------------------------------------------------------------ 4. lightWipe ---------------------------------- */
  if (G) G.registerPlugin({ name: 'rvWipe', headless: true, init(t, v) { this.v = STATES[v]; }, render(r, d) { d.v.draw(r); } });
  function lightWipe(tl, o) {
    const el = o.el.el || o.el, R = o.el.rect || rectOf(o.target), T = timing(o, N.wipe.dur), W = Object.assign({}, N.wipe, o);
    const h = o.host || el.parentNode, th = W.angle * Math.PI / 180, tan = Math.tan(th), E = G.parseEase(W.ease || N.wipe.ease);
    const band = mk('div', h, 'position:absolute;left:0;top:0;width:' + px(W.width) + ';height:' + px(R.h * 1.6) + ';opacity:0;mix-blend-mode:' + W.blend +
      ';background:linear-gradient(90deg,rgba(' + W.colour + ',0) 0%,rgba(' + W.colour + ',1) 50%,rgba(' + W.colour + ',0) 100%);transform-origin:50% 50%;pointer-events:none');
    const run = R.w + Math.abs(tan) * R.h + W.width;             // the edge travels from fully off the left to fully off the right
    const st = { draw(r) {
      if (r >= 1) { el.style.clipPath = ''; band.style.opacity = '0'; return; }
      const u = E(r), e = -Math.abs(tan) * R.h / 2 - W.width / 2 + run * u;          // edge x at mid-height (element px)
      const xt = e - tan * (R.h / 2), xb = e + tan * (R.h / 2);
      el.style.clipPath = 'polygon(' + px(-2 * R.w) + ' 0,' + px(xt) + ' 0,' + px(xb) + ' ' + px(R.h) + ',' + px(-2 * R.w) + ' ' + px(R.h) + ')';
      band.style.transform = 'translate(' + px(R.x + e - W.width / 2) + ',' + px(R.y - R.h * 0.3) + ') rotate(' + W.angle + 'deg)';
      band.style.opacity = (W.peak * Math.pow(Math.sin(Math.PI * clamp(r, 0, 1)), W.soft)).toFixed(4);
    } };
    st.draw(0);
    cutIn(tl, el, T.at);
    tl.to({}, { rvWipe: keep(st), duration: T.end - T.at, ease: 'none', lazy: false }, T.at);
    if (o.card) cutOut(tl, o.card.el || o.card, T.end);
    return record(Object.assign({ kind: 'lightWipe', target: R, angle: W.angle, width: W.width, peak: W.peak, blend: W.blend, handover: 'lane starts at end' }, T));
  }

  /* ------------------------------------------------------------ 5. matchCutHandover --------------------------- */
  function matchCutHandover(tl, o) {
    const fps = o.fps || N.fps, at = snap(o.at === undefined ? 0 : o.at, fps), settle = o.settle === undefined ? N.match.settle : o.settle, ease = o.ease || N.match.ease;
    const fromEl = o.from.el && o.from.el.el ? o.from.el.el : o.from.el, toEl = o.to.el && o.to.el.el ? o.to.el.el : o.to.el;
    const fr = rectOf(o.from.rect || (o.from.el && o.from.el.rect)), tr = rectOf(o.to.rect || (o.to.el && o.to.el.rect)), F = fit(fr, tr, o.mode);
    const from = { x: F.x, y: F.y, scaleX: F.scaleX, scaleY: F.scaleY, transformOrigin: '0 0' };
    if (fromEl) cutOut(tl, fromEl, at);
    if (o.cut !== false) cutIn(tl, toEl, at);
    if (settle > 0) tw(tl, toEl, from, { x: 0, y: 0, scaleX: 1, scaleY: 1, transformOrigin: '0 0', duration: settle, ease }, at);
    else tw(tl, toEl, from, Object.assign({ duration: N.cut, ease: 'none' }, from), at - N.cut);   // hold the aligned transform from the cut frame on
    return record({ kind: 'matchCutHandover', at, dur: settle, end: +(at + settle).toFixed(6), frame: frameOf(at, fps), fps, transform: F, from: fr, to: tr, handover: 'from cuts out, to cuts in on frame' });
  }

  /* ------------------------------------------------------------ receipts, pending ----------------------------- */
  function pending() { return loads.length ? Promise.all(loads.splice(0)) : undefined; }
  const list = () => receipts.map(r => { const c = Object.assign({}, r); delete c.ready; return c; });

  /* ------------------------------------------------------------ node CLI -------------------------------------- */
  function selftest(json) {
    const out = { ok: true, checks: [] }, add = (name, pass, detail) => { out.checks.push({ name, pass: !!pass, detail }); if (!pass) out.ok = false; };
    const g = grid([0, 0, 1280, 720], 6000);
    add('grid 6000 → 103×58 cells of 12.39 px', g.cols === 103 && g.rows === 58 && Math.abs(g.cell - 12.394) < 0.01, g);
    add('grid clamps to [4000, 9000]', grid([0, 0, 1280, 720], 100).n >= 3800 && grid([0, 0, 1280, 720], 50000).n <= 9400, [grid([0, 0, 1280, 720], 100).n, grid([0, 0, 1280, 720], 50000).n]);
    const rgba = new Uint8ClampedArray(g.n * 4); for (let i = 0; i < g.n; i++) { rgba[i * 4] = (i * 7) & 255; rgba[i * 4 + 1] = (i * 13) & 255; rgba[i * 4 + 2] = (i * 29) & 255; rgba[i * 4 + 3] = 255; }
    const A = particleTable(rgba, g, { seed: 7 }, rng(7)), B = particleTable(rgba, g, { seed: 7 }, rng(7)), C = particleTable(rgba, g, { seed: 8 }, rng(8));
    let same = true, diff = 0; for (let i = 0; i < A.n; i++) { if (A.x0[i] !== B.x0[i] || A.delay[i] !== B.delay[i] || A.qx[i] !== B.qx[i]) same = false; if (A.x0[i] !== C.x0[i]) diff++; }
    add('same seed → identical table', same, A.n + ' particles'); add('other seed → different starts', diff > A.n * 0.9, diff + ' of ' + A.n + ' differ');
    let landed = 0, inside = 0, maxLand = 0; for (let i = 0; i < A.n; i++) { const q = particleAt(A, i, 0.9); if (q.u >= 1) landed++; if (Math.abs(q.x - A.x1[i]) < 1e-3 && Math.abs(q.y - A.y1[i]) < 1e-3) inside++; maxLand = Math.max(maxLand, A.delay[i] + A.flight); }
    add('every particle landed by 90 % of the window', landed === A.n && inside === A.n, { landed, n: A.n, lastLanding: +maxLand.toFixed(4), window: A.dur });
    const q0 = particleAt(A, 0, 0); add('nothing drawn at ratio 0', q0.alpha === 0 && q0.u === 0, q0);
    const far = Math.min.apply(null, Array.from(A.x0).map((x, i) => Math.hypot(x - 640, A.y0[i] - 360)));
    add('starts are ≥ 0.55 half-diagonals from the focus (minus jitter)', far > 0.5 * Math.hypot(1280, 720) / 2 - 1, +far.toFixed(1));
    add('colour comes from the sampled cell', A.col[5] === 'rgb(35,65,145)' && A.sampled, A.col[5]);
    const F = fit([320, 180, 640, 360], [0, 0, 1280, 720]); add('fit: 16:9 card over the stage = scale 0.5 at (320,180)', F.scaleX === 0.5 && F.scaleY === 0.5 && F.x === 320 && F.y === 180 && F.uniform, F);
    const F2 = fit([100, 100, 600, 160], [0, 0, 1280, 720]); add('fit: uniform centres a mismatched aspect', F2.scaleX === F2.scaleY && Math.abs(F2.x - (100 + (600 - 1280 * F2.scaleX) / 2)) < 0.01 && F2.aspect > 0.01, F2);
    add('snap: 0.9 s is frame 27, 1.2+1.4 lands on frame 78', frameOf(0.9) === 27 && frameOf(1.4 + 1.2) === 78 && snap(0.91) === 0.9, [frameOf(0.9), frameOf(2.6)]);
    const t1 = timing({ land: 2.6, dur: 1.2 }, 0.9); add('land keys the end frame', t1.at === 1.4 && t1.end === 2.6 && t1.frame === 78, t1);
    add('iris radius: from (86 %, 9 %) of 1280×720 the far corner (0, 720) is 1281.0 px', Math.abs(irisRadius({ x: 86, y: 9 }, 1280, 720) - 1281.03) < 0.1, +irisRadius({ x: 86, y: 9 }, 1280, 720).toFixed(2));
    const sq = squircle(0, 0, 100, 100, 4, 64); add('squircle: 64 points on |x|^4+|y|^4 = 100^4', sq.length === 64 && sq.every(p => Math.abs(Math.pow(Math.abs(p[0]), 4) + Math.pow(Math.abs(p[1]), 4) - 1e8) < 1e8 * 1e-6), sq[8].map(v => +v.toFixed(2)));
    const xf = xfadeAt(0.95, 0.1); add('cross-fade: canvas and image sum to 1 and cross at 95 %', Math.abs(xf.canvas + xf.img - 1) < 1e-9 && Math.abs(xf.img - 0.5) < 1e-9, xf);
    const pl = plan({ kind: 'assemble', at: 1.4, particles: 6000, seed: 3 }); add('plan: assemble receipt', pl.end === 2.6 && pl.frame === 78 && pl.particles === 5974 && pl.landedBy === 2.48, pl);
    add('HARD ease is 0 before the last tick and 1 on it', HARD(0.999) === 0 && HARD(1) === 1, null);
    if (json) console.log(JSON.stringify(out, null, 1)); else { out.checks.forEach(c => console.log((c.pass ? 'PASS  ' : 'FAIL  ') + c.name + (c.pass ? '' : '  ' + JSON.stringify(c.detail)))); console.log(out.ok ? 'selftest ok (' + out.checks.length + ' checks)' : 'selftest FAILED'); }
    return out.ok ? 0 : 1;
  }
  function cli(argv) {
    const fs = require('fs');
    if (!argv.length || argv.indexOf('--help') >= 0 || argv.indexOf('-h') >= 0) {
      console.log('reveals.js — opener / closer reveals of real stills (pure part)\n  node lib/reveals.js --selftest [--json]\n  node lib/reveals.js --plan <json | file.json>   {"kind":"heroDive|pullBack|assemble|irisFrom|lightWipe|matchCutHandover","at"|"land",...}\n  exit 0 ok · 1 findings · 2 usage');
      return argv.length ? 0 : 2;
    }
    if (argv.indexOf('--selftest') >= 0) return selftest(argv.indexOf('--json') >= 0);
    const i = argv.indexOf('--plan');
    if (i >= 0) {
      const src = argv[i + 1]; if (!src) { console.error('--plan needs JSON or a file'); return 2; }
      let o; try { o = JSON.parse(fs.existsSync(src) ? fs.readFileSync(src, 'utf8') : src); } catch (e) { console.error('bad JSON: ' + e.message); return 2; }
      const plans = (Array.isArray(o) ? o : [o]).map(plan); console.log(JSON.stringify(Array.isArray(o) ? plans : plans[0], null, 1)); return 0;
    }
    console.error('unknown arguments: ' + argv.join(' ')); return 2;
  }

  const REVEAL = { N, HARD, rng, hash, frameOf, snap, timing, fit, irisRadius, squircle, grid, particleTable, particleAt, xfadeAt, plan, list, pending,
    host: HAS_DOM ? host : null, mount: HAS_DOM ? mount : null, heroDive, pullBack, assemble, irisFrom, lightWipe, matchCutHandover };
  root.REVEAL = REVEAL;
  if (typeof module !== 'undefined' && module.exports) { module.exports = REVEAL; if (require.main === module) process.exit(cli(process.argv.slice(2))); }
})(typeof window !== 'undefined' ? window : globalThis);
