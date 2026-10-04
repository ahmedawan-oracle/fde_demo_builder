/* depth.js — DEPTH: parallax planes and a perspective dolly for the recreated layer (lib/motion.js + GSAP).

   Why. A card whose parts all move together is a flat picture. Give its parts different rates and the eye reads
   distance: a far plane barely moves and is a little soft, the subject moves at the card's own push rate, a near
   occluder sweeps past fast and softer still. Both helpers here are pure functions of the block's local time (they
   read MOTION time through the block's paused timeline, never the camera), so a seek and a step agree to the pixel.
   Blur radii are chosen once at build (filter never animates); transforms carry every motion. Nothing here touches
   the footage lane — planes belong to recreated cards.

   The rules
     planes   rates are relative to the card's own slow push (1.2 %/s in the template): a plane at rate r drifts
              r × travel px over the hold (travel 14 px per unit rate per 6 s hold → rate .2 ≈ 3 px, rate 1 ≈ 14 px,
              rate 6 ≈ 84 px) and grows 1 + min(r, 2) × 0.004 per second of hold (the near occluder grows 4.8 %, not 14 %); blur in px is fixed per plane (6 far, 22
              near; the subject plane at rate 1 is never blurred). Exactly one near occluder (the highest rate, or
              o.occluder) crosses the headline band once, centred a third into the hold (window 0.28 of the hold,
              sine.inOut), then stays parked off the far side — the one event a hold needs so nothing idles.
     dolly    perspective P = 1200 px on the host, children at translateZ(z_i); the rig moves along z so the z = 0
              plane scales from `from` (1) to `to` (1.08) over dur 4 s (sine.out): z_rig = P (1 − 1/s). A child at
              z_i appears at P / (P − z_rig − z_i): for z = +90 the near child grows 1.175×, for z = −120 the far one
              0.909 → 0.975 — differential growth is what reads as camera travel rather than a zoom.

   Scene wiring (inside a MOTION.block build; planes mount their own block when given a host, or add to a tl):
     <script src="../node_modules/gsap/dist/gsap.min.js"></script><script src="lib/motion.js"></script>
     <script src="lib/depth.js"></script>
     DEPTH.planes($('#kpiCard'), [ { el: $('#far'), rate: 0.2, blur: 6 }, { el: $('#kpiInner'), rate: 1 },
                                   { el: $('#near'), rate: 6, blur: 22 } ], { start: P.kpi, end: P.close, headline: $('#kpiTitle') });
     MOTION.block('kpi', (tl, el, api) => { DEPTH.dolly(tl, el, 0, { to: 1.08, dur: api.exitAt }); }, { el: $('#kpiCard'), start: P.kpi, end: P.close });

   Node (no DOM): node lib/depth.js --help | --selftest | --dolly [--from 1 --to 1.08 --p 1200 --z -120,0,90]
                  | --planes [--rates .2,1,6 --hold 6 --fps 30]   JSON in / JSON out; exit 0 ok, 1 findings, 2 usage. */
