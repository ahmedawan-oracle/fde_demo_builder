/* motion.js — MOTION: GSAP timelines driven by the film clock.

   GSAP gives us eased, composable keyframes; the film clock gives us determinism. This module makes the two agree:
   every timeline is created PAUSED, its ticker never runs, and each frame(t) sets every mounted timeline to its local
   time with tl.totalTime(local, true). Same t, same pixels — on any machine, in any worker, in any order.

   Usage (scene):
     <script src="../node_modules/gsap/dist/gsap.min.js"></script>  <!-- npm i gsap; never a CDN -->
     <script src="lib/motion.js"></script>
     const card = MOTION.block('title', (tl, el) => {                // build once; the timeline is paused
       tl.fromTo(el.querySelector('h1'), { y: 40, opacity: 0 }, { y: 0, opacity: 1, duration: 0.6, ease: 'power3.out' });
       tl.to(el, { scale: 1.04, duration: 6, ease: 'none' }, 0);     // the sanctioned slow push
     }, { el: $('#titleCard'), start: 0, end: P.nb, exit: 0.4 });
     function frame(t) { …; MOTION.seek(t); … }

   Contract: build(tl, el, api) runs ONCE at mount, synchronously, and must not read the wall clock or random numbers
   (use MOTION.rng(seed)). Elements outside [start, end) are hidden by MOTION (visibility), so a block never leaks into
   another beat. `exit` (seconds) is how long before `end` the timeline's own exit segment should start — the block
   reads it from api.exitAt. Nothing here touches the footage lane.

   Outside a block, write a property with MOTION.set (a bare gsap.set never renders under the paused ticker; inside a
   block use tl.set) and draw per-frame state from MOTION.onSeek(fn) (GSAP suppresses onUpdate under totalTime). */
(function (root) {
  'use strict';
  const G = root.gsap;
  if (!G) throw new Error('motion.js: load gsap before lib/motion.js (npm i gsap; <script src="../node_modules/gsap/dist/gsap.min.js">)');
  // the ticker must never advance a timeline on its own: every value comes from seek()
  G.ticker.lagSmoothing(0);
  G.config({ autoSleep: 1e9, nullTargetWarn: false });
  if (G.globalTimeline) G.globalTimeline.pause();

  const blocks = [];
  const clamp = (x, a, b) => Math.max(a, Math.min(b, x));

  /* seeded PRNG (mulberry32): the only randomness a block may use */
  function rng(seed) {
    let s = (seed >>> 0) || 1;
    return () => { s = (s + 0x6D2B79F5) >>> 0; let x = Math.imul(s ^ (s >>> 15), 1 | s); x ^= x + Math.imul(x ^ (x >>> 7), 61 | x); return ((x ^ (x >>> 14)) >>> 0) / 4294967296; };
  }

  /* mount a block: build(tl, el, api) → records {id, tl, el, start, end} */
  function block(id, build, o) {
    o = o || {};
    const tl = G.timeline({ paused: true });
    const start = o.start || 0, end = o.end === undefined ? Infinity : o.end;
    const api = { start, end, exitAt: Number.isFinite(end) ? Math.max(0, end - start - (o.exit || 0)) : Infinity, rng: rng(o.seed || hash(id)), clamp };
    build(tl, o.el || null, api);
    tl.pause(0);
    const b = { id, tl, el: o.el || null, start, end, hide: o.hide !== false, lastVisible: null };
    const i = blocks.findIndex(x => x.id === id);
    if (i >= 0) { try { blocks[i].tl.kill(); } catch (e) { /* replaced */ } blocks[i] = b; } else blocks.push(b);
    return b;
  }
  function hash(s) { let h = 2166136261; for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); } return h >>> 0; }

  /* set every timeline to the film time (idempotent, seek-safe); then the seek hooks (lib/cursor.js, lib/hud.js …)
     draw their own per-frame state from the same t — GSAP suppresses onUpdate when totalTime(t, true) is used,
     so a lib that needs a callback per frame registers it here instead of wrapping MOTION.seek */
  const hooks = [];
  function onSeek(fn) { if (typeof fn === 'function' && hooks.indexOf(fn) < 0) hooks.push(fn); return () => { const i = hooks.indexOf(fn); if (i >= 0) hooks.splice(i, 1); }; }
  function seek(t) {
    for (const b of blocks) {
      const inWin = t >= b.start && t < b.end;
      const local = clamp(t - b.start, 0, b.tl.totalDuration() || 0);
      b.tl.totalTime(local, true);
      if (b.el && b.hide) {
        const vis = inWin ? 'visible' : 'hidden';
        if (b.lastVisible !== vis) { b.el.style.visibility = vis; b.lastVisible = vis; }
      }
    }
    for (const h of hooks) h(t);
  }
  function get(id) { return blocks.find(b => b.id === id) || null; }
  function remove(id) { const i = blocks.findIndex(b => b.id === id); if (i >= 0) { try { blocks[i].tl.kill(); } catch (e) { /* gone */ } blocks.splice(i, 1); } }
  function list() { return blocks.map(b => ({ id: b.id, start: b.start, end: b.end, dur: b.tl.totalDuration() })); }

  /* eases we name in docs (GSAP strings): keep the vocabulary small and consistent across libs */
  const EASE = { push: 'sine.out', pan: 'sine.inOut', reveal: 'power4.out', exit: 'power4.in', settle: 'power3.out', expo: 'expo.out', none: 'none' };

  /* a reusable "arrive" for any element: rise + fade on power4.out, 0.5 s default (the measured entrance window) */
  function arrive(tl, el, at, o) {
    o = o || {};
    tl.fromTo(el, { y: o.dy === undefined ? 24 : o.dy, opacity: 0, scale: o.scale0 === undefined ? 0.985 : o.scale0 },
      { y: 0, opacity: 1, scale: 1, duration: o.dur || 0.5, ease: o.ease || EASE.reveal, immediateRender: false }, at);
    return tl;
  }
  /* "leave": exit ≈ 75 % of the entrance, power4.in, travel left on the house current unless told otherwise */
  function leave(tl, el, at, o) {
    o = o || {};
    tl.to(el, { x: o.dx === undefined ? -120 : o.dx, opacity: 0, duration: o.dur || 0.36, ease: o.ease || EASE.exit }, at);
    return tl;
  }
  /* stagger a list of elements with a shrinking gap (first 0.06 s, ×0.84 each), total capped at 0.5 s */
  function cascade(tl, els, at, o) {
    o = o || {};
    let gap = o.gap0 === undefined ? 0.06 : o.gap0, acc = 0; const cap = o.cap === undefined ? 0.5 : o.cap;
    els.forEach((el, i) => { arrive(tl, el, at + Math.min(acc, cap), { dy: o.dy, dur: o.dur || 0.42 }); acc += gap; gap *= (o.decay === undefined ? 0.84 : o.decay); });
    return tl;
  }

  /* set(target, vars): an immediate property write. gsap.set() alone is a zero-duration tween that waits for a tick
     the paused ticker never gives it — so it would silently do nothing here. Inside a block use tl.set(...) (driven by
     seek); outside a block use MOTION.set, which renders the write at once. */
  function set(target, vars) { const tw = G.set(target, vars); tw.render(0, true, true); return tw; }

  root.MOTION = { block, seek, onSeek, get, remove, list, rng, EASE, arrive, leave, cascade, set, gsap: G };
})(typeof window !== 'undefined' ? window : globalThis);
