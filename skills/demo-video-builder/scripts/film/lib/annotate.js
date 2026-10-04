/* annotate.js — ANNOTATE: a human hand over real footage (lib/motion.js + GSAP). Marks sit in a screen-space layer the
   scene owns (#ovl or a sibling of the footage lane), never inside it: product pixels are read, never redrawn.

   Why hand-drawn. A perfect ellipse around a figure reads as a UI element the product might have drawn; a slightly
   wobbly one, drawn on in half a second and boiling a little while it holds, reads as a person pointing. Every path
   here is generated from a seeded generator (MOTION.rng), so the wobble is the same in every worker and every run.

   The measured numbers (defaults; every helper takes overrides)
     stroke     coral #E56B5E, 3 px on screen (the stroke-width attribute is divided by the camera scale every frame
                so a zoom never fattens the line), round joins, cap 'butt' while drawing then 'round' once drawn
     draw-on    0.45 s power2.out via stroke-dashoffset: each variant's length is measured ONCE at build
     boil       3 path variants (seed, seed+1, seed+2) swapped every 3 frames, plus a jitter of ±1.6 px / ±0.5° around
                the mark's centre from a generator seeded by (seed, step) — a pure function of the frame index
     circle     24-point wobbly ellipse, radial noise ±4.5 %, 1.08 turns so the end overlaps the start, padding 1.22×
     arrow      quadratic shaft (bend 0.18 of its length) from a `from` point to the rect's nearest edge (8 px off),
                open V head 14 px at ±28°, drawn after the shaft
     box        wobbly rounded rectangle: 6 points a side, ±1.2 px, 12 px overshoot past the start corner
     underline  wavy line 6 px under the rect with a 2 px downward bow; strike: through the centre, tilt −2°, 6 % overshoot
     spotlight  dim rgba(6,8,12,.55) over the whole stage with a radial hole: transparent to 52 %, opaque from 88 %, the
                52 % ring at 1.15× the rect's half-extent; glide between rects 0.8 s power2.inOut; fade in .35 s, out .30 s
     label      a small tag (navy, ink text 13 px, coral left bar) with a 1.5 px leader line to the rect edge and a 3 px
                dot where it lands; tag size never scales with the camera; arrives 0.35 s, leader draws 0.3 s

   Coordinates. A rect {x, y, w, h} is given in FOOTAGE coordinates (source px of the recording). project(rect) → the
   same rect on the 1280×720 stage for the current camera. ANNOTATE.projector(() => pose, K) builds one from a pose
   {s, cx, cy} (the value applyCam used this frame) and K = 1280 / sourceWidth. Call MOTION.seek(t) AFTER the camera
   pose for frame t is resolved — the marks read the pose when they paint.

   Gate rule (for gates/annotate_gate.py, to come): a mark must sit on a claims.json figure or on a logged click (the
   recording's own cursor event), never across product text. ANNOTATE.ledger() returns every mark with its rect and
   times; ANNOTATE.lint(ledger, { claims: [rects], clicks: [points] }) applies the rule as pure arithmetic.

   Scene wiring
     <script src="../node_modules/gsap/dist/gsap.min.js"></script><script src="lib/motion.js"></script>
     <script src="lib/annotate.js"></script>
     ANNOTATE.install({ host: $('#ovl'), project: ANNOTATE.projector(() => poseNow, 1280 / 1920), fps: 30 });
     MOTION.block('kpiMarks', (tl, el, api) => {
       ANNOTATE.circle(tl, { x: 1210, y: 262, w: 190, h: 70 }, 0.2, { until: api.exitAt, seed: 11 });
       ANNOTATE.spotlight(tl, [{ rect: KPI, at: 0 }, { rect: ROW, at: 1.8 }], 0, { until: api.exitAt });
       ANNOTATE.label(tl, KPI, 0.7, { text: 'open claims', side: 'right' });
     }, { start: P.kpi, end: P.close, exit: 0.3 });

   Node (no DOM): node lib/annotate.js --help | --selftest | --shape circle|arrow|box|underline|strike --rect x,y,w,h
                  [--seed 7] [--from x,y]  |  --lint marks.json   JSON in / JSON out; exit 0 ok, 1 findings, 2 usage. */
