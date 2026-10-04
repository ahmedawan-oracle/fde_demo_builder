/* compare.js — COMPARE: honest side-by-side, before/after and picture-in-picture blocks on the film clock.

   WHY. "Before and after" is the strongest claim a demo film makes, and the easiest to fake. These blocks let two
   real stills (or a second real recording) share the frame with nothing done to either: both halves are the
   recording's own pixels, scaled UNIFORMLY to the stage like the footage lane does, cut by a clip edge, never by a
   filter, blend, recolour or warp. Labels live in #ovl (the screen-space overlay layer), never on the pixels.

   BLOCKS (all GSAP timelines mounted through lib/motion.js — pure functions of t, seek-safe, no callbacks):
     COMPARE.split(host, { id, a:{src,label}, b:{src,label}, start, end, divider:[{t, x}], rect?, dividerPx:2, handle:true, ovl })
       two stills in one rect (default the whole 1280x720 stage); B is revealed to the right of a divider whose x
       (fraction of the width) moves between the keyframes on power2.inOut — the way a hand drags a handle — and
       holds between them. The divider is a 2 px ink line with a 36 px round grip (two chevrons) so it reads as
       draggable; nothing is actually interactive. Keyframe times are ABSOLUTE film seconds (pass wt()).
     COMPARE.wipe(host, { id, a:{src,label:'BEFORE'}, b:{src,label:'AFTER'}, start, end, at, dur:0.9, dir:'ltr', dividerPx:2, ovl })
       A alone until `at`; then B wipes in over `dur` (power2.inOut) behind a 2 px edge line that fades over the
       last 0.15 s; the BEFORE pill leaves and the AFTER pill arrives at the wipe's midpoint. dir: ltr | rtl | ttb | btt.
     COMPARE.pip(host, { id, src | frames:{base,count,fps,at}, start, end, corner:'br', width:0.28, margin:32, radius:14,
                         shadow:'0 30px 80px rgba(0,0,0,.45)', aspect:16/9, label, ovl })
       a second recording in a corner at 28 % of the stage width (358 px → 201 px tall at 16:9), 14 px corners, the
       house shadow; arrives from its corner over 0.5 s power4.out (scale 0.92 → 1), leaves over 0.36 s power4.in.
       With `frames`, call block.draw(t) from frame(t) (it picks f_###.jpg like the footage lane) and await
       block.pending — the renderer's decode-aware step takes care of the rest.
   Every block returns { id, kind, el, start, end, labels, ready (Promise: both images decoded), rect, tl } and is
   registered in MOTION under `id` (labels under `id:labels`). COMPARE.ready() awaits every block's images.

   PURE HELPERS (also what the node selftest checks): COMPARE.dividerAt(keys, t) → x fraction; COMPARE.wipeInset(u, dir, rect)
   → the clip-path inset string at progress u; COMPARE.pipRect(o, stage) → {x, y, w, h}; COMPARE.labelPos(kind, rect, side).

   Node CLI:  node lib/compare.js --selftest | --help        exit 0 ok · 1 findings · 2 usage */