(function (root) {
  'use strict';
  const IS_NODE = typeof window === 'undefined';
  const clamp = (x, a, b) => Math.max(a, Math.min(b, x));
  const num = (v, d) => (v === undefined || v === null || Number.isNaN(v) ? d : v);
  const motion = () => { const m = root.MOTION; if (!m) throw new Error('depth.js: load gsap and lib/motion.js before lib/depth.js'); return m; };

  const tokens = {
    planes: { travel: 14, growPerSec: 0.004, growRateCap: 2, hold: 6, blurFar: 6, blurNear: 22, cross: { at: 1 / 3, window: 0.28, overshoot: 1.25 } },
    dolly: { perspective: 1200, from: 1, to: 1.08, dur: 4, ease: 'sine.out', zs: [-120, 0, 90], maxTo: 1.2 }
  };
  const sineIO = u => 0.5 - 0.5 * Math.cos(Math.PI * clamp(u, 0, 1));
  const sineOut = u => Math.sin(clamp(u, 0, 1) * Math.PI / 2);

  /* ------------------------------------------------------------------ pure geometry ------------------------------ */
  /* a plane's drift (px) and scale at fraction u of the hold: pure, so the scene and the node CLI share one law */
  function planeAt(rate, u, hold, o) {
    o = o || {}; const T = tokens.planes, h = num(hold, T.hold);
    return { dx: -rate * num(o.travel, T.travel) * (h / T.hold) * clamp(u, 0, 1), scale: 1 + Math.min(rate, T.growRateCap) * num(o.growPerSec, T.growPerSec) * h * clamp(u, 0, 1) };
  }
  /* the occluder's crossing: x from −W·overshoot to +W·overshoot over a window centred at a third of the hold */
  function crossAt(u, W, o) {
    o = o || {}; const C = tokens.planes.cross, c = num(o.at, C.at), w = num(o.window, C.window), ov = num(o.overshoot, C.overshoot);
    const v = sineIO((u - (c - w / 2)) / w);
    return -W * ov + 2 * W * ov * v;
  }
  /* dolly: rig z for a z=0-plane scale s, and the apparent scale of a child at z given the rig position */
  const rigZ = (s, P) => P * (1 - 1 / s);
  const childScale = (z, zrig, P) => P / (P - zrig - z);
  function dollyAt(u, o) {
    o = o || {}; const D = tokens.dolly, P = num(o.perspective, D.perspective), from = num(o.from, D.from), to = Math.min(num(o.to, D.to), D.maxTo);
    const s = from + (to - from) * sineOut(u), zr = rigZ(s, P), zs = o.zs || D.zs;
    return { s, zRig: zr, children: zs.map(z => ({ z, scale: childScale(z, zr, P) })) };
  }

  /* ------------------------------------------------------------------ plugin ------------------------------------- */
  let pluginReady = false;
  function ensurePlugin() {
    if (pluginReady) return;
    motion().gsap.registerPlugin({ name: 'depthPaint', rawVars: 1, headless: true,
      init(target, fn) { this.fn = typeof fn === 'function' ? fn : () => {}; this.fn(0); }, render(ratio, data) { data.fn(clamp(ratio, 0, 1)); } });
    pluginReady = true;
  }

  /* ------------------------------------------------------------------ planes ------------------------------------- */
  /* DEPTH.planes(host, planes, o) → { block | tl, hold, occluder }
     planes  [{ el, rate, blur }]: rate relative to the card's push; blur px fixed at build (omit = crisp)
     o       start/end (film s) → mounts its own MOTION.block 'depth:<host.id>'; or o.tl + o.at to add to a block's
             timeline (hold = o.hold || end − start || 6); o.headline (the band the occluder crosses; default host);
             o.occluder (el; default the highest rate); o.cross {at, window, overshoot}; o.travel; o.growPerSec
     planes are absolutely positioned by the scene: position them with explicit insets (an absolute child ignores its
     parent's padding), and when a dolly also runs, put the plane transform on an INNER element (the dolly owns the
     plane's own transform for translateZ) */
  function planes(host, list, o) {
    o = o || {}; ensurePlugin(); const M = motion(), T = tokens.planes;
    const hold = num(o.hold, (Number.isFinite(o.end) && Number.isFinite(o.start)) ? o.end - o.start : T.hold);
    const W = (o.headline || host).offsetWidth || host.offsetWidth || 1280;
    const occ = o.occluder || list.reduce((a, b) => (a && a.rate >= b.rate ? a : b), null);
    list.forEach(p => {
      if (p.blur) p.el.style.filter = 'blur(' + p.blur + 'px)';                      // fixed per plane, chosen once
      // never will-change: a promoted plane rasters at a scale the compositor picks from how its transform changed, and that
      // differs between a cold seek and a stepped run (measured on a frosted panel under load: 46/76 frames differed run to run)
      p.el.style.transformOrigin = p.el.style.transformOrigin || '50% 50%';
      p.el.dataset.depthRate = String(p.rate);
    });
    const paint = u => {
      list.forEach(p => {
        const a = planeAt(p.rate, u, hold, o);
        let x = a.dx;
        if (p === occ) x += crossAt(u, W, o.cross);
        p.el.style.transform = 'translate(' + x.toFixed(2) + 'px,0px) scale(' + a.scale.toFixed(4) + ')';
      });
    };
    paint(0);                                                                        // frame-0 state at build (GSAP initialises lazily)
    function build(tl, at) { tl.to({}, { duration: hold, ease: 'none', depthPaint: paint }, at); }
    if (o.tl) { build(o.tl, num(o.at, 0)); return { tl: o.tl, hold, occluder: occ ? occ.el : null }; }
    const block = M.block(o.id || ('depth:' + (host.id || 'host')), tl => build(tl, 0), { el: null, start: num(o.start, 0), end: num(o.end, Infinity), hide: false });
    return { block, hold, occluder: occ ? occ.el : null };
  }

  /* ------------------------------------------------------------------ dolly -------------------------------------- */
  /* DEPTH.dolly(tl, host, at, o) → { end, zFrom, zTo, rig }
     host gets perspective P (1200) and a rig (o.rig, or host's first element child with class .rig, or host itself
     when it has no inner rig) with transform-style preserve-3d; the rig's children receive translateZ from o.zs
     (cycled, default [−120, 0, 90]) or their data-z attribute; the rig travels from z(from) to z(to) over dur (4 s,
     sine.out). `to` is capped at 1.2 (beyond that the near plane leaves the card). The z = 0 plane really grows by `to`:
     inside a fixed frame (a glass panel) leave (to − 1) / 2 of the width as inner margin or keep `to` ≤ 1.04;
     1.08 is for cards that fill the stage, where growth past the edges is the point. */
  function dolly(tl, host, at, o) {
    o = o || {}; motion(); const D = tokens.dolly, P = num(o.perspective, D.perspective);
    const from = num(o.from, D.from), to = Math.min(num(o.to, D.to), D.maxTo), dur = num(o.dur, D.dur);
    const rig = o.rig || host.querySelector(':scope > .rig') || host;
    Object.assign(host.style, { perspective: P + 'px', perspectiveOrigin: o.origin || '50% 50%' });
    rig.style.transformStyle = 'preserve-3d';
    const zs = o.zs || D.zs;
    // static depth per child, written once as a style (no tween: GSAP parses it when the rig tween first renders)
    Array.from(rig.children).forEach((c, i) => { const z = c.dataset.z !== undefined ? +c.dataset.z : zs[i % zs.length]; c.style.transform = 'translate3d(0px,0px,' + z + 'px)'; c.dataset.depthZ = String(z); });
    const z0 = rigZ(from, P), z1 = rigZ(to, P);
    rig.style.transform = 'translate3d(0px,0px,' + z0.toFixed(3) + 'px)';            // the start pose is on the DOM before any render
    tl.fromTo(rig, { z: z0 }, { z: z1, duration: dur, ease: o.ease || D.ease, immediateRender: false }, at);
    return { end: at + dur, zFrom: z0, zTo: z1, rig };
  }

  const DEPTH = { tokens, planes, dolly, geo: { planeAt, crossAt, dollyAt, rigZ, childScale } };
  root.DEPTH = DEPTH;

  /* ------------------------------------------------------------------ node CLI ----------------------------------- */
  function selftest() {
    const fails = []; const eq = (a, b, tol, w) => { if (!(Math.abs(a - b) <= (tol || 1e-9))) fails.push(w + ': ' + a + ' vs ' + b); };
    // planes: drift ∝ rate, far plane ≈ 3 px, near ≈ 84 px over a 6 s hold; scale law
    eq(planeAt(0.2, 1, 6).dx, -2.8, 1e-9, 'far drift'); eq(planeAt(6, 1, 6).dx, -84, 1e-9, 'near drift'); eq(planeAt(1, 0, 6).dx, 0, 0, 'no drift at u=0');
    eq(planeAt(1, 1, 6).scale, 1.024, 1e-9, 'subject grows 2.4 % over 6 s');
    // occluder: off-left before the window, off-right after, centred (x=0) at a third of the hold
    eq(crossAt(0, 1000), -1250, 1e-9, 'occluder parked left'); eq(crossAt(1, 1000), 1250, 1e-9, 'occluder parked right'); eq(crossAt(1 / 3, 1000), 0, 1e-6, 'occluder crosses centre at 1/3');
    if (crossAt(1 / 3 - 0.14 - 0.01, 1000) > -1250 + 1e-6) fails.push('occluder moved before its window');
    // dolly: z=0 plane 1 → 1.08; near child 1.175 at the end; far child 0.909 → 0.975
    const d0 = dollyAt(0), d1 = dollyAt(1);
    eq(d0.s, 1, 0, 'dolly from'); eq(d1.s, 1.08, 1e-9, 'dolly to'); eq(d1.zRig, 1200 * (1 - 1 / 1.08), 1e-9, 'rig z');
    eq(d1.children[2].scale, 1200 / (1200 - d1.zRig - 90), 1e-9, 'near child scale'); eq(d0.children[0].scale, 1200 / 1320, 1e-9, 'far child start');
    if (!(d1.children[2].scale > d1.children[1].scale && d1.children[1].scale > d1.children[0].scale)) fails.push('dolly parallax order (near > subject > far) broken');
    eq(dollyAt(1, { to: 2 }).s, 1.2, 1e-9, 'to capped at 1.2');
    // a timeline-driven plane paint is seek-order independent (gsap present)
    if (root.MOTION) {
      ensurePlugin(); const tl = root.MOTION.gsap.timeline({ paused: true }); const seen = {};
      tl.to({}, { duration: 6, ease: 'none', depthPaint: u => { seen.x = planeAt(6, u, 6).dx + crossAt(u, 1000); } }, 0);
      tl.totalTime(2.1, true); const a = seen.x; tl.totalTime(5, true); tl.totalTime(0.2, true); tl.totalTime(2.1, true);
      if (a === undefined || a !== seen.x) fails.push('seek order changed the plane transform: ' + a + ' vs ' + seen.x);
    }
    return { ok: !fails.length, fails, gsap: !!root.MOTION, samples: { far6s: planeAt(0.2, 1, 6), near6s: planeAt(6, 1, 6), dollyEnd: dollyAt(1) } };
  }
  function cli(argv) {
    const arg = (k, d) => { const i = argv.indexOf(k); return i >= 0 && argv[i + 1] !== undefined ? argv[i + 1] : d; };
    const out = s => process.stdout.write(JSON.stringify(s, null, 2) + '\n');
    if (argv.includes('--help') || argv.includes('-h') || !argv.length) {
      process.stdout.write('depth.js — DEPTH geometry (pure) and selftest\n  node lib/depth.js --selftest\n  node lib/depth.js --dolly [--from 1] [--to 1.08] [--p 1200] [--z -120,0,90] [--fps 30] [--dur 4]\n  node lib/depth.js --planes [--rates .2,1,6] [--hold 6] [--fps 30] [--w 1000]\n  exit 0 ok · 1 findings · 2 usage\n');
      process.exit(argv.length ? 0 : 2);
    }
    if (argv.includes('--selftest')) { const r = selftest(); out(r); process.exit(r.ok ? 0 : 1); }
    const fps = +arg('--fps', 30);
    if (argv.includes('--dolly')) {
      const o = { from: +arg('--from', 1), to: +arg('--to', 1.08), perspective: +arg('--p', 1200), zs: String(arg('--z', '-120,0,90')).split(',').map(Number) }, dur = +arg('--dur', 4);
      const samples = []; for (let i = 0; i <= Math.round(dur * fps); i++) samples.push(Object.assign({ t: +(i / fps).toFixed(4) }, dollyAt(i / fps / dur, o)));
      out({ dolly: o, dur, fps, samples }); process.exit(0);
    }
    if (argv.includes('--planes')) {
      const rates = String(arg('--rates', '.2,1,6')).split(',').map(Number), hold = +arg('--hold', 6), W = +arg('--w', 1000), occ = Math.max(...rates);
      const samples = []; for (let i = 0; i <= Math.round(hold * fps); i++) { const u = i / fps / hold; samples.push({ t: +(i / fps).toFixed(4), planes: rates.map(r => { const a = planeAt(r, u, hold); return { rate: r, dx: +(a.dx + (r === occ ? crossAt(u, W) : 0)).toFixed(3), scale: +a.scale.toFixed(5) }; }) }); }
      out({ rates, hold, fps, occluderRate: occ, samples }); process.exit(0);
    }
    process.stderr.write('usage: --selftest | --dolly | --planes (see --help)\n'); process.exit(2);
  }
  if (IS_NODE && typeof module !== 'undefined' && module.exports) {
    module.exports = DEPTH;
    if (require.main === module) {
      try { if (!root.gsap) root.gsap = require('gsap').gsap; if (!root.MOTION) require('./motion.js'); } catch (e) { /* pure parts only */ }
      cli(process.argv.slice(2));
    }
  }
})(typeof window !== 'undefined' ? window : globalThis);
