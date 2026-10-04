/* glass.js — GLASS: frosted panels for the recreated layer (lib/motion.js + GSAP). A panel sits in a screen-space
   layer the scene owns; what shows through it is blurred by the compositor, the pixels underneath are untouched.

   Why frosted. A caption plate in flat navy over footage hides what it covers; a frosted plate lets the eye keep the
   product's layout under it while the plate's own text stays readable. The blur radius is fixed at build (24–28 px,
   never animated), so the frost is a material, not an effect.

   The measured numbers (defaults; every helper takes overrides)
     material  backdrop-filter blur(26px) saturate(1.4); fill rgba(255,255,255,.08) on the DARK variant (panel over a
               dark card) / rgba(0,0,0,.28) on the LIGHT variant (panel over light footage) / rgba(5,22,28,.86) on the
               PAGE variant (panel over a white product page: the house ground as a near-opaque frost, so the panel
               reads as the recreated layer and its ink stays above 10:1 — the .28 black left light ink at ~2.3:1
               and a .66 black read as a mid-grey slab); 1 px border rgba(255,255,255,.25); radius 18 (16–20);
               inner top highlight 1 px rgba(255,255,255,.35); panel type (h3) at the 16 px floor; no will-change
     settle    scale .96 → 1 power3.out 0.45 s, opacity 0 → 1 over the first 0.30 s; exit 0.3 s power3.in, 1 → .98
     budget    at most 2 panels visible at once (each full-size backdrop blur costs a compositor pass at DPR 1.5); a panel
               never covers the caption lane (stage y ≥ 570 by default — the lane's home); GLASS.lint checks both

   Scene wiring
     <script src="../node_modules/gsap/dist/gsap.min.js"></script><script src="lib/motion.js"></script>
     <script src="lib/glass.js"></script>
     GLASS.install();                                            // tokens → :root CSS variables + one static <style>
     MOTION.block('why', (tl, el, api) => {
       const p = GLASS.panel(el, { variant: 'light', x: 760, y: 90, w: 440, h: 180, tl, at: 0.1, until: api.exitAt,
                                   html: '<h3>Why it matters</h3><p>Open claims, one view.</p>', window: [P.why, P.close] });
     }, { el: $('#ovl'), start: P.why, end: P.close, exit: 0.3 });

   Node (no DOM): node lib/glass.js --help | --selftest | --lint panels.json  (panels = GLASS.ledger())
   JSON in / JSON out; exit 0 ok, 1 findings, 2 usage. */