(function (root) {
  'use strict';
  const PAL = { navy: '#082A34', navy2: '#204A56', ink: '#E9F3F9', cream: '#ECDEC3', coral: '#E56B5E', mint: '#81A9AB', gold: '#E8C874' };
  const STAGE = [1280, 720];
  const D = { dividerPx: 2, handle: 36, wipeDur: 0.9, wipeEase: 'power2.inOut', dragEase: 'power2.inOut', fadeEdge: 0.15, pipWidth: 0.28, pipMargin: 32, pipRadius: 14, pipShadow: '0 30px 80px rgba(0,0,0,.45)', arrive: 0.5, leave: 0.36 };
  const clamp = (x, a, b) => Math.max(a, Math.min(b, x));
  const p2io = x => (x = clamp(x, 0, 1)) < 0.5 ? 2 * x * x : 1 - Math.pow(-2 * x + 2, 2) / 2;
  const blocks = [];

  /* ---------- pure geometry ---------- */
  function dividerAt(keys, t) {
    if (!keys || !keys.length) return 0.5;
    const K = keys.slice().sort((a, b) => a.t - b.t);
    if (t <= K[0].t) return clamp(K[0].x, 0, 1);
    for (let i = 1; i < K.length; i++) if (t <= K[i].t) { const a = K[i - 1], b = K[i], u = p2io((t - a.t) / Math.max(1e-6, b.t - a.t)); return clamp(a.x + (b.x - a.x) * u, 0, 1); }
    return clamp(K[K.length - 1].x, 0, 1);
  }
  /* clip-path inset for the INCOMING picture at progress u (0 = hidden, 1 = whole rect) */
  function wipeInset(u, dir, rect) {
    u = clamp(u, 0, 1); const w = rect.w, h = rect.h, f = (v) => v.toFixed(2) + 'px';
    if (dir === 'rtl') return 'inset(0px 0px 0px ' + f(w * (1 - u)) + ')';
    if (dir === 'ttb') return 'inset(0px 0px ' + f(h * (1 - u)) + ' 0px)';
    if (dir === 'btt') return 'inset(' + f(h * (1 - u)) + ' 0px 0px 0px)';
    return 'inset(0px ' + f(w * (1 - u)) + ' 0px 0px)';                       // ltr: the edge travels left → right
  }
  function edgeAt(u, dir, rect) {       // where the wipe edge line sits at progress u (stage px, rect-relative)
    u = clamp(u, 0, 1);
    if (dir === 'rtl') return { x: rect.w * (1 - u), y: 0, vertical: true };
    if (dir === 'ttb') return { x: 0, y: rect.h * u, vertical: false };
    if (dir === 'btt') return { x: 0, y: rect.h * (1 - u), vertical: false };
    return { x: rect.w * u, y: 0, vertical: true };
  }
  function pipRect(o, stage) {
    o = o || {}; const S = stage || STAGE, w = Math.round(S[0] * (o.width || D.pipWidth)), h = Math.round(w / (o.aspect || 16 / 9)), m = o.margin === undefined ? D.pipMargin : o.margin, c = o.corner || 'br';
    return { x: c.endsWith('r') ? S[0] - m - w : m, y: c.startsWith('b') ? S[1] - m - h : m, w, h, corner: c };
  }
  function labelPos(kind, rect, side) {
    if (kind === 'pip') return { x: rect.x, y: rect.y - 30, align: 'left' };
    return side === 'b' ? { x: rect.x + rect.w - 16, y: rect.y + 16, align: 'right' } : { x: rect.x + 16, y: rect.y + 16, align: 'left' };
  }

  /* ---------- dom helpers ---------- */
  function div(parent, css, id) { const e = document.createElement('div'); if (id) e.id = id; e.style.cssText = css; parent.appendChild(e); return e; }
  function img(parent, src, rect) {
    const e = document.createElement('img'); e.alt = ''; e.decoding = 'sync'; e.setAttribute('src', src);
    e.style.cssText = 'position:absolute;left:0;top:0;width:' + rect.w + 'px;height:' + rect.h + 'px;display:block';   // uniform scale only: no filter, no blend, no object-fit crop
    parent.appendChild(e); return e;
  }
  function pill(parent, text, pos) {
    const e = document.createElement('div'); e.className = 'cmp-label'; e.textContent = String(text);
    e.style.cssText = 'position:absolute;top:' + pos.y + 'px;' + (pos.align === 'right' ? 'right:' + (STAGE[0] - pos.x) + 'px' : 'left:' + pos.x + 'px') +
      ';padding:6px 10px;border-radius:6px;background:rgba(8,42,52,.76);color:' + PAL.ink + ";font:600 12px/1 Arial,'Segoe UI',sans-serif;letter-spacing:.08em;text-transform:uppercase;white-space:nowrap;opacity:0";
    parent.appendChild(e); return e;
  }
  function rectOf(o) { return Object.assign({ x: 0, y: 0, w: STAGE[0], h: STAGE[1] }, o.rect || {}); }
  let pluginReady = false;
  function need(G) {
    if (!root.MOTION || !G) throw new Error('compare.js: load gsap and lib/motion.js before building compare blocks');
    if (pluginReady) return;
    // clipEdge: a rendered property (not a callback) — GSAP snaps inset() strings instead of interpolating them, and
    // MOTION.seek suppresses callbacks, so the clip is written here from the same pure helpers the selftest checks
    G.registerPlugin({ name: 'clipEdge', rawVars: 1, init(target, v) { this.t = target; this.a = v.from; this.d = v.to - v.from; this.f = v.fn; return true; },
      render(ratio, d) { d.t.style.clipPath = d.f(d.a + d.d * ratio); } });
    pluginReady = true;
  }
  function mountLabels(o, rect, kind, items, S) {
    const ovl = o.ovl || (document.getElementById('ovl')) || null; if (!ovl || !items.length) return { el: null, pills: [] };
    const host = div(ovl, 'position:absolute;inset:0;pointer-events:none;visibility:hidden', o.id + '-labels');
    const pills = items.map(it => pill(host, it.text, labelPos(kind, rect, it.side)));
    root.MOTION.block(o.id + ':labels', (tl, el) => { pills.forEach((p, i) => root.MOTION.arrive(tl, p, items[i].at || 0.1, { dy: 10, dur: 0.4 })); items.forEach((it, i) => { if (it.leaveAt !== undefined) tl.to(pills[i], { opacity: 0, y: -8, duration: 0.3, ease: 'power3.in' }, it.leaveAt); }); },
      { el: host, start: S.start, end: S.end });
    return { el: host, pills };
  }
  function finish(kind, o, S, el, rect, labels, imgs, tl, extra) {
    const b = Object.assign({ id: o.id, kind, el, start: S.start, end: S.end, labels, rect, tl, ready: Promise.all(imgs.map(i => i.decode().catch(() => {}))) }, extra || {});
    const i = blocks.findIndex(x => x.id === o.id); if (i >= 0) blocks[i] = b; else blocks.push(b); return b;
  }
  function window_(o) { const start = o.start || 0, end = o.end === undefined ? Infinity : o.end; return { start, end }; }

  /* ---------- split ---------- */
  function split(host, o) {
    o = Object.assign({ dividerPx: D.dividerPx, handle: true }, o || {}); const G = root.MOTION && root.MOTION.gsap; need(G);
    if (!o.id || !o.a || !o.b) throw new Error('compare.js: split needs id, a:{src}, b:{src}');
    const rect = rectOf(o), S = window_(o), keys = (o.divider && o.divider.length ? o.divider : [{ t: S.start, x: 0.5 }]).slice().sort((a, b) => a.t - b.t);
    const wrap = div(host, 'position:absolute;left:' + rect.x + 'px;top:' + rect.y + 'px;width:' + rect.w + 'px;height:' + rect.h + 'px;overflow:hidden;visibility:hidden', o.id);
    const A = img(wrap, o.a.src, rect), B = img(wrap, o.b.src, rect);
    const x0 = rect.w * clamp(keys[0].x, 0, 1);
    B.style.clipPath = 'inset(0px 0px 0px ' + x0.toFixed(2) + 'px)';
    const line = div(wrap, 'position:absolute;top:0;left:0;width:' + o.dividerPx + 'px;height:' + rect.h + 'px;background:' + PAL.ink + ';transform:translateX(' + (x0 - o.dividerPx / 2).toFixed(2) + 'px)');
    let grip = null;
    if (o.handle) {
      grip = div(wrap, 'position:absolute;left:0;top:50%;width:' + D.handle + 'px;height:' + D.handle + 'px;margin-top:' + (-D.handle / 2) + 'px;border-radius:50%;background:' + PAL.ink + ';box-shadow:0 6px 18px rgba(0,0,0,.35);display:flex;align-items:center;justify-content:center;gap:5px;color:' + PAL.navy + ';font:700 13px/1 Arial,sans-serif;transform:translateX(' + (x0 - D.handle / 2).toFixed(2) + 'px)');
      grip.innerHTML = '<span>&#8249;</span><span>&#8250;</span>';
    }
    const labels = mountLabels(o, rect, 'split', [o.a.label && { text: o.a.label, side: 'a' }, o.b.label && { text: o.b.label, side: 'b' }].filter(Boolean), S);
    const b = root.MOTION.block(o.id, (tl, el) => {
      root.MOTION.arrive(tl, el, 0, { dy: 0, scale0: 1, dur: 0.3 });
      for (let i = 1; i < keys.length; i++) {
        const a = keys[i - 1], k = keys[i], xa = rect.w * clamp(a.x, 0, 1), xb = rect.w * clamp(k.x, 0, 1), at = a.t - S.start, dur = Math.max(1 / 30, k.t - a.t);
        tl.to(B, { clipEdge: { from: xa, to: xb, fn: x => 'inset(0px 0px 0px ' + x.toFixed(2) + 'px)' }, duration: dur, ease: D.dragEase }, at);
        tl.fromTo(line, { x: xa - o.dividerPx / 2 }, { x: xb - o.dividerPx / 2, duration: dur, ease: D.dragEase, immediateRender: false }, at);
        if (grip) tl.fromTo(grip, { x: xa - D.handle / 2 }, { x: xb - D.handle / 2, duration: dur, ease: D.dragEase, immediateRender: false }, at);
      }
    }, { el: wrap, start: S.start, end: S.end });
    return finish('split', o, S, wrap, rect, labels, [A, B], b.tl, { keys, xAt: t => dividerAt(keys, t) });
  }

  /* ---------- wipe ---------- */
  function wipe(host, o) {
    o = Object.assign({ dividerPx: D.dividerPx, dur: D.wipeDur, dir: 'ltr' }, o || {}); const G = root.MOTION && root.MOTION.gsap; need(G);
    if (!o.id || !o.a || !o.b) throw new Error('compare.js: wipe needs id, a:{src}, b:{src}');
    const rect = rectOf(o), S = window_(o), at = (o.at === undefined ? S.start + 0.5 : o.at) - S.start;
    if (at < 0) throw new Error('compare.js: wipe `at` is before `start`');
    const wrap = div(host, 'position:absolute;left:' + rect.x + 'px;top:' + rect.y + 'px;width:' + rect.w + 'px;height:' + rect.h + 'px;overflow:hidden;visibility:hidden', o.id);
    const A = img(wrap, o.a.src, rect), B = img(wrap, o.b.src, rect);
    B.style.clipPath = wipeInset(0, o.dir, rect);
    const e0 = edgeAt(0, o.dir, rect), e1 = edgeAt(1, o.dir, rect);
    const line = div(wrap, 'position:absolute;left:0;top:0;background:' + PAL.ink + ';opacity:0;' + (e0.vertical ? 'width:' + o.dividerPx + 'px;height:' + rect.h + 'px' : 'height:' + o.dividerPx + 'px;width:' + rect.w + 'px'));
    const half = o.dividerPx / 2, pos = e => e.vertical ? { x: e.x - half, y: 0 } : { x: 0, y: e.y - half };
    const labels = mountLabels(o, rect, 'wipe', [o.a.label && { text: o.a.label, side: 'a', at: 0.1, leaveAt: at + o.dur * 0.5 }, o.b.label && { text: o.b.label, side: 'b', at: at + o.dur * 0.5 }].filter(Boolean), S);
    const b = root.MOTION.block(o.id, (tl, el) => {
      root.MOTION.arrive(tl, el, 0, { dy: 0, scale0: 1, dur: 0.3 });
      tl.to(B, { clipEdge: { from: 0, to: 1, fn: u => wipeInset(u, o.dir, rect) }, duration: o.dur, ease: D.wipeEase }, at);
      tl.fromTo(line, Object.assign({ opacity: 1 }, pos(e0)), Object.assign({ duration: o.dur, ease: D.wipeEase, immediateRender: false }, pos(e1)), at);
      tl.fromTo(line, { opacity: 1 }, { opacity: 0, duration: D.fadeEdge, ease: 'none', immediateRender: false }, at + o.dur - D.fadeEdge);
    }, { el: wrap, start: S.start, end: S.end });
    return finish('wipe', o, S, wrap, rect, labels, [A, B], b.tl, { at: o.at, dur: o.dur, dir: o.dir, uAt: t => p2io((t - S.start - at) / o.dur) });
  }

  /* ---------- pip ---------- */
  function pip(host, o) {
    o = Object.assign({ corner: 'br', width: D.pipWidth, margin: D.pipMargin, radius: D.pipRadius, shadow: D.pipShadow, aspect: 16 / 9 }, o || {}); const G = root.MOTION && root.MOTION.gsap; need(G);
    if (!o.id || !(o.src || o.frames)) throw new Error('compare.js: pip needs id and src or frames:{base,count,fps,at}');
    const rect = pipRect(o), S = window_(o);
    const wrap = div(host, 'position:absolute;left:' + rect.x + 'px;top:' + rect.y + 'px;width:' + rect.w + 'px;height:' + rect.h + 'px;border-radius:' + o.radius + 'px;overflow:hidden;box-shadow:' + o.shadow + ';background:' + PAL.navy2 + ';visibility:hidden;transform-origin:' + (rect.corner.endsWith('r') ? '100%' : '0%') + ' ' + (rect.corner.startsWith('b') ? '100%' : '0%'), o.id);
    const frameSrc = f => o.frames.base + 'f_' + String(f).padStart(3, '0') + '.jpg';
    const I = img(wrap, o.src || frameSrc(1), { w: rect.w, h: rect.h });
    const labels = mountLabels(o, rect, 'pip', o.label ? [{ text: o.label, side: 'a', at: 0.25 }] : [], S);
    const b = root.MOTION.block(o.id, (tl, el, api) => {
      tl.fromTo(el, { opacity: 0, scale: 0.92 }, { opacity: 1, scale: 1, duration: D.arrive, ease: 'power4.out', immediateRender: false }, 0);
      if (Number.isFinite(api.exitAt)) tl.to(el, { opacity: 0, scale: 0.94, duration: D.leave, ease: 'power4.in' }, api.exitAt);
    }, { el: wrap, start: S.start, end: S.end, exit: Number.isFinite(S.end) ? D.leave : 0 });
    let pending = [];
    function draw(t) {                   // frames: the clip plays from frames.at at frames.fps and holds on its last frame
      pending = []; if (!o.frames) return pending;
      const f = clamp(1 + Math.floor(Math.max(0, t - (o.frames.at === undefined ? S.start : o.frames.at)) * (o.frames.fps || 30) + 1e-6), 1, o.frames.count || 1);
      const src = frameSrc(f); if (I.getAttribute('src') !== src) { I.setAttribute('src', src); pending.push(I.decode().catch(() => {})); }
      return pending;
    }
    return finish('pip', o, S, wrap, rect, labels, [I], b.tl, { draw, get pending() { return pending; } });
  }

  function ready() { return Promise.all(blocks.map(b => b.ready)); }
  function list() { return blocks.map(b => ({ id: b.id, kind: b.kind, start: b.start, end: b.end, rect: b.rect })); }

  /* ---------- node selftest ---------- */
  function selftest() {
    const out = [], fail = m => out.push('FAIL ' + m), ok = m => out.push('ok   ' + m);
    const keys = [{ t: 2, x: 0.5 }, { t: 3, x: 0.2 }, { t: 5, x: 0.8 }];
    (dividerAt(keys, 1) === 0.5 && dividerAt(keys, 9) === 0.8 ? ok : fail)('divider holds its first/last keyframe outside the range');
    (Math.abs(dividerAt(keys, 2.5) - 0.35) < 1e-9 ? ok : fail)('divider is half-way at the midpoint of a drag (power2.inOut is symmetric)');
    const q = dividerAt(keys, 2.25); (q > 0.46 && q < 0.5 ? ok : fail)('drag eases in: 25 % of the time covers 12.5 % of the distance (x=' + q.toFixed(4) + ')');
    const R = { x: 0, y: 0, w: 1280, h: 720 };
    (wipeInset(0, 'ltr', R) === 'inset(0px 1280.00px 0px 0px)' && wipeInset(1, 'ltr', R) === 'inset(0px 0.00px 0px 0px)' ? ok : fail)('ltr wipe: hidden → whole rect');
    (wipeInset(0.5, 'ttb', R) === 'inset(0px 0px 360.00px 0px)' && wipeInset(0.25, 'btt', R) === 'inset(540.00px 0px 0px 0px)' ? ok : fail)('ttb / btt insets');
    const e = edgeAt(0.5, 'rtl', R); (Math.abs(e.x - 640) < 1e-9 && e.vertical ? ok : fail)('edge line rides the wipe front');
    const pr = pipRect({ corner: 'br' }); (pr.w === 358 && pr.h === 201 && pr.x === 1280 - 32 - 358 && pr.y === 720 - 32 - 201 ? ok : fail)('pip 28 % → 358x201 in the bottom-right with a 32 px margin (got ' + [pr.x, pr.y, pr.w, pr.h].join(',') + ')');
    const tl = pipRect({ corner: 'tl', width: 0.2 }); (tl.x === 32 && tl.y === 32 && tl.w === 256 ? ok : fail)('pip tl / 20 % → 256 px wide at 32,32');
    const lp = labelPos('split', R, 'b'); (lp.align === 'right' && lp.x === 1264 ? ok : fail)('B label right-aligned 16 px inside the rect');
    (labelPos('pip', pr).y === pr.y - 30 ? ok : fail)('pip label sits 30 px above the pip');
    const bad = out.filter(l => l.startsWith('FAIL')).length; return { ok: bad === 0, lines: out, failures: bad };
  }
  function cli(argv) {
    if (!argv.length || argv.includes('--help') || argv.includes('-h')) { console.log('compare.js — split / wipe / pip blocks\n  node lib/compare.js --selftest\n  exit 0 ok · 1 findings · 2 usage'); return argv.length ? 0 : 2; }
    if (argv.includes('--selftest')) { const r = selftest(); console.log(r.lines.join('\n')); console.log(JSON.stringify({ selftest: 'compare.js', ok: r.ok, failures: r.failures })); return r.ok ? 0 : 1; }
    console.error('usage: --selftest | --help'); return 2;
  }

  const COMPARE = { split, wipe, pip, ready, list, dividerAt, wipeInset, edgeAt, pipRect, labelPos, selftest, D, PAL };
  root.COMPARE = COMPARE;
  if (typeof module !== 'undefined' && module.exports) { module.exports = COMPARE; if (require.main === module) process.exit(cli(process.argv.slice(2))); }
})(typeof window !== 'undefined' ? window : globalThis);
