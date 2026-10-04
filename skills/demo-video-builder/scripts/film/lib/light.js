/* light.js — LIGHT: soft light on the recreated layer (built on lib/motion.js + GSAP). Never on product pixels.

   Why a separate light layer. A card drawn in flat colour reads as a slide; the same card with a dim glow behind it,
   a 1 px highlight along its top edge and one light band crossing it on the landing word reads as an object in a
   room. All four helpers put light AROUND an element, in sibling or child layers the scene owns, so the footage lane
   and every glyph stay untouched: no filter ever animates on text (a blur radius is chosen once at build and the
   layer's opacity / transform carry the motion — animating blur() on text re-rasterises glyphs every frame and reads
   as a focus hunt).

   The measured numbers (defaults; every helper takes overrides)
     bloom    radial glow behind a card/figure: opacity 0 → peak .30 (ceiling .45, never crossed), scale .80 → 1 over
              grow 1.0 s (clamped 0.6–1.4), power3.out; blur fixed at 28 px; a slow breathe follows the landing with
              amplitude 0.05/sqrt(N) (N = blooms mounted in the scene: five lamps breathe at under half the swing of
              one; N is frozen on the first seek, so mount every bloom before frame 0), period 2.4 s, dying over the
              last 20 % before `until`
     leak     three-layer warm light leak (amber / red / gold ellipses, fixed blur 30 px, screen blend) drifting on
              seeded offsets; envelope 0 → .90 (35 %) → .46 (70 %) → 0; dur ≤ 0.5 s (clamped); allowed over footage
              ONLY inside a declared seam window — the helper throws if [at, at+dur] leaves `window`
     sweep    one 105° light band across a card, once, on the landing word: 0.9 s power2.inOut, band 55 % of the card
              wide, peak opacity .32 at mid-travel
     rim      a static 1 px top-edge highlight (white .55 at centre fading to the corners)

   Scene wiring (everything inside a MOTION.block build; `at` and `until` are block-local seconds):
     <script src="../node_modules/gsap/dist/gsap.min.js"></script><script src="lib/motion.js"></script>
     <script src="lib/light.js"></script>
     MOTION.block('kpi', (tl, el, api) => {
       LIGHT.rim(el.querySelector('.card'));
       LIGHT.bloom(tl, el.querySelector('.card'), 0.2, { until: api.exitAt, color: LIGHT.tokens.gold });
       LIGHT.sweep(tl, el.querySelector('.card'), wt('kpi', 'answer') - P.kpi);
     }, { el: $('#kpiCard'), start: P.kpi, end: P.close, exit: 0.4 });
     // a leak over footage, declared: LIGHT.leak(tl, $('#stage'), 0.0, { window: [0, 0.5], host: $('#stage') })

   Node (no DOM): node lib/light.js --help | --selftest | --envelope <bloom|leak|sweep> [--dur s] [--fps 30] [--n 1]
   JSON in / JSON out; exit 0 ok, 1 findings, 2 usage. */