(function (root) {
  'use strict';
  const IS_NODE = typeof window === 'undefined';
  const clamp = (x, a, b) => Math.max(a, Math.min(b, x));
  const num = (v, d) => (v === undefined || v === null || Number.isNaN(v) ? d : v);
  const motion = () => { const m = root.MOTION; if (!m) throw new Error('annotate.js: load gsap and lib/motion.js before lib/annotate.js'); return m; };
  const SVGNS = 'http://www.w3.org/2000/svg';

  const tokens = {
    stroke: '#E56B5E', width: 3, draw: 0.45, drawEase: 'power2.out', fadeOut: 0.25, fps: 30,
    boil: { px: 1.6, deg: 0.5, every: 3, variants: 3 },
    circle: { n: 24, noise: 0.045, turns: 1.08, pad: 1.22, minPad: 8, start: 200 },
    arrow: { bend: 0.18, head: 14, headDeg: 28, gap: 8, from: [0.75, 0.5, 90, 70] },
    box: { perSide: 6, noise: 1.2, pad: 6, overshoot: 12 },
    underline: { below: 6, noise: 1.2, bow: 2, n: 8, over: [4, 6] }, strike: { noise: 1.0, tilt: -2, over: 0.06, n: 6 },
    spotlight: { dim: 'rgba(6,8,12,.55)', clear: 0.52, opaque: 0.88, pad: 1.15, glide: 0.8, glideEase: 'power2.inOut', fadeIn: 0.35, fadeOut: 0.30 },
    label: { gap: 26, font: '600 13px/1 Arial, "Segoe UI", sans-serif', bg: '#082A34', ink: '#E9F3F9', leader: 1.5, dot: 3, arrive: 0.35, leaderDraw: 0.3 }
  };

  /* ------------------------------------------------------------------ seeded generator --------------------------- */
  /* mulberry32 seeded by (seed, step): the same (seed, step) always yields the same stream — the boil is a pure function */
  function rngFor(seed, step) {
    let s = ((seed | 0) * 0x9E3779B1 + ((step | 0) + 1) * 0x85EBCA77) >>> 0; if (!s) s = 1;
    return () => { s = (s + 0x6D2B79F5) >>> 0; let x = Math.imul(s ^ (s >>> 15), 1 | s); x ^= x + Math.imul(x ^ (x >>> 7), 61 | x); return ((x ^ (x >>> 14)) >>> 0) / 4294967296; };
  }
  const easeFn = { 'power2.out': u => 1 - (1 - u) * (1 - u), 'power2.in': u => u * u, 'power2.inOut': u => (u < 0.5 ? 2 * u * u : 1 - Math.pow(-2 * u + 2, 2) / 2), none: u => u };
  const E = (name, u) => (easeFn[name] || easeFn['power2.out'])(clamp(u, 0, 1));

  /* ------------------------------------------------------------------ path geometry (pure) ----------------------- */
  const f2 = v => (Math.round(v * 100) / 100).toString();
  /* Catmull-Rom through points → cubic Béziers (open polyline); tension 1 = classic */
  function smooth(pts) {
    if (pts.length < 2) return '';
    let d = 'M' + f2(pts[0][0]) + ' ' + f2(pts[0][1]);
    for (let i = 0; i < pts.length - 1; i++) {
      const p0 = pts[Math.max(0, i - 1)], p1 = pts[i], p2 = pts[i + 1], p3 = pts[Math.min(pts.length - 1, i + 2)];
      const c1 = [p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6], c2 = [p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6];
      d += 'C' + [c1[0], c1[1], c2[0], c2[1], p2[0], p2[1]].map(f2).join(' ');
    }
    return d;
  }
  const poly = pts => pts.map((p, i) => (i ? 'L' : 'M') + f2(p[0]) + ' ' + f2(p[1])).join('');

  function circlePath(r, seed, o) {
    o = o || {}; const C = tokens.circle, g = rngFor(seed, 0), n = num(o.n, C.n), turns = num(o.turns, C.turns), noise = num(o.noise, C.noise);
    const cx = r.x + r.w / 2, cy = r.y + r.h / 2, rx = Math.max(r.w / 2 * num(o.pad, C.pad), r.w / 2 + C.minPad), ry = Math.max(r.h / 2 * num(o.pad, C.pad), r.h / 2 + C.minPad);
    const a0 = num(o.start, C.start) * Math.PI / 180, pts = [];
    for (let i = 0; i <= n; i++) {
      const u = i / n, a = a0 + u * turns * 2 * Math.PI, k = 1 + (g() * 2 - 1) * noise + 0.03 * u;   // the loop ends a touch outside where it began
      pts.push([cx + rx * k * Math.cos(a), cy + ry * k * Math.sin(a)]);
    }
    return smooth(pts);
  }
  function boxPath(r, seed, o) {
    o = o || {}; const B = tokens.box, g = rngFor(seed, 0), pad = num(o.pad, B.pad), per = num(o.perSide, B.perSide), nz = num(o.noise, B.noise), ov = num(o.overshoot, B.overshoot);
    const x0 = r.x - pad, y0 = r.y - pad, x1 = r.x + r.w + pad, y1 = r.y + r.h + pad, pts = [], j = () => (g() * 2 - 1) * nz;
    const side = (ax, ay, bx, by, from, to) => { for (let i = from; i <= to; i++) { const u = i / per; pts.push([ax + (bx - ax) * u + (ax === bx ? j() : 0), ay + (by - ay) * u + (ay === by ? j() : 0)]); } };
    side(x0 + 10, y0, x1, y0, 0, per); side(x1, y0, x1, y1, 1, per); side(x1, y1, x0, y1, 1, per); side(x0, y1, x0, y0, 1, per); pts.push([x0 + 10 + ov, y0 + j()]);
    return poly(pts);
  }
  function underlinePath(r, seed, o) {
    o = o || {}; const U = tokens.underline, g = rngFor(seed, 0), n = num(o.n, U.n), y = r.y + r.h + num(o.below, U.below), pts = [];
    for (let i = 0; i <= n; i++) { const u = i / n; pts.push([r.x - U.over[0] + (r.w + U.over[0] + U.over[1]) * u, y + Math.sin(Math.PI * u) * num(o.bow, U.bow) + (g() * 2 - 1) * num(o.noise, U.noise)]); }
    return smooth(pts);
  }
  function strikePath(r, seed, o) {
    o = o || {}; const S = tokens.strike, g = rngFor(seed, 0), n = num(o.n, S.n), tilt = Math.tan(num(o.tilt, S.tilt) * Math.PI / 180), ov = r.w * num(o.over, S.over), pts = [];
    for (let i = 0; i <= n; i++) { const u = i / n, x = r.x - ov + (r.w + 2 * ov) * u; pts.push([x, r.y + r.h / 2 + (x - (r.x + r.w / 2)) * tilt + (g() * 2 - 1) * num(o.noise, S.noise)]); }
    return smooth(pts);
  }
  /* nearest point on the padded rect boundary to p */
  function edgeTowards(r, p, gap) {
    const x0 = r.x - gap, y0 = r.y - gap, x1 = r.x + r.w + gap, y1 = r.y + r.h + gap, cx = (x0 + x1) / 2, cy = (y0 + y1) / 2;
    const dx = p[0] - cx, dy = p[1] - cy; if (!dx && !dy) return [x1, cy];
    const k = Math.min(Math.abs((x1 - x0) / 2 / (dx || 1e-9)), Math.abs((y1 - y0) / 2 / (dy || 1e-9)));
    return [cx + dx * k, cy + dy * k];
  }
  function arrowPath(r, seed, o) {
    o = o || {}; const A = tokens.arrow, g = rngFor(seed, 0);
    const from = o.from || [r.x + r.w * A.from[0] + A.from[2], r.y + r.h * A.from[1] + A.from[3]];
    const to = edgeTowards(r, from, num(o.gap, A.gap)), vx = to[0] - from[0], vy = to[1] - from[1], len = Math.hypot(vx, vy) || 1;
    const side = o.side || (g() < 0.5 ? -1 : 1), bend = num(o.bend, A.bend) * len * side;
    const c = [(from[0] + to[0]) / 2 - vy / len * bend + (g() * 2 - 1) * 2, (from[1] + to[1]) / 2 + vx / len * bend + (g() * 2 - 1) * 2];
    const tx = to[0] - c[0], ty = to[1] - c[1], tl = Math.hypot(tx, ty) || 1, ang = Math.atan2(ty, tx), hd = num(o.head, A.head), ha = num(o.headDeg, A.headDeg) * Math.PI / 180;
    const h1 = [to[0] - hd * Math.cos(ang - ha), to[1] - hd * Math.sin(ang - ha)], h2 = [to[0] - hd * Math.cos(ang + ha), to[1] - hd * Math.sin(ang + ha)];
    return 'M' + [from[0], from[1]].map(f2).join(' ') + 'Q' + [c[0], c[1], to[0], to[1]].map(f2).join(' ') + 'M' + [to[0], to[1]].map(f2).join(' ') + 'L' + h1.map(f2).join(' ') + 'M' + [to[0], to[1]].map(f2).join(' ') + 'L' + h2.map(f2).join(' ');
  }
  const SHAPES = { circle: circlePath, arrow: arrowPath, box: boxPath, underline: underlinePath, strike: strikePath };
  /* the boil state at a block-local time: variant index and jitter (px, px, deg) — pure in (seed, frame) */
  function boilAt(sLocal, seed, o) {
    // step >= 0: a mark whose `at` sits a few ms before its block start paints at a negative local time, and a negative step
    // indexed variants[-1] (TypeError at build); the first boil state simply holds until the clock reaches the mark
    o = o || {}; const B = tokens.boil, fps = num(o.fps, tokens.fps), step = Math.max(0, Math.floor(Math.round(sLocal * fps) / num(o.every, B.every)));
    const g = rngFor(seed + 101, step), px = num(o.px, B.px), deg = num(o.deg, B.deg);
    return { step, variant: step % num(o.variants, B.variants), jx: (g() * 2 - 1) * px, jy: (g() * 2 - 1) * px, rot: (g() * 2 - 1) * deg };
  }
  /* projector: pose {s, cx, cy} on the stage (what applyCam used) + K = 1280 / sourceWidth → project(rect) */
  function projector(poseFn, K) {
    K = num(K, 1280 / 1920);
    return rect => { const p = poseFn() || { s: 1, cx: 640, cy: 360 }, S = p.s || 1;
      return { x: 640 + S * (rect.x * K - p.cx), y: 360 + S * (rect.y * K - p.cy), w: rect.w * K * S, h: rect.h * K * S }; };
  }
  const identity = r => ({ x: r.x, y: r.y, w: r.w, h: r.h });
  /* spotlight rect at local time s over stops [{rect, at}] (at relative to the spotlight's own `at`) */
  function spotRectAt(s, stops, o) {
    o = o || {}; const SP = tokens.spotlight, glide = num(o.glide, SP.glide);
    let cur = stops[0].rect;
    for (let i = 1; i < stops.length; i++) {
      const st = stops[i]; if (s < st.at) break;
      const u = E(o.glideEase || SP.glideEase, (s - st.at) / glide), a = cur, b = st.rect;
      cur = { x: a.x + (b.x - a.x) * u, y: a.y + (b.y - a.y) * u, w: a.w + (b.w - a.w) * u, h: a.h + (b.h - a.h) * u };
    }
    return cur;
  }

  /* ------------------------------------------------------------------ plugin + install -------------------------- */
  let pluginReady = false;
  function ensurePlugin() {
    if (pluginReady) return;
    motion().gsap.registerPlugin({ name: 'annotPaint', rawVars: 1, headless: true,
      init(target, fn) { this.fn = typeof fn === 'function' ? fn : () => {}; this.fn(0); }, render(ratio, data) { data.fn(clamp(ratio, 0, 1)); } });
    pluginReady = true;
  }
  const cfg = { host: null, project: identity, fps: tokens.fps, stroke: tokens.stroke, width: tokens.width };
  const marks = [];
  /* ANNOTATE.install({ host, project, fps, stroke, width }) → cfg: host = the screen-space layer marks are appended to */
  function install(o) { Object.assign(cfg, o || {}); if (!cfg.host && !IS_NODE) cfg.host = document.getElementById('ovl') || document.body; return cfg; }
  const hostOf = o => (o && o.host) || cfg.host || install().host;
  function svgIn(host, cls) {
    const svg = document.createElementNS(SVGNS, 'svg'); svg.setAttribute('class', cls); svg.setAttribute('width', '1'); svg.setAttribute('height', '1');
    // no will-change: the mark's transform (camera x boil) changes every frame; a promoted layer rasters it at a scale the compositor
    // picks from that history, so a cold seek and a stepped run disagree (measured on a frosted panel under load: 46/76 frames)
    Object.assign(svg.style, { position: 'absolute', left: '0px', top: '0px', overflow: 'visible', transformOrigin: '0 0', pointerEvents: 'none' });
    host.appendChild(svg); return svg;
  }

  /* ------------------------------------------------------------------ a stroke mark ----------------------------- */
  /* ANNOTATE.<kind>(tl, rect, at, o) → { el, end, until }  — kind ∈ circle | arrow | box | underline | strike
     o: seed (default by mark count) · stroke · width · draw .45 · ease power2.out · until (block-local s; default at+30,
        the block's own window still hides it) · fadeOut .25 · boil {px, deg, every, variants} or false · project · host
        + per-shape geometry (circle: n, noise, turns, pad, start · arrow: from [x,y], bend, side, head, headDeg, gap …) */
  function stroke(kind, tl, rect, at, o) {
    o = o || {}; ensurePlugin();
    const gen = SHAPES[kind], seed = num(o.seed, 7 + marks.length * 13), B = tokens.boil, nv = o.boil === false ? 1 : num(o.boil && o.boil.variants, B.variants);
    const host = hostOf(o), project = o.project || cfg.project, color = o.stroke || cfg.stroke, width = num(o.width, cfg.width);
    const draw = num(o.draw, tokens.draw), until = num(o.until, at + 30), life = Math.max(draw, until - at), fade = num(o.fadeOut, tokens.fadeOut);
    const svg = svgIn(host, 'annot annot-' + kind), path = document.createElementNS(SVGNS, 'path');
    path.setAttribute('fill', 'none'); path.setAttribute('stroke', color); path.setAttribute('stroke-linejoin', 'round'); path.setAttribute('stroke-linecap', 'butt'); svg.appendChild(path);
    // variants and their lengths, measured once at build (the host must be in the DOM)
    const variants = []; for (let v = 0; v < nv; v++) { const d = gen(rect, seed + v, o); path.setAttribute('d', d); variants.push({ d, L: path.getTotalLength() }); }
    const cx = rect.x + rect.w / 2, cy = rect.y + rect.h / 2;
    const rec = { kind, rect, at, drawEnd: at + draw, until, seed, el: svg }; marks.push(rec);
    svg.dataset.annot = kind; svg.dataset.annotRect = [rect.x, rect.y, rect.w, rect.h].join(','); svg.dataset.annotAt = at.toFixed(3);
    const paint = u => {
      const s = u * life, p = E(o.ease || tokens.drawEase, s / draw), b = o.boil === false ? { variant: 0, jx: 0, jy: 0, rot: 0 } : boilAt(at + s, seed, Object.assign({ fps: cfg.fps }, o.boil || {}));
      const V = variants[b.variant], P = project({ x: 0, y: 0, w: 1, h: 1 }), S = P.w || 1;
      if (path.getAttribute('d') !== V.d) path.setAttribute('d', V.d);
      path.setAttribute('stroke-dasharray', f2(V.L)); path.setAttribute('stroke-dashoffset', f2(V.L * (1 - p)));
      path.setAttribute('stroke-width', f2(width / S)); path.setAttribute('stroke-linecap', p >= 1 ? 'round' : 'butt');
      svg.style.transform = 'translate(' + f2(P.x + b.jx) + 'px,' + f2(P.y + b.jy) + 'px) scale(' + S.toFixed(4) + ') translate(' + f2(cx) + 'px,' + f2(cy) + 'px) rotate(' + b.rot.toFixed(3) + 'deg) translate(' + f2(-cx) + 'px,' + f2(-cy) + 'px)';
      svg.style.opacity = (u <= 0 ? 0 : (1 - E('power2.in', (s - (life - fade)) / fade))).toFixed(3);
    };
    paint(0);                                           // frame-0 state now: GSAP initialises the tween lazily on its first render
    tl.to({}, { duration: life, ease: 'none', annotPaint: paint }, at);
    return { el: svg, end: at + draw, until };
  }
  const circle = (tl, r, at, o) => stroke('circle', tl, r, at, o), arrow = (tl, r, at, o) => stroke('arrow', tl, r, at, o), box = (tl, r, at, o) => stroke('box', tl, r, at, o);
  const underline = (tl, r, at, o) => stroke('underline', tl, r, at, o), strike = (tl, r, at, o) => stroke('strike', tl, r, at, o);

  /* ------------------------------------------------------------------ spotlight --------------------------------- */
  /* ANNOTATE.spotlight(tl, rect | [{rect, at}], at, o) → { el, end, until }
     dims the whole stage except a feathered hole over the rect; stops glide 0.8 s power2.inOut; o: until, dim, pad,
     clear .52, opaque .88, glide, fadeIn .35, fadeOut .30, project, host, z */
  function spotlight(tl, rects, at, o) {
    o = o || {}; ensurePlugin(); const SP = tokens.spotlight, host = hostOf(o), project = o.project || cfg.project;
    const stops = Array.isArray(rects) ? rects.map(s => ({ rect: s.rect, at: num(s.at, 0) })) : [{ rect: rects, at: 0 }];
    const until = num(o.until, at + 30), life = until - at, fi = num(o.fadeIn, SP.fadeIn), fo = num(o.fadeOut, SP.fadeOut), pad = num(o.pad, SP.pad);
    const el = document.createElement('div'); el.className = 'annot annot-spotlight';
    Object.assign(el.style, { position: 'absolute', left: '0px', top: '0px', width: (host.offsetWidth || 1280) + 'px', height: (host.offsetHeight || 720) + 'px', background: o.dim || SP.dim, opacity: '0', pointerEvents: 'none', zIndex: String(num(o.z, 1)) });
    host.appendChild(el);
    const rec = { kind: 'spotlight', rect: stops[0].rect, stops, at, drawEnd: at + fi, until, el }; marks.push(rec);
    el.dataset.annot = 'spotlight'; el.dataset.annotAt = at.toFixed(3);
    const paint = u => {
      const s = u * life, r = project(spotRectAt(s, stops, o)), rx = (r.w / 2 * pad) / num(o.clear, SP.clear), ry = (r.h / 2 * pad) / num(o.clear, SP.clear);
      const m = 'radial-gradient(ellipse ' + f2(rx) + 'px ' + f2(ry) + 'px at ' + f2(r.x + r.w / 2) + 'px ' + f2(r.y + r.h / 2) + 'px, rgba(0,0,0,0) ' + Math.round(num(o.clear, SP.clear) * 100) + '%, #000 ' + Math.round(num(o.opaque, SP.opaque) * 100) + '%)';
      el.style.webkitMaskImage = m; el.style.maskImage = m;
      el.style.opacity = (u <= 0 ? 0 : Math.min(E('power2.out', s / fi), 1 - E('power2.in', (s - (life - fo)) / fo))).toFixed(3);
    };
    paint(0);                                           // frame-0 state now: GSAP initialises the tween lazily on its first render
    tl.to({}, { duration: life, ease: 'none', annotPaint: paint }, at);
    return { el, end: at + fi, until };
  }

  /* ------------------------------------------------------------------ label ------------------------------------- */
  /* ANNOTATE.label(tl, rect, at, o) → { el, end, until }: o.text (required), side right|left|above|below, gap 26, until,
     project, host. The tag keeps its screen size; only its anchor follows the camera. */
  function label(tl, rect, at, o) {
    o = o || {}; ensurePlugin(); const LB = tokens.label, host = hostOf(o), project = o.project || cfg.project, side = o.side || 'right', gap = num(o.gap, LB.gap);
    const until = num(o.until, at + 30), life = until - at, fade = num(o.fadeOut, tokens.fadeOut);
    const wrap = document.createElement('div'); wrap.className = 'annot annot-label';
    Object.assign(wrap.style, { position: 'absolute', left: '0px', top: '0px', pointerEvents: 'none', opacity: '0' });   // no will-change (see svgIn)
    const tag = document.createElement('div'); tag.textContent = o.text || '';
    Object.assign(tag.style, { position: 'absolute', left: '0px', top: '0px', font: o.font || LB.font, color: o.ink || LB.ink, background: o.bg || LB.bg, padding: '6px 9px', borderRadius: '4px', borderLeft: '2px solid ' + (o.stroke || cfg.stroke), whiteSpace: 'nowrap', transformOrigin: '0 0' });
    const svg = document.createElementNS(SVGNS, 'svg'); Object.assign(svg.style, { position: 'absolute', left: '0px', top: '0px', overflow: 'visible' }); svg.setAttribute('width', '1'); svg.setAttribute('height', '1');
    const line = document.createElementNS(SVGNS, 'line'), dot = document.createElementNS(SVGNS, 'circle');
    line.setAttribute('stroke', o.stroke || cfg.stroke); line.setAttribute('stroke-width', String(LB.leader)); dot.setAttribute('fill', o.stroke || cfg.stroke); dot.setAttribute('r', String(LB.dot));
    svg.appendChild(line); svg.appendChild(dot); wrap.appendChild(svg); wrap.appendChild(tag); host.appendChild(wrap);
    const tw = tag.offsetWidth || 80, th = tag.offsetHeight || 25;                     // measured once at build
    const rec = { kind: 'label', rect, at, drawEnd: at + LB.arrive, until, text: o.text || '', el: wrap }; marks.push(rec);
    wrap.dataset.annot = 'label'; wrap.dataset.annotRect = [rect.x, rect.y, rect.w, rect.h].join(','); wrap.dataset.annotAt = at.toFixed(3);
    const paint = u => {
      const s = u * life, r = project(rect), a = E('power2.out', s / LB.arrive), ld = E('power2.out', (s - LB.arrive * 0.4) / LB.leaderDraw);
      let ax, ay, tx, ty;                                                                   // anchor on the rect edge, tag origin
      if (side === 'left') { ax = r.x - 2; ay = r.y + r.h / 2; tx = ax - gap - tw; ty = ay - th / 2; }
      else if (side === 'above') { ax = r.x + r.w / 2; ay = r.y - 2; tx = ax - tw / 2; ty = ay - gap - th; }
      else if (side === 'below') { ax = r.x + r.w / 2; ay = r.y + r.h + 2; tx = ax - tw / 2; ty = ay + gap; }
      else { ax = r.x + r.w + 2; ay = r.y + r.h / 2; tx = ax + gap; ty = ay - th / 2; }
      const nx = side === 'left' ? tx + tw : side === 'right' ? tx : tx + tw / 2, ny = side === 'above' ? ty + th : side === 'below' ? ty : ty + th / 2;
      tag.style.transform = 'translate(' + f2(tx) + 'px,' + f2(ty + (1 - a) * 8) + 'px)'; tag.style.opacity = a.toFixed(3);
      line.setAttribute('x1', f2(nx)); line.setAttribute('y1', f2(ny)); line.setAttribute('x2', f2(nx + (ax - nx) * ld)); line.setAttribute('y2', f2(ny + (ay - ny) * ld));
      dot.setAttribute('cx', f2(ax)); dot.setAttribute('cy', f2(ay)); dot.setAttribute('opacity', (ld >= 1 ? 1 : 0).toString());
      wrap.style.opacity = (u <= 0 ? 0 : 1 - E('power2.in', (s - (life - fade)) / fade)).toFixed(3);
    };
    paint(0);                                           // frame-0 state now: GSAP initialises the tween lazily on its first render
    tl.to({}, { duration: life, ease: 'none', annotPaint: paint }, at);
    return { el: wrap, end: at + LB.arrive, until };
  }

  /* ------------------------------------------------------------------ ledger + lint ----------------------------- */
  function ledger() { return marks.map(m => ({ kind: m.kind, rect: m.rect, stops: m.stops ? m.stops.map(s => ({ rect: s.rect, at: s.at })) : undefined, at: m.at, drawEnd: m.drawEnd, until: m.until, seed: m.seed, text: m.text })); }
  const hit = (r, p, tol) => p[0] >= r.x - tol && p[0] <= r.x + r.w + tol && p[1] >= r.y - tol && p[1] <= r.y + r.h + tol;
  const overlap = (a, b) => a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
  /* the gate rule as arithmetic: each stroke/label rect must overlap a claims figure rect or contain a logged click
     (tolerance 12 px); spotlights are exempt (they frame, they do not point). Without evidence lists, only the
     same-time stacking check runs (> 2 strokes drawn at once is a finding). */
  function lint(led, ev) {
    led = led || ledger(); ev = ev || {}; const out = [], claims = ev.claims || null, clicks = ev.clicks || null, tol = num(ev.tol, 12);
    led.forEach((m, i) => {
      if (m.kind === 'spotlight') return;
      if (claims || clicks) {
        const onClaim = (claims || []).some(c => overlap(m.rect, c)), onClick = (clicks || []).some(p => hit(m.rect, p, tol));
        if (!onClaim && !onClick) out.push({ rule: 'mark_off_evidence', i, kind: m.kind, msg: m.kind + ' at ' + m.at + ' s sits on no claims figure and no logged click' });
      }
    });
    const strokes = led.filter(m => m.kind !== 'spotlight' && m.kind !== 'label');
    strokes.forEach((m, i) => { const n = strokes.filter(x => x.at < m.drawEnd && m.at < x.drawEnd).length; if (n > 2) out.push({ rule: 'marks_stacked', i, msg: n + ' marks drawing at once around ' + m.at + ' s (max 2)' }); });
    return out;
  }

  const ANNOTATE = { tokens, install, projector, circle, arrow, box, underline, strike, spotlight, label, ledger, lint,
                     geo: { circlePath, arrowPath, boxPath, underlinePath, strikePath, boilAt, spotRectAt, edgeTowards, rngFor } };
  root.ANNOTATE = ANNOTATE;

  /* ------------------------------------------------------------------ node CLI ----------------------------------- */
  function selftest() {
    const fails = [], R = { x: 100, y: 80, w: 200, h: 60 };
    Object.keys(SHAPES).forEach(k => {
      const a = SHAPES[k](R, 7), b = SHAPES[k](R, 7), c = SHAPES[k](R, 8);
      if (a !== b) fails.push(k + ': same seed, different path'); if (a === c) fails.push(k + ': different seed, same path'); if (!/^M/.test(a)) fails.push(k + ': path does not start with M');
    });
    // circle: 24 segments + the closing overlap → 25 cubic segments; it stays outside the rect
    const cd = circlePath(R, 3); if ((cd.match(/C/g) || []).length !== 24) fails.push('circle: expected 24 Bézier segments, got ' + (cd.match(/C/g) || []).length);
    // arrow: lands 8 px off the rect's right edge when fired from the lower right; head has two strokes
    const ad = arrowPath(R, 5, { from: [500, 110] }); if ((ad.match(/M/g) || []).length !== 3) fails.push('arrow: expected shaft + 2 head strokes');
    const tip = edgeTowards(R, [500, 110], 8); if (Math.abs(tip[0] - 308) > 1e-9 || Math.abs(tip[1] - 110) > 1e-9) fails.push('arrow tip: ' + tip);
    // boil: pure in (seed, frame); steps every 3 frames; within ±1.6 px / ±0.5°
    const b1 = boilAt(1.0, 7, { fps: 30 }), b2 = boilAt(1.0, 7, { fps: 30 }), b3 = boilAt(1.0 + 1 / 30, 7, { fps: 30 }), b4 = boilAt(1.0 + 3 / 30, 7, { fps: 30 });
    if (JSON.stringify(b1) !== JSON.stringify(b2)) fails.push('boil not pure'); if (b1.step !== b3.step) fails.push('boil stepped within 3 frames'); if (b1.step === b4.step) fails.push('boil did not step after 3 frames');
    for (let f = 0; f < 300; f++) { const b = boilAt(f / 30, 11, { fps: 30 }); if (Math.abs(b.jx) > 1.6 || Math.abs(b.jy) > 1.6 || Math.abs(b.rot) > 0.5) fails.push('boil out of range at frame ' + f); }
    const bn = boilAt(-0.004, 7, { fps: 30 }); if (bn.step !== 0 || bn.variant !== 0) fails.push('boil at a negative local time must hold step 0: ' + JSON.stringify(bn));
    if (boilAt(-0.4, 7, { fps: 30 }).variant < 0) fails.push('boil variant went negative');
    // spotlight glide: parked, half-way at 0.4 s of a 0.8 s glide, arrived at 0.8 s
    const stops = [{ rect: R, at: 0 }, { rect: { x: 400, y: 300, w: 100, h: 40 }, at: 1 }];
    if (spotRectAt(0.5, stops).x !== 100) fails.push('spotlight moved before its stop'); if (Math.abs(spotRectAt(1.4, stops).x - 250) > 1e-9) fails.push('spotlight glide midpoint: ' + spotRectAt(1.4, stops).x);
    if (spotRectAt(2, stops).x !== 400) fails.push('spotlight did not arrive');
    // projector: pose {s:1.6, cx:940, cy:225} on a 1920 recording maps the source rect like applyCam does
    const pr = projector(() => ({ s: 1.6, cx: 940, cy: 225 }), 1280 / 1920)({ x: 1410, y: 337.5, w: 300, h: 150 });
    if (Math.abs(pr.x - (640 + 1.6 * (940 - 940))) > 1e-9 || Math.abs(pr.w - 320) > 1e-9) fails.push('projector: ' + JSON.stringify(pr));
    // lint: a mark on a claim passes, one off evidence is a finding
    const led = [{ kind: 'circle', rect: R, at: 0, drawEnd: 0.45, until: 3 }, { kind: 'box', rect: { x: 900, y: 900, w: 10, h: 10 }, at: 0, drawEnd: 0.45, until: 3 }];
    const f = lint(led, { claims: [{ x: 120, y: 90, w: 50, h: 20 }] }); if (f.length !== 1 || f[0].i !== 1) fails.push('lint evidence rule: ' + JSON.stringify(f));
    if (root.MOTION) {                                           // the timeline-driven paint is seek-order independent
      ensurePlugin(); const tl = root.MOTION.gsap.timeline({ paused: true }); const seen = {};
      tl.to({}, { duration: 3, ease: 'none', annotPaint: u => { seen.b = JSON.stringify(boilAt(u * 3, 7)); } }, 0);
      tl.totalTime(1.7, true); const a = seen.b; tl.totalTime(2.9, true); tl.totalTime(0.1, true); tl.totalTime(1.7, true);
      if (a === undefined || a !== seen.b) fails.push('seek order changed the boil');
    }
    return { ok: !fails.length, fails, gsap: !!root.MOTION, samples: { circle: circlePath(R, 7).slice(0, 60) + '…', boil_1s: boilAt(1, 7), arrowTip: tip } };
  }
  function cli(argv) {
    const arg = (k, d) => { const i = argv.indexOf(k); return i >= 0 && argv[i + 1] !== undefined ? argv[i + 1] : d; };
    const out = s => process.stdout.write(JSON.stringify(s, null, 2) + '\n');
    if (argv.includes('--help') || argv.includes('-h') || !argv.length) {
      process.stdout.write('annotate.js — hand-drawn mark geometry (pure) and selftest\n  node lib/annotate.js --selftest\n  node lib/annotate.js --shape circle|arrow|box|underline|strike --rect x,y,w,h [--seed 7] [--from x,y] [--variants 3]\n  node lib/annotate.js --lint marks.json [--claims claims.json]   (marks.json = ANNOTATE.ledger(); claims = [{x,y,w,h}] or claims.json with figures[].rect)\n  exit 0 ok · 1 findings · 2 usage\n');
      process.exit(argv.length ? 0 : 2);
    }
    if (argv.includes('--selftest')) { const r = selftest(); out(r); process.exit(r.ok ? 0 : 1); }
    if (argv.includes('--shape')) {
      const k = arg('--shape'), rv = String(arg('--rect', '')).split(',').map(Number); if (!SHAPES[k] || rv.length !== 4 || rv.some(isNaN)) { process.stderr.write('usage: --shape <kind> --rect x,y,w,h\n'); process.exit(2); }
      const r = { x: rv[0], y: rv[1], w: rv[2], h: rv[3] }, seed = +arg('--seed', 7), nv = +arg('--variants', 3), o = {}; if (arg('--from')) o.from = String(arg('--from')).split(',').map(Number);
      out({ shape: k, rect: r, seed, variants: Array.from({ length: nv }, (_, v) => SHAPES[k](r, seed + v, o)) }); process.exit(0);
    }
    if (argv.includes('--lint')) {
      const fs = require('fs'), led = JSON.parse(fs.readFileSync(arg('--lint'), 'utf8')); let claims = null;
      if (arg('--claims')) { const cj = JSON.parse(fs.readFileSync(arg('--claims'), 'utf8')); claims = Array.isArray(cj) ? cj : (cj.figures || []).map(f => f.rect).filter(Boolean); }
      const f = lint(led, claims ? { claims } : {}); out({ findings: f, marks: led.length }); process.exit(f.length ? 1 : 0);
    }
    process.stderr.write('usage: --selftest | --shape | --lint (see --help)\n'); process.exit(2);
  }
  if (IS_NODE && typeof module !== 'undefined' && module.exports) {
    module.exports = ANNOTATE;
    if (require.main === module) {
      try { if (!root.gsap) root.gsap = require('gsap').gsap; if (!root.MOTION) require('./motion.js'); } catch (e) { /* pure parts only */ }
      cli(process.argv.slice(2));
    }
  }
})(typeof window !== 'undefined' ? window : globalThis);
