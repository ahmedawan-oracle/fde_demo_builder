/* cursor.js — CURSOR: a redrawn vector pointer that follows the presenter's hand, on the film clock.

   The footage lane shows median stills, so the real pointer is gone. This layer puts a clean one back: our own
   arrow (12 x 19 px at scale 1, drawn 1.5-2x, soft shadow) riding a Catmull-Rom path through the recorded pointer
   samples, fading after 1.2 s of stillness, with a stroke-only ring on every click (28 -> 64 px, 0.32 s, power2.out).

   Where it lives: a stage sibling layer INSIDE #camera (next to #clipWrap, never inside the footage lane), so the
   camera's push/pan carries the cursor with the pixels it points at, and the grade gate still proves the footage
   untouched. Keystroke pills are a separate screen-space layer (lib/hud.js).

   Usage:
     <script src="../node_modules/gsap/dist/gsap.min.js"></script><script src="lib/motion.js"></script><script src="lib/cursor.js"></script>
     const cur = CURSOR.mount($('#camera'), window.EVENTS, { scale: 1.75, color: '#E9F3F9', outline: '#082A34',
                               source: [1920, 1080], spans: [{ t0: 8.4, t1: 20.0, src: 12.0 }] });
     function frame(t) { …; MOTION.seek(t); … }        // that is all: CURSOR hooks MOTION.seek (see below)

   Inputs
     events  the parsed lines of events.jsonl (record_events.py / cursor_track.py) — objects {t, x, y, type, …}; a
             leading {type:'meta', source:[W,H]} line is honoured for `source`. Coordinates are recording pixels.
     spans   film-time windows that show the recording: {t0, t1, src} = film t0..t1 shows recording from src at
             rate 1. Default: one identity span (film time == recording time). Outside every span the cursor is hidden.
     crop    [x, y, w, h] of the recording that fills the 1280x720 stage (a cropped clip); default the whole frame.
     scale   1.75 (1.5-2x reads as 'produced' at 1080p; 1 = the OS size)   color/outline  fill and outline colours
     idle    1.2 s without movement -> fade out over 0.3 s; a click or movement brings it back in 0.12 s
     smooth  n samples averaged on each side of a sample before the spline (0 for 60 Hz telemetry, 1-2 for a 15 fps tracker)

   Determinism: the arrow pose is a pure function of t (binary search + Hermite segment); the rings are GSAP tweens in a
   MOTION block, so they are seek-safe; no wall clock, no randomness, no CSS animation. All DOM writes are idempotent.

   Clock hook: MOTION.seek(t) drives GSAP; CURSOR also needs t for the pure draw, so mount() registers draw(t) through
   MOTION.onSeek(fn) (lib/motion.js runs every hook after the timelines are set; remove() unsubscribes). CURSOR.seek(t)
   exists for scenes without MOTION. */