(function (root) {
  'use strict';
  const IS_NODE = typeof window === 'undefined';
  const clamp = (x, a, b) => Math.max(a, Math.min(b, x));
  const num = (v, d) => (v === undefined || v === null || Number.isNaN(v) ? d : v);
  const motion = () => { const m = root.MOTION; if (!m) throw new Error('glass.js: load gsap and lib/motion.js before lib/glass.js'); return m; };

  const tokens = {
    blur: 26, blurMin: 24, blurMax: 28, saturate: 1.4, radius: 18, radiusMin: 16, radiusMax: 20,
    fill: { dark: 'rgba(255,255,255,.08)', light: 'rgba(0,0,0,.28)', page: 'rgba(5,22,28,.86)' }, border: 'rgba(255,255,255,.25)', highlight: 'rgba(255,255,255,.35)',
    ink: { dark: '#E9F3F9', light: '#F4F7F9', page: '#E9F3F9' }, font: 'Arial, "Segoe UI", sans-serif',
    settle: { scale0: 0.96, dur: 0.45, ease: 'power3.out', fade: 0.30 }, exit: { dur: 0.30, ease: 'power3.in', scale1: 0.98 },
    maxPanels: 2, captionLaneY: 570, stage: { w: 1280, h: 720 }
  };
  const panels = [];
  let installed = false;

  /* GLASS.install(overrides) → tokens: writes --glass-* variables on :root and one static stylesheet (no transitions) */
  function install(o) {
    Object.assign(tokens, o || {});
    if (IS_NODE) { installed = true; return tokens; }
    const r = document.documentElement.style;
    r.setProperty('--glass-blur', tokens.blur + 'px'); r.setProperty('--glass-sat', String(tokens.saturate)); r.setProperty('--glass-radius', tokens.radius + 'px');
    r.setProperty('--glass-fill-dark', tokens.fill.dark); r.setProperty('--glass-fill-light', tokens.fill.light); r.setProperty('--glass-fill-page', tokens.fill.page || tokens.fill.light); r.setProperty('--glass-border', tokens.border);
    if (!document.getElementById('glass-style')) {
      const st = document.createElement('style'); st.id = 'glass-style';
      st.textContent = '.glass{position:absolute;box-sizing:border-box;overflow:hidden;pointer-events:none;border:1px solid var(--glass-border);border-radius:var(--glass-radius);' +
        /* no will-change: a promoted layer whose scale settles .96 -> 1 kept the raster scale the compositor picked mid-settle in one render
           and not the other (46/76 frames differed run to run under load).
           no backdrop-filter on the near-opaque 'page' fill: a backdrop root re-rasters the lane beneath it history-dependently (two
           concurrent 3-worker renders differed on 62/1171 frames for the panel's whole life at <= 15 levels; 0 without the filter), and
           at .86 the blur was invisible anyway. 'dark'/'light' panels keep the frost (class .frost) — use them over recreated cards. */
        'transform-origin:50% 50%}' +
        '.glass.frost{-webkit-backdrop-filter:blur(var(--glass-blur)) saturate(var(--glass-sat));backdrop-filter:blur(var(--glass-blur)) saturate(var(--glass-sat))}' +
        '.glass.dark{background:var(--glass-fill-dark);color:' + tokens.ink.dark + '}.glass.light{background:var(--glass-fill-light);color:' + tokens.ink.light + '}' +
        '.glass.page{background:var(--glass-fill-page);color:' + (tokens.ink.page || tokens.ink.dark) + '}' +
        '.glass .glass-hl{position:absolute;left:12px;right:12px;top:0;height:1px;background:linear-gradient(90deg,rgba(255,255,255,0),' + tokens.highlight + ' 50%,rgba(255,255,255,0))}' +
        '.glass .glass-body{position:absolute;inset:0;padding:18px 22px;font:400 16px/1.4 ' + tokens.font + '}' +
        '.glass .glass-body h3{margin:0 0 6px;font:600 16px/1 ' + tokens.font + ';letter-spacing:.12em;text-transform:uppercase;opacity:.8}.glass .glass-body p{margin:0}';   // 16 px: the legibility floor for every label
      document.head.appendChild(st);
    }
    installed = true; return tokens;
  }

  /* GLASS.panel(host, o) → { el, body, rect, end }
     o: variant 'dark'|'light'|'page' · x y w h (stage px; or rect {x,y,w,h}) · radius 16–20 · blur 24–28 · html | text ·
        tl + at (settle on a block timeline; omit for a static panel) · until (block-local; exit starts at until−0.3) ·
        window [t0, t1] film seconds (for the ≤ 2-at-once budget) · id · z */
  function panel(host, o) {
    o = o || {}; if (!installed) install();
    const variant = o.variant === 'light' || o.variant === 'page' ? o.variant : 'dark', r = o.rect || { x: num(o.x, 80), y: num(o.y, 80), w: num(o.w, 420), h: num(o.h, 160) };
    const blur = clamp(num(o.blur, tokens.blur), tokens.blurMin, tokens.blurMax), radius = clamp(num(o.radius, tokens.radius), tokens.radiusMin, tokens.radiusMax);
    const el = document.createElement('div'); el.className = 'glass ' + variant + (variant !== 'page' && o.frost !== false ? ' frost' : ''); if (o.id) el.id = o.id;
    Object.assign(el.style, { left: r.x + 'px', top: r.y + 'px', width: r.w + 'px', height: r.h + 'px', zIndex: String(num(o.z, 2)) });
    if (blur !== tokens.blur) { el.style.webkitBackdropFilter = 'blur(' + blur + 'px) saturate(' + tokens.saturate + ')'; el.style.backdropFilter = el.style.webkitBackdropFilter; }
    if (radius !== tokens.radius) el.style.borderRadius = radius + 'px';
    const hl = document.createElement('div'); hl.className = 'glass-hl'; const body = document.createElement('div'); body.className = 'glass-body';
    if (o.html) body.innerHTML = o.html; else if (o.text) body.textContent = o.text;
    el.appendChild(hl); el.appendChild(body); host.appendChild(el);
    el.dataset.glass = variant; el.dataset.glassRect = [r.x, r.y, r.w, r.h].join(',');
    const rec = { id: o.id || ('glass' + panels.length), variant, rect: r, window: o.window || null, at: num(o.at, 0), until: o.until === undefined ? null : o.until }; panels.push(rec);
    let end = num(o.at, 0);
    if (o.tl) {
      const S = tokens.settle, X = tokens.exit, at = num(o.at, 0);
      el.style.opacity = '0'; el.style.transform = 'scale(' + num(o.scale0, S.scale0) + ')';   // frame-0 state before any render (static style, no tween)
      o.tl.fromTo(el, { scale: num(o.scale0, S.scale0) }, { scale: 1, duration: num(o.settle, S.dur), ease: S.ease, immediateRender: false }, at);
      o.tl.fromTo(el, { opacity: 0 }, { opacity: 1, duration: S.fade, ease: 'power2.out', immediateRender: false }, at);
      end = at + num(o.settle, S.dur);
      if (Number.isFinite(o.until)) o.tl.to(el, { opacity: 0, scale: X.scale1, duration: X.dur, ease: X.ease }, Math.max(end, o.until - X.dur));
    }
    return { el, body, rect: r, end };
  }
  function remove(id) { const i = panels.findIndex(p => p.id === id); if (i >= 0) { panels.splice(i, 1); const el = document.getElementById(id); if (el) el.remove(); } }

  /* ------------------------------------------------------------------ ledger + lint ----------------------------- */
  function ledger() { return panels.map(p => ({ id: p.id, variant: p.variant, rect: p.rect, window: p.window, at: p.at, until: p.until })); }
  /* pure: > 2 panels whose windows overlap → 'panels_over_budget'; a rect reaching the caption lane → 'panel_on_caption_lane';
     rect outside the stage → 'panel_off_stage'. Panels without a window are assumed always visible. */
  function lint(led, o) {
    led = led || ledger(); o = o || {}; const out = [], laneY = num(o.captionLaneY, tokens.captionLaneY), maxP = num(o.maxPanels, tokens.maxPanels), W = tokens.stage.w, H = tokens.stage.h;
    led.forEach((p, i) => {
      const r = p.rect; if (r.y + r.h > laneY) out.push({ rule: 'panel_on_caption_lane', i, id: p.id, msg: p.id + ' reaches y=' + (r.y + r.h) + ' (caption lane from ' + laneY + ')' });
      if (r.x < 0 || r.y < 0 || r.x + r.w > W || r.y + r.h > H) out.push({ rule: 'panel_off_stage', i, id: p.id, msg: p.id + ' leaves the stage' });
    });
    const edges = []; led.forEach(p => { const w = p.window || [-Infinity, Infinity]; edges.push([w[0], 1], [w[1], -1]); });
    edges.sort((a, b) => a[0] - b[0] || a[1] - b[1]); let n = 0, worst = 0, at = null;
    edges.forEach(e => { n += e[1]; if (n > worst) { worst = n; at = e[0]; } });
    if (worst > maxP) out.push({ rule: 'panels_over_budget', msg: worst + ' panels visible at once from t=' + at + ' (max ' + maxP + ')' });
    return out;
  }

  const GLASS = { tokens, install, panel, remove, ledger, lint };
  root.GLASS = GLASS;

  /* ------------------------------------------------------------------ node CLI ----------------------------------- */
  function selftest() {
    const fails = [];
    const ok = lint([{ id: 'a', rect: { x: 80, y: 80, w: 420, h: 160 }, window: [0, 5] }, { id: 'b', rect: { x: 760, y: 90, w: 440, h: 180 }, window: [2, 8] }]);
    if (ok.length) fails.push('lint false positive: ' + JSON.stringify(ok));
    const over = lint([{ id: 'a', rect: { x: 0, y: 0, w: 100, h: 100 }, window: [0, 5] }, { id: 'b', rect: { x: 0, y: 0, w: 100, h: 100 }, window: [1, 6] }, { id: 'c', rect: { x: 0, y: 0, w: 100, h: 100 }, window: [2, 7] }]);
    if (!over.some(f => f.rule === 'panels_over_budget')) fails.push('lint missed 3 panels at once');
    const seq = lint([{ id: 'a', rect: { x: 0, y: 0, w: 100, h: 100 }, window: [0, 2] }, { id: 'b', rect: { x: 0, y: 0, w: 100, h: 100 }, window: [2, 4] }, { id: 'c', rect: { x: 0, y: 0, w: 100, h: 100 }, window: [4, 6] }]);
    if (seq.some(f => f.rule === 'panels_over_budget')) fails.push('lint counted back-to-back panels as concurrent');
    const lane = lint([{ id: 'a', rect: { x: 80, y: 500, w: 420, h: 160 } }]); if (!lane.some(f => f.rule === 'panel_on_caption_lane')) fails.push('lint missed the caption lane');
    const off = lint([{ id: 'a', rect: { x: 1000, y: 80, w: 420, h: 160 } }]); if (!off.some(f => f.rule === 'panel_off_stage')) fails.push('lint missed an off-stage panel');
    if (clamp(40, tokens.blurMin, tokens.blurMax) !== 28 || clamp(10, tokens.radiusMin, tokens.radiusMax) !== 16) fails.push('material clamps');
    if (!/^rgba\(5,22,28,\.8\d\)$/.test(tokens.fill.page) || !tokens.ink.page) fails.push('page variant tokens (fill rgba(5,22,28,.86) + ink) missing');
    if (root.MOTION) {                                             // settle curve on a plain object: .96 → 1 in 0.45 s, seek-order independent
      const G = root.MOTION.gsap, tl = G.timeline({ paused: true }), obj = { scale: 0.96 };
      tl.fromTo(obj, { scale: 0.96 }, { scale: 1, duration: 0.45, ease: 'power3.out' }, 0);
      tl.totalTime(0.2, true); const a = obj.scale; tl.totalTime(0.45, true); const b = obj.scale; tl.totalTime(0, true); tl.totalTime(0.2, true);
      if (Math.abs(b - 1) > 1e-9) fails.push('settle did not reach 1'); if (a !== obj.scale) fails.push('seek order changed the settle'); if (!(a > 0.96 && a < 1)) fails.push('settle mid value ' + a);
    }
    return { ok: !fails.length, fails, gsap: !!root.MOTION, tokens: { blur: tokens.blur, saturate: tokens.saturate, radius: tokens.radius, fill: tokens.fill, maxPanels: tokens.maxPanels, captionLaneY: tokens.captionLaneY } };
  }
  function cli(argv) {
    const arg = (k, d) => { const i = argv.indexOf(k); return i >= 0 && argv[i + 1] !== undefined ? argv[i + 1] : d; };
    const out = s => process.stdout.write(JSON.stringify(s, null, 2) + '\n');
    if (argv.includes('--help') || argv.includes('-h') || !argv.length) {
      process.stdout.write('glass.js — frosted panel budget lint and selftest\n  node lib/glass.js --selftest\n  node lib/glass.js --lint panels.json [--lane 570] [--max 2]   (panels.json = GLASS.ledger())\n  exit 0 ok · 1 findings · 2 usage\n');
      process.exit(argv.length ? 0 : 2);
    }
    if (argv.includes('--selftest')) { const r = selftest(); out(r); process.exit(r.ok ? 0 : 1); }
    if (argv.includes('--lint')) {
      const led = JSON.parse(require('fs').readFileSync(arg('--lint'), 'utf8')); const f = lint(led, { captionLaneY: +arg('--lane', tokens.captionLaneY), maxPanels: +arg('--max', tokens.maxPanels) });
      out({ findings: f, panels: led.length }); process.exit(f.length ? 1 : 0);
    }
    process.stderr.write('usage: --selftest | --lint panels.json (see --help)\n'); process.exit(2);
  }
  if (IS_NODE && typeof module !== 'undefined' && module.exports) {
    module.exports = GLASS;
    if (require.main === module) {
      try { if (!root.gsap) root.gsap = require('gsap').gsap; if (!root.MOTION) require('./motion.js'); } catch (e) { /* pure parts only */ }
      cli(process.argv.slice(2));
    }
  }
})(typeof window !== 'undefined' ? window : globalThis);