(function (root) {
  'use strict';
  const IS_NODE = typeof window === 'undefined';
  const clamp = (x, a, b) => Math.max(a, Math.min(b, x));
  const num = (v, d) => (v === undefined || v === null || Number.isNaN(v) ? d : v);
  const motion = () => { const m = root.MOTION; if (!m) throw new Error('light.js: load gsap and lib/motion.js before lib/light.js'); return m; };

  /* ------------------------------------------------------------------ tokens ------------------------------------- */
  const tokens = {
    navy: '#082A34', navy2: '#204A56', ink: '#E9F3F9', cream: '#ECDEC3', coral: '#E56B5E', mint: '#81A9AB', gold: '#E8C874',
    amber: '#E8A24A',
    bloom: { peak: 0.30, ceiling: 0.45, grow: 1.0, growMin: 0.6, growMax: 1.4, scale0: 0.80, blur: 28, spread: 0.55,
             breatheAmp: 0.05, breathePeriod: 2.4, breatheFade: 0.2, ease: 'power3.out' },
    leak: { durMax: 0.5, blur: 30, env: [0, 0.90, 0.46, 0], at: [0, 0.35, 0.70, 1.0], drift: 0.08, z: 30 },
    sweep: { dur: 0.9, angle: 105, band: 0.55, peak: 0.32, ease: 'power2.inOut' },
    rim: { alpha: 0.55, inset: 10 }
  };

  /* hex (#RRGGBB) → 'r,g,b' for rgba() strings */
  function rgb(hex) {
    const h = String(hex).replace('#', '');
    const v = h.length === 3 ? h.split('').map(c => parseInt(c + c, 16)) : [0, 2, 4].map(i => parseInt(h.slice(i, i + 2), 16));
    return v.join(',');
  }
  const easeFn = {                                             // the eases the pure envelopes use (same curves GSAP names)
    'power3.out': u => 1 - Math.pow(1 - u, 3), 'power2.out': u => 1 - Math.pow(1 - u, 2), 'power2.in': u => u * u,
    'sine.inOut': u => 0.5 - 0.5 * Math.cos(Math.PI * u), 'power2.inOut': u => (u < 0.5 ? 2 * u * u : 1 - Math.pow(-2 * u + 2, 2) / 2),
    none: u => u
  };

  /* ------------------------------------------------------------------ pure envelopes ----------------------------- */
  /* the breathe term after the landing: amp/sqrt(N) * sin(2π u T/period), fading over the last `fade` of the hold */
  function breathe(u, hold, N, o) {
    o = o || {}; const B = tokens.bloom;
    const amp = num(o.amp, B.breatheAmp) / Math.sqrt(Math.max(1, N || 1));
    const fade = clamp((1 - u) / num(o.fade, B.breatheFade), 0, 1);
    return amp * Math.sin(2 * Math.PI * u * hold / num(o.period, B.breathePeriod)) * fade;
  }
  /* bloom opacity as a pure function of local time s (s=0 at `at`): grow, then breathe until `hold` ends */
  function bloomEnv(s, o) {
    o = o || {}; const B = tokens.bloom;
    const grow = clamp(num(o.grow, B.grow), B.growMin, B.growMax), peak = Math.min(num(o.peak, B.peak), num(o.ceiling, B.ceiling));
    const hold = num(o.hold, 6), N = num(o.n, 1);
    if (s <= 0) return 0;
    if (s < grow) return peak * easeFn['power3.out'](s / grow);
    const u = clamp((s - grow) / Math.max(1e-6, hold - grow), 0, 1);
    return clamp(peak + breathe(u, hold - grow, N, o), 0, num(o.ceiling, B.ceiling));
  }
  /* leak envelope: piecewise through [0 → .90 → .46 → 0] at [0, 35 %, 70 %, 100 %] of dur (power2.out / sine.inOut / power2.in) */
  function leakEnv(s, dur) {
    const L = tokens.leak, d = Math.min(num(dur, L.durMax), L.durMax);
    if (s <= 0 || s >= d) return 0;
    const u = s / d, eases = ['power2.out', 'sine.inOut', 'power2.in'];
    for (let i = 1; i < L.at.length; i++) {
      if (u <= L.at[i]) { const v = (u - L.at[i - 1]) / (L.at[i] - L.at[i - 1]); return L.env[i - 1] + (L.env[i] - L.env[i - 1]) * easeFn[eases[i - 1]](v); }
    }
    return 0;
  }
  /* sweep: band position −1 → +1 across the card (power2.inOut) and its opacity (peak at mid-travel) */
  function sweepEnv(s, dur) {
    const S = tokens.sweep, d = num(dur, S.dur);
    if (s < 0 || s > d) return { x: s < 0 ? -1 : 1, opacity: 0 };
    const u = easeFn[S.ease](s / d);
    return { x: -1 + 2 * u, opacity: S.peak * Math.sin(Math.PI * clamp(s / d, 0, 1)) };
  }

  /* ------------------------------------------------------------------ the paint plugin --------------------------- */
  let pluginReady = false;
  function ensurePlugin() {
    if (pluginReady) return; const G = motion().gsap;
    G.registerPlugin({
      name: 'lightPaint', rawVars: 1, headless: true,            // headless: the node selftest has no window
      init(target, fn) { this.fn = typeof fn === 'function' ? fn : () => {}; this.fn(0); },
      render(ratio, data) { data.fn(clamp(ratio, 0, 1)); }
    });
    pluginReady = true;
    if (motion().onSeek) motion().onSeek(freezeCount);         // runs after the timelines of the first seek have painted
  }
  /* N (the bloom count the breathe amplitude divides by, 0.05/sqrt(N)) is frozen on the FIRST seek: a bloom mounted after that
     cannot change the swing of the lamps already on screen, so a cold seek and a stepped run read the same N for every frame.
     Hence the rule: every bloom a scene wants counted mounts before the first frame (every MOTION.block builds before __seek).
     A bloom that mounts after the freeze is recorded (`late`) and lint reports it. */
  const registry = { blooms: [], leaks: [], sweeps: [], n: null, late: 0 };
  const bloomCount = () => registry.n === null ? registry.blooms.length : registry.n;
  function freezeCount() { if (registry.n === null) registry.n = registry.blooms.length; }
  const rectOf = el => ({ x: el.offsetLeft, y: el.offsetTop, w: el.offsetWidth, h: el.offsetHeight });
  function layer(parent, before, css) {
    const d = document.createElement('div'); Object.assign(d.style, { position: 'absolute', pointerEvents: 'none' }, css);
    if (before) parent.insertBefore(d, before); else parent.appendChild(d);
    return d;
  }

  /* ------------------------------------------------------------------ bloom -------------------------------------- */
  /* LIGHT.bloom(tl, el, at, o) → { glow, end, hold }
     el   a positioned element with final layout (a card, a figure) inside a positioned host; the glow is inserted as a
          sibling right behind it (same offset parent), sized el × (1 + 2·spread) and centred on it
     o    peak .30 · ceiling .45 · grow 1.0 (0.6–1.4) · scale0 .80 · blur 28 (fixed) · spread .55 · color gold · until
          (block-local s the hold ends; default at + 6) · shadow true (a coloured box-shadow 0 0 48px on el itself) */
  function bloom(tl, el, at, o) {
    o = o || {}; ensurePlugin(); const B = tokens.bloom, G = motion().gsap;
    const grow = clamp(num(o.grow, B.grow), B.growMin, B.growMax), peak = Math.min(num(o.peak, B.peak), num(o.ceiling, B.ceiling));
    const until = num(o.until, at + 6), hold = Math.max(grow, until - at), color = o.color || tokens.gold, spread = num(o.spread, B.spread);
    const r = rectOf(el), pw = r.w * spread, ph = r.h * spread;
    const glow = layer(el.parentNode, el, {
      left: (r.x - pw) + 'px', top: (r.y - ph) + 'px', width: (r.w + 2 * pw) + 'px', height: (r.h + 2 * ph) + 'px', borderRadius: '50%',
      background: 'radial-gradient(ellipse at 50% 50%, rgba(' + rgb(color) + ',.95) 0%, rgba(' + rgb(color) + ',.35) 38%, rgba(' + rgb(color) + ',0) 70%)',
      filter: 'blur(' + num(o.blur, B.blur) + 'px)', opacity: '0', transformOrigin: '50% 50%'
      // no will-change: a promoted layer whose transform changes per frame rasters at a history-dependent scale (a cold seek and a
      // stepped run disagreed on 46/76 frames of a frosted panel under load); the blur filter already gives the glow its own surface
    });
    glow.className = 'light-bloom'; glow.dataset.lightBloom = at.toFixed(3) + ':' + until.toFixed(3);
    const rec = { el, glow, at, until, peak }; registry.blooms.push(rec); if (registry.n !== null) registry.late++;
    tl.fromTo(glow, { scale: num(o.scale0, B.scale0) }, { scale: 1, duration: grow, ease: o.ease || B.ease, immediateRender: false }, at);
    // opacity is one pure function of local time (grow, then breathe) so a seek lands on the same value as a step
    tl.to({}, { duration: hold, ease: 'none', lightPaint: u => { glow.style.opacity = bloomEnv(u * hold, { grow, peak, ceiling: o.ceiling, hold, n: bloomCount(), amp: o.breatheAmp, period: o.breathePeriod, fade: o.breatheFade }).toFixed(4); } }, at);
    if (o.shadow !== false) tl.fromTo(el, { boxShadow: '0 0 0px 0px rgba(' + rgb(color) + ',0)' }, { boxShadow: '0 0 48px 2px rgba(' + rgb(color) + ',' + (peak * 0.6).toFixed(3) + ')', duration: grow, ease: 'power2.out', immediateRender: false }, at);
    return { glow, end: at + grow, hold: until };
  }

  /* ------------------------------------------------------------------ leak --------------------------------------- */
  /* LIGHT.leak(tl, stage, at, o) → { el, end }
     Three blurred warm ellipses on a full-stage screen-blend layer; dur ≤ 0.5 s. Over footage this is a SEAM accent and
     must be declared: o.window = [t0, t1] (block-local) — the leak throws when [at, at+dur] is not inside it. The layer
     is appended to o.host (default `stage`) at z-index 30: above the footage, below the overlay and caption lanes. */
  function leak(tl, stage, at, o) {
    o = o || {}; const L = tokens.leak, rng = motion().rng(num(o.seed, 7));
    const dur = Math.min(num(o.dur, L.durMax), L.durMax);
    if (o.overFootage !== false) {
      if (!Array.isArray(o.window) || o.window.length !== 2) throw new Error('LIGHT.leak: a leak over footage needs o.window = [t0, t1] (the declared seam window)');
      if (at < o.window[0] - 1e-6 || at + dur > o.window[1] + 1e-6) throw new Error('LIGHT.leak: [' + at + ', ' + (at + dur).toFixed(3) + '] leaves the seam window [' + o.window.join(', ') + ']');
    }
    const host = o.host || stage, W = host.offsetWidth || 1280, H = host.offsetHeight || 720;
    const el = layer(host, null, { left: '0px', top: '0px', width: W + 'px', height: H + 'px', mixBlendMode: 'screen', opacity: '0', zIndex: String(num(o.z, L.z)), overflow: 'hidden' });
    el.className = 'light-leak'; el.dataset.lightLeak = at.toFixed(3) + ':' + (at + dur).toFixed(3);
    const colors = o.colors || [tokens.amber, tokens.coral, tokens.gold], sizes = [[0.62, 0.55], [0.48, 0.40], [0.55, 0.36]], alphas = [0.9, 0.7, 0.8];
    colors.forEach((c, i) => {
      const w = W * sizes[i % 3][0], h = H * sizes[i % 3][1];
      const x0 = W * (0.1 + 0.6 * rng()) - w / 2, y0 = H * (0.1 + 0.6 * rng()) - h / 2;
      const dx = (rng() - 0.5) * 2 * W * L.drift * (i % 2 ? -1 : 1), dy = (rng() - 0.5) * H * L.drift;
      const e = layer(el, null, { left: x0 + 'px', top: y0 + 'px', width: w + 'px', height: h + 'px', borderRadius: '50%', filter: 'blur(' + num(o.blur, L.blur) + 'px)',
        background: 'radial-gradient(closest-side, rgba(' + rgb(c) + ',' + alphas[i % 3] + '), rgba(' + rgb(c) + ',0) 72%)' });
      tl.fromTo(e, { x: -dx / 2, y: -dy / 2 }, { x: dx / 2, y: dy / 2, duration: dur, ease: 'none', immediateRender: false }, at);
    });
    tl.to(el, { keyframes: [
      { opacity: L.env[1], duration: dur * L.at[1], ease: 'power2.out' },
      { opacity: L.env[2], duration: dur * (L.at[2] - L.at[1]), ease: 'sine.inOut' },
      { opacity: L.env[3], duration: dur * (L.at[3] - L.at[2]), ease: 'power2.in' } ] }, at);
    registry.leaks.push({ el, at, end: at + dur, window: o.window || null });
    return { el, end: at + dur };
  }

  /* ------------------------------------------------------------------ sweep -------------------------------------- */
  /* LIGHT.sweep(tl, el, at, o) → { band, end }: one 105° light band crosses the card in 0.9 s (power2.inOut), opacity
     peaking at .32 mid-travel. The band lives in a clipped child (border-radius inherited) — the card's own pixels are
     untouched; only the band's transform and opacity move. Once per card per beat. */
  function sweep(tl, el, at, o) {
    o = o || {}; ensurePlugin(); const S = tokens.sweep, dur = num(o.dur, S.dur), angle = num(o.angle, S.angle);
    if (getComputedStyle(el).position === 'static') el.style.position = 'relative';
    const clip = layer(el, null, { left: '0px', top: '0px', width: '100%', height: '100%', overflow: 'hidden', borderRadius: 'inherit' });
    clip.className = 'light-sweep';
    const r = rectOf(el), bw = Math.max(40, r.w * num(o.band, S.band));
    const band = layer(clip, null, { left: '0px', top: '-50%', width: bw + 'px', height: '200%', opacity: '0',
      background: 'linear-gradient(' + angle + 'deg, rgba(255,255,255,0) 0%, rgba(255,255,255,.55) 45%, rgba(255,255,255,.9) 50%, rgba(255,255,255,.55) 55%, rgba(255,255,255,0) 100%)' });
    const travel = r.w + bw;
    tl.to({}, { duration: dur, ease: 'none', lightPaint: u => { const e = sweepEnv(u * dur, dur);
      band.style.transform = 'translateX(' + ((-bw + (e.x + 1) / 2 * travel)).toFixed(2) + 'px) skewX(' + (90 - angle).toFixed(1) + 'deg)';
      band.style.opacity = e.opacity.toFixed(4); } }, at);
    registry.sweeps.push({ el, at, end: at + dur });
    return { band, end: at + dur };
  }

  /* ------------------------------------------------------------------ rim ---------------------------------------- */
  /* LIGHT.rim(el, o) → the highlight element: a static 1 px line along the top edge, white .55 at centre, clear at the
     corners (inset 10 px so a rounded corner is not crossed). Static: nothing to seek. */
  function rim(el, o) {
    o = o || {}; const R = tokens.rim, a = num(o.alpha, R.alpha), inset = num(o.inset, R.inset);
    if (getComputedStyle(el).position === 'static') el.style.position = 'relative';
    const line = layer(el, null, { left: inset + 'px', right: inset + 'px', top: '0px', height: '1px',
      background: 'linear-gradient(90deg, rgba(255,255,255,0), rgba(255,255,255,' + a + ') 50%, rgba(255,255,255,0))' });
    line.className = 'light-rim';
    return line;
  }

  /* ------------------------------------------------------------------ ledger + lint ------------------------------ */
  /* what a gate can read back: every bloom / leak / sweep with its window (block-local seconds) */
  function ledger() {
    return { blooms: registry.blooms.map(b => ({ at: b.at, until: b.until, peak: b.peak })), n: bloomCount(), late: registry.late,
             leaks: registry.leaks.map(l => ({ at: l.at, end: l.end, window: l.window })), sweeps: registry.sweeps.map(s => ({ at: s.at, end: s.end })) };
  }
  /* findings over the ledger (pure): leaks outside their window, leaks longer than 0.5 s, bloom peaks over the ceiling */
  function lint(led) {
    led = led || ledger(); const out = [];
    (led.leaks || []).forEach((l, i) => {
      if (l.end - l.at > tokens.leak.durMax + 1e-6) out.push({ rule: 'leak_too_long', i, msg: 'leak ' + i + ' lasts ' + (l.end - l.at).toFixed(2) + ' s (max 0.5)' });
      if (l.window && (l.at < l.window[0] - 1e-6 || l.end > l.window[1] + 1e-6)) out.push({ rule: 'leak_outside_window', i, msg: 'leak ' + i + ' leaves its seam window' });
    });
    (led.blooms || []).forEach((b, i) => { if (b.peak > tokens.bloom.ceiling + 1e-6) out.push({ rule: 'bloom_over_ceiling', i, msg: 'bloom ' + i + ' peak ' + b.peak + ' > ' + tokens.bloom.ceiling }); });
    if (led.late > 0) out.push({ rule: 'bloom_after_first_seek', i: -1, msg: led.late + ' bloom(s) mounted after the first seek: N was frozen without them (mount every bloom before frame 0)' });
    return out;
  }

  const LIGHT = { tokens, bloom, leak, sweep, rim, ledger, lint, env: { bloom: bloomEnv, leak: leakEnv, sweep: sweepEnv, breathe }, rgb };
  root.LIGHT = LIGHT;

  /* ------------------------------------------------------------------ node CLI ----------------------------------- */
  function selftest() {
    const fails = [];
    const eq = (a, b, tol, what) => { if (Math.abs(a - b) > (tol || 1e-9)) fails.push(what + ': ' + a + ' vs ' + b); };
    // bloom: 0 before, peak at the end of grow, never above the ceiling, breathe shrinks with N
    eq(bloomEnv(-0.1, {}), 0, 0, 'bloom before at');
    eq(bloomEnv(1.0, { grow: 1.0 }), 0.30, 1e-9, 'bloom peak at grow end');
    let mx = 0; for (let s = 0; s <= 6; s += 1 / 30) mx = Math.max(mx, bloomEnv(s, { peak: 0.44, hold: 6, n: 1 }));
    if (mx > 0.45 + 1e-9) fails.push('bloom crossed the ceiling: ' + mx);
    const swing = n => { let lo = 1, hi = 0; for (let s = 1; s <= 6; s += 1 / 60) { const v = bloomEnv(s, { hold: 6, n }); lo = Math.min(lo, v); hi = Math.max(hi, v); } return hi - lo; };
    eq(swing(4) / swing(1), 0.5, 0.02, 'breathe amplitude ∝ 1/sqrt(N) (N=4 → half)');
    eq(bloomEnv(6, { hold: 6 }), 0.30, 1e-6, 'breathe fades out by the end of the hold');
    // leak: envelope through the measured points, zero outside, clamped at 0.5 s
    eq(leakEnv(0.5 * 0.35, 0.5), 0.90, 1e-9, 'leak 35 %'); eq(leakEnv(0.5 * 0.70, 0.5), 0.46, 1e-9, 'leak 70 %');
    eq(leakEnv(0.6, 0.9), 0, 0, 'leak clamped to 0.5 s'); eq(leakEnv(-0.01, 0.5), 0, 0, 'leak before');
    // sweep: starts off-left, ends off-right, peak .32 at the middle
    eq(sweepEnv(0, 0.9).x, -1, 0, 'sweep start'); eq(sweepEnv(0.9, 0.9).x, 1, 0, 'sweep end'); eq(sweepEnv(0.45, 0.9).opacity, 0.32, 1e-9, 'sweep peak');
    // lint: a leak outside its window is a finding, one inside is not
    const f1 = lint({ leaks: [{ at: 0.2, end: 0.6, window: [0, 0.5] }] }); if (!f1.length) fails.push('lint missed a leak outside its window');
    const f0 = lint({ leaks: [{ at: 0.0, end: 0.45, window: [0, 0.5] }], blooms: [{ peak: 0.3 }] }); if (f0.length) fails.push('lint false positive: ' + JSON.stringify(f0));
    // with gsap available: a timeline-driven envelope is seek-order independent
    if (root.MOTION) {
      ensurePlugin(); const tl = root.MOTION.gsap.timeline({ paused: true }); const seen = {};
      tl.to({}, { duration: 2, ease: 'none', lightPaint: u => { seen.v = bloomEnv(u * 2, { hold: 2 }); } }, 0);
      tl.totalTime(1.5, true); const a = seen.v; tl.totalTime(0.3, true); tl.totalTime(1.5, true);
      if (a === undefined || seen.v !== a) fails.push('seek order (1.5 → 0.3 → 1.5) changed the painted value: ' + a + ' vs ' + seen.v);
      eq(a, bloomEnv(1.5, { hold: 2 }), 0, 'timeline-driven value equals the pure envelope');
      // N freezes on the first MOTION.seek; a bloom pushed afterwards is counted as late and lint reports it
      if (root.MOTION.onSeek) {
        const n0 = registry.blooms.length; registry.blooms.push({ at: 0, until: 1, peak: 0.1 }); root.MOTION.seek(0);
        if (registry.n !== n0 + 1) fails.push('N did not freeze on the first seek: ' + registry.n);
        registry.blooms.push({ at: 0, until: 1, peak: 0.1 }); registry.late++;
        if (bloomCount() !== n0 + 1) fails.push('frozen N changed after a late mount: ' + bloomCount());
        if (!lint(ledger()).some(f => f.rule === 'bloom_after_first_seek')) fails.push('lint missed a bloom mounted after the first seek');
        registry.blooms.length = n0; registry.n = null; registry.late = 0;
      }
    }
    return { ok: !fails.length, fails, gsap: !!root.MOTION, samples: { bloom_1s: bloomEnv(1, {}), leak_35: leakEnv(0.175, 0.5), sweep_mid: sweepEnv(0.45, 0.9) } };
  }
  function cli(argv) {
    const arg = (k, d) => { const i = argv.indexOf(k); return i >= 0 && argv[i + 1] !== undefined ? argv[i + 1] : d; };
    const out = s => process.stdout.write(JSON.stringify(s, null, 2) + '\n');
    if (argv.includes('--help') || argv.includes('-h') || !argv.length) {
      process.stdout.write('light.js — LIGHT envelopes (pure) and selftest\n  node lib/light.js --selftest\n  node lib/light.js --envelope bloom|leak|sweep [--dur s] [--fps 30] [--n N] [--hold s]\n  exit 0 ok · 1 findings · 2 usage\n');
      process.exit(argv.length ? 0 : 2);
    }
    if (argv.includes('--selftest')) { const r = selftest(); out(r); process.exit(r.ok ? 0 : 1); }
    const kind = arg('--envelope');
    if (!kind || !LIGHT.env[kind]) { process.stderr.write('usage: --envelope bloom|leak|sweep\n'); process.exit(2); }
    const fps = +arg('--fps', 30), dur = +arg('--dur', kind === 'leak' ? 0.5 : kind === 'sweep' ? 0.9 : +arg('--hold', 6)), n = +arg('--n', 1);
    const samples = []; for (let i = 0; i <= Math.round(dur * fps); i++) { const s = i / fps; samples.push({ t: +s.toFixed(4), v: kind === 'bloom' ? bloomEnv(s, { hold: dur, n }) : kind === 'leak' ? leakEnv(s, dur) : sweepEnv(s, dur) }); }
    out({ envelope: kind, dur, fps, n, samples }); process.exit(0);
  }
  if (IS_NODE && typeof module !== 'undefined' && module.exports) {
    module.exports = LIGHT;
    if (require.main === module) {
      try { if (!root.gsap) root.gsap = require('gsap').gsap; if (!root.MOTION) require('./motion.js'); } catch (e) { /* pure parts only */ }
      cli(process.argv.slice(2));
    }
  }
})(typeof window !== 'undefined' ? window : globalThis);