(function (root) {
  'use strict';
  const clamp = (x, a, b) => Math.max(a, Math.min(b, x));
  const rmp = (t, a, b) => clamp((t - a) / (b - a), 0, 1);
  const P2O = x => 1 - (1 - x) * (1 - x);
  const SVGNS = 'http://www.w3.org/2000/svg';
  // our arrow, 12 x 19 at scale 1: tip at (0,0), straight left edge, notched tail
  const ARROW = 'M0 0 L0 16 L4 12.6 L6.7 18.6 L9 17.7 L6.3 11.8 L11.4 11.8 Z';
  const DEFAULTS = { scale: 1.75, color: '#E9F3F9', outline: '#082A34', shadow: true, source: [1920, 1080], stage: [1280, 720], crop: null,
    idle: 1.2, fade: 0.3, wake: 0.12, ring: { d0: 28, d1: 64, dur: 0.32 }, press: { amount: 0.1, dur: 0.16 }, smooth: 0, id: 'cursor', moveEps: 2 };
  const handles = [];

  /* ---------- clock hook: MOTION.onSeek(fn) → unsubscribe; the lib export is never reassigned (same hook as hud.js) ---------- */
  function onClock(fn) {
    const M = root.MOTION;
    if (!M) return null;
    if (typeof M.onSeek !== 'function') throw new Error('cursor.js: lib/motion.js is older than this lib (MOTION.onSeek missing) — update lib/motion.js');
    return M.onSeek(fn);
  }

  /* ---------- samples: recording-time path points + activity times ---------- */
  function samples(events, o) {
    let src = o.source;
    const pts = [], clicks = [];
    for (const e of events) {
      if (e.type === 'meta') { if (Array.isArray(e.source) && !o.sourceGiven) src = e.source; continue; }
      if (typeof e.x !== 'number' || typeof e.y !== 'number') continue;
      if (e.type === 'move' || e.type === 'down' || e.type === 'up') {
        if (!pts.length || e.t > pts[pts.length - 1].t + 1e-6) pts.push({ t: e.t, x: e.x, y: e.y });
        else if (e.type !== 'move') { const p = pts[pts.length - 1]; p.x = e.x; p.y = e.y; }
      }
      if (e.type === 'down') clicks.push({ t: e.t, x: e.x, y: e.y });
    }
    if (o.smooth > 0) {
      const n = o.smooth, sm = pts.map((p, i) => { let sx = 0, sy = 0, c = 0; for (let k = -n; k <= n; k++) { const q = pts[clamp(i + k, 0, pts.length - 1)]; sx += q.x; sy += q.y; c++; } return { t: p.t, x: sx / c, y: sy / c }; });
      pts.splice(0, pts.length, ...sm);
    }
    // activity: a sample that moved >= moveEps px since the previous one, or a click
    const act = [];
    for (let i = 1; i < pts.length; i++) if (Math.hypot(pts[i].x - pts[i - 1].x, pts[i].y - pts[i - 1].y) >= o.moveEps) act.push(pts[i].t);
    for (const c of clicks) act.push(c.t);
    act.sort((a, b) => a - b);
    return { pts, clicks, act, source: src };
  }
  /* index of the last element <= t in a sorted array of numbers or of {t} */
  function lastLE(arr, t, key) {
    let lo = 0, hi = arr.length - 1, ans = -1;
    while (lo <= hi) { const mid = (lo + hi) >> 1; const v = key ? arr[mid][key] : arr[mid]; if (v <= t) { ans = mid; lo = mid + 1; } else hi = mid - 1; }
    return ans;
  }
  /* position at recording time t: cubic Hermite with Catmull-Rom tangents scaled for non-uniform sample times */
  function posAt(pts, t) {
    if (!pts.length) return null;
    if (t <= pts[0].t) return { x: pts[0].x, y: pts[0].y };
    const n = pts.length;
    if (t >= pts[n - 1].t) return { x: pts[n - 1].x, y: pts[n - 1].y };
    const i = lastLE(pts, t, 't');
    const p0 = pts[Math.max(0, i - 1)], p1 = pts[i], p2 = pts[Math.min(n - 1, i + 1)], p3 = pts[Math.min(n - 1, i + 2)];
    const dt = p2.t - p1.t; if (dt <= 1e-9) return { x: p1.x, y: p1.y };
    const u = (t - p1.t) / dt, u2 = u * u, u3 = u2 * u;
    // tangents: finite differences over time, scaled to the segment length (standard non-uniform Catmull-Rom)
    const m1x = (p2.x - p0.x) / Math.max(1e-9, p2.t - p0.t) * dt, m1y = (p2.y - p0.y) / Math.max(1e-9, p2.t - p0.t) * dt;
    const m2x = (p3.x - p1.x) / Math.max(1e-9, p3.t - p1.t) * dt, m2y = (p3.y - p1.y) / Math.max(1e-9, p3.t - p1.t) * dt;
    const h00 = 2 * u3 - 3 * u2 + 1, h10 = u3 - 2 * u2 + u, h01 = -2 * u3 + 3 * u2, h11 = u3 - u2;
    return { x: h00 * p1.x + h10 * m1x + h01 * p2.x + h11 * m2x, y: h00 * p1.y + h10 * m1y + h01 * p2.y + h11 * m2y };
  }

  /* ---------- mount ---------- */
  function mount(host, events, opts) {
    const o = Object.assign({}, DEFAULTS, opts || {});
    o.sourceGiven = !!(opts && opts.source);
    o.ring = Object.assign({}, DEFAULTS.ring, (opts && opts.ring) || {});
    o.press = Object.assign({}, DEFAULTS.press, (opts && opts.press) || {});
    const S = samples(events || [], o);
    const src = S.source, crop = o.crop || [0, 0, src[0], src[1]];
    const kx = o.stage[0] / crop[2], ky = o.stage[1] / crop[3];
    const toStage = p => ({ x: (p.x - crop[0]) * kx, y: (p.y - crop[1]) * ky });
    const spans = (o.spans && o.spans.length) ? o.spans.slice().sort((a, b) => a.t0 - b.t0) : [{ t0: -Infinity, t1: Infinity, src: -Infinity }];
    const recOf = tf => { for (const s of spans) if (tf >= s.t0 && tf < s.t1) return Number.isFinite(s.src) ? s.src + (tf - s.t0) : tf; return null; };
    const filmOf = tr => { for (const s of spans) { const s0 = Number.isFinite(s.src) ? s.src : -Infinity; const len = s.t1 - s.t0; if (!Number.isFinite(s0)) return tr; if (tr >= s0 && tr < s0 + len) return s.t0 + (tr - s0); } return null; };

    // layer: an SVG in stage coordinates, a sibling of the footage lane inside #camera
    const layer = document.createElementNS(SVGNS, 'svg');
    layer.setAttribute('id', o.id); layer.setAttribute('viewBox', '0 0 ' + o.stage[0] + ' ' + o.stage[1]);
    layer.setAttribute('width', o.stage[0]); layer.setAttribute('height', o.stage[1]);
    layer.style.cssText = 'position:absolute;left:0;top:0;pointer-events:none;overflow:visible;z-index:5';
    layer.setAttribute('data-qa-allow-overlap', '');
    const defs = document.createElementNS(SVGNS, 'defs'), filt = document.createElementNS(SVGNS, 'filter'), ds = document.createElementNS(SVGNS, 'feDropShadow');
    for (const [k, v] of [['id', o.id + 'Shadow'], ['x', '-60%'], ['y', '-40%'], ['width', '240%'], ['height', '220%']]) filt.setAttribute(k, v);
    for (const [k, v] of [['dx', '0.6'], ['dy', '1.4'], ['stdDeviation', '1.1'], ['flood-color', '#000'], ['flood-opacity', '0.38']]) ds.setAttribute(k, v);
    filt.appendChild(ds); defs.appendChild(filt); layer.appendChild(defs);
    const rings = document.createElementNS(SVGNS, 'g'); rings.setAttribute('class', 'cursor-rings'); layer.appendChild(rings);
    const arrowG = document.createElementNS(SVGNS, 'g'); arrowG.setAttribute('class', 'cursor-arrow'); arrowG.style.opacity = '0';
    const path = document.createElementNS(SVGNS, 'path');
    path.setAttribute('d', ARROW); path.setAttribute('fill', o.color); path.setAttribute('stroke', o.outline);
    path.setAttribute('stroke-width', '1.1'); path.setAttribute('stroke-linejoin', 'round'); path.setAttribute('vector-effect', 'non-scaling-stroke');
    if (o.shadow) path.setAttribute('filter', 'url(#' + o.id + 'Shadow)');
    arrowG.appendChild(path); layer.appendChild(arrowG);
    host.appendChild(layer);

    // click rings: one circle per click, animated by GSAP inside a MOTION block (seek-safe); invisible before and after
    const ringEls = [];
    for (const c of S.clicks) {
      const tf = filmOf(c.t); if (tf === null) continue;
      const p = toStage(c);
      const el = document.createElementNS(SVGNS, 'circle');
      el.setAttribute('cx', p.x.toFixed(2)); el.setAttribute('cy', p.y.toFixed(2)); el.setAttribute('r', (o.ring.d0 / 2).toFixed(2));
      el.setAttribute('fill', 'none'); el.setAttribute('stroke', o.color); el.setAttribute('stroke-width', '2.5'); el.style.opacity = '0';
      rings.appendChild(el); ringEls.push({ el, tf });
    }
    if (root.MOTION && ringEls.length) {
      root.MOTION.block(o.id + ':rings', function (tl) {
        for (const r of ringEls) {
          tl.fromTo(r.el, { opacity: 0, attr: { r: o.ring.d0 / 2, 'stroke-width': 2.5 } },
            { keyframes: [{ opacity: 0.9, duration: 0.02, ease: 'none' },
                          { opacity: 0, attr: { r: o.ring.d1 / 2, 'stroke-width': 1 }, duration: o.ring.dur - 0.02, ease: 'power2.out' }],
              immediateRender: false, lazy: false }, Math.max(0, r.tf));
        }
      }, { el: rings, start: 0, end: Infinity, hide: false });
    }

    /* pure pose at film time t -> writes the arrow (idempotent) */
    let lastKey = null;
    function draw(tf) {
      const tr = recOf(tf);
      let op = 0, x = 0, y = 0, sc = o.scale;
      if (tr !== null && S.pts.length && tr >= S.pts[0].t - 1e-6) {
        const p = toStage(posAt(S.pts, tr)); x = p.x; y = p.y;
        const i = lastLE(S.act, tr), lastAct = i >= 0 ? S.act[i] : S.pts[0].t;
        op = 1 - rmp(tr - lastAct, o.idle, o.idle + o.fade);                       // fade after `idle` seconds of stillness
        if (i < 0) op = Math.min(op, P2O(rmp(tr - S.pts[0].t, 0, o.wake)));         // first appearance eases in
        else { const prev = i > 0 ? S.act[i - 1] : -Infinity; if (lastAct - prev > o.idle + o.fade) op = Math.min(op, P2O(rmp(tr - lastAct, 0, o.wake))); }   // waking from a full fade eases in
        // press: a small squeeze on every click (pure, from the click times)
        const ci = lastLE(S.clicks, tr, 't');
        if (ci >= 0) { const u = rmp(tr - S.clicks[ci].t, 0, o.press.dur); if (u < 1) sc *= 1 - o.press.amount * Math.sin(Math.PI * u); }
      }
      const key = op.toFixed(3) + '|' + x.toFixed(2) + '|' + y.toFixed(2) + '|' + sc.toFixed(4);
      if (key === lastKey) return;
      lastKey = key;
      arrowG.style.opacity = op.toFixed(3);
      arrowG.setAttribute('transform', 'translate(' + x.toFixed(2) + ' ' + y.toFixed(2) + ') scale(' + sc.toFixed(4) + ')');
    }
    let off = null;
    const h = { id: o.id, layer, draw, seek: draw, samples: S, opts: o, remove() { layer.remove(); const i = handles.indexOf(h); if (i >= 0) handles.splice(i, 1); if (off) off(); if (root.MOTION) root.MOTION.remove(o.id + ':rings'); } };
    handles.push(h);
    off = onClock(draw);
    draw(0);
    return h;
  }
  function seek(t) { for (const h of handles) h.draw(t); }

  root.CURSOR = { mount, seek, posAt, samples, ARROW, DEFAULTS, handles };
})(typeof window !== 'undefined' ? window : globalThis);
