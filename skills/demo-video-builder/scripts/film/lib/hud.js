/* hud.js — HUD: the keystroke pill. Shortcuts (Ctrl + K, Enter, Esc) and typed text from key events, on the film clock.

   Viewers cannot see a keyboard. When the presenter presses Ctrl+K or types a question, a small pill at the bottom
   centre of the frame — above the caption lane, in screen space, never inside #camera — names it. One pill at a time.

   Usage:
     <script src="../node_modules/gsap/dist/gsap.min.js"></script><script src="lib/motion.js"></script><script src="lib/hud.js"></script>
     const hud = HUD.mount($('#stage'), window.EVENTS, { bottom: 170, spans: [{ t0: 8.4, t1: 20.0, src: 12.0 }] });
     function frame(t) { …; MOTION.seek(t); … }        // HUD registers draw(t) through MOTION.onSeek (same hook as lib/cursor.js)

   Pills (built once at mount from the `key` events, in film time via `spans` as in cursor.js):
     shortcut   any key with Ctrl / Alt / Win held, or a special key (Enter, Esc, Tab, Backspace outside a typed run,
                arrows, Delete, Home/End, PageUp/Down, F-keys): keycaps joined by '+', shown for `holdShortcut` (0.9 s)
     typed      printable characters closer than `typedGap` (0.6 s) to each other form one run; the pill's text grows
                as the keys land (so it reads like typing), tail-truncated to `maxChars` (24) with a leading ellipsis;
                Backspace inside the run deletes; the pill stays `holdTyped` (0.8 s) after the last key
     one visible  pills are sorted by start; a pill ends no later than `out` seconds before the next one starts

   Envelope (the measured values): in 0.26 s — opacity 0 -> 1, y +10 -> 0, scale 0.86 -> 1 on back.out(1.6), the
   one sanctioned overshoot (a key press has a snap); out 0.20 s — opacity -> 0, scale -> 0.96 on power2.in.
   The envelope is a GSAP timeline in a MOTION block (seek-safe); the text at time t is a pure function of t.

   Geometry: bottom = 170 stage px (255 px at 1080p): the caption lane's box ends ~112 px up and runs <= 2 lines, so
   the pill sits above it without touching; pill height 36 stage px, keycaps 26 px tall, font 600 15px.

   Determinism: no wall clock, no randomness, no CSS animation. All DOM writes idempotent. */
(function (root) {
  'use strict';
  const clamp = (x, a, b) => Math.max(a, Math.min(b, x));
  const SPECIAL = { Enter: '↵ Enter', Esc: 'Esc', Tab: 'Tab ⇥', Backspace: '⌫', Delete: 'Del', Left: '←', Right: '→', Up: '↑', Down: '↓',
    Home: 'Home', End: 'End', PageUp: 'PgUp', PageDown: 'PgDn', Space: 'Space', Insert: 'Ins' };
  const DEFAULTS = { bottom: 170, stage: [1280, 720], font: "600 15px Arial, 'Segoe UI', sans-serif", bg: '#082A34', fg: '#E9F3F9', cap: '#E8C874',
    capBg: 'rgba(233,243,249,0.10)', inDur: 0.26, outDur: 0.20, typedGap: 0.6, holdTyped: 0.8, holdShortcut: 0.9, maxChars: 24, id: 'hud', spans: null, maxPills: 400 };

  /* clock hook: MOTION.onSeek(fn) → unsubscribe; the lib export is never reassigned */
  function onClock(fn) {
    const M = root.MOTION;
    if (!M) return null;
    if (typeof M.onSeek !== 'function') throw new Error('hud.js: lib/motion.js is older than this lib (MOTION.onSeek missing) — update lib/motion.js');
    return M.onSeek(fn);
  }
  const isShortcutMod = e => (e.mods || []).some(m => m === 'Ctrl' || m === 'Alt' || m === 'Win' || m === 'Cmd');
  const isSpecial = e => !!SPECIAL[e.key] || /^F\d{1,2}$/.test(e.key || '');
  const capLabel = k => SPECIAL[k] || (k && k.length === 1 ? k.toUpperCase() : k);

  /* key events (recording time) -> pills [{t0, t1, kind, caps | states:[{t, text}]}] in film time */
  function buildPills(events, o, filmOf) {
    const keys = events.filter(e => e.type === 'key' && typeof e.t === 'number').sort((a, b) => a.t - b.t);
    const pills = [];
    let run = null;
    const closeRun = () => { if (run) { run.t1 = run.lastT + o.holdTyped; pills.push(run); run = null; } };
    for (const e of keys) {
      const tf = filmOf(e.t); if (tf === null) continue;
      const printable = typeof e.char === 'string' && e.char.length > 0 && !isShortcutMod(e);
      const backspaceInRun = e.key === 'Backspace' && run && tf - run.lastT <= o.typedGap;
      if (printable || backspaceInRun) {
        if (run && tf - run.lastT > o.typedGap) closeRun();
        if (!run) run = { t0: tf, kind: 'typed', states: [], text: '', lastT: tf };
        run.text = backspaceInRun ? run.text.slice(0, -1) : run.text + e.char;
        run.states.push({ t: tf, text: run.text });
        run.lastT = tf;
        continue;
      }
      if (!(isShortcutMod(e) || isSpecial(e))) continue;          // a bare letter with --no-text: nothing to show
      closeRun();
      const caps = (e.mods || []).filter(m => m !== 'Shift' || isSpecial(e)).map(m => m === 'Cmd' ? '⌘' : m).concat([capLabel(e.key)]);
      pills.push({ t0: tf, t1: tf + o.holdShortcut, kind: 'shortcut', caps });
    }
    closeRun();
    pills.sort((a, b) => a.t0 - b.t0);
    for (let i = 0; i + 1 < pills.length; i++) pills[i].t1 = Math.min(pills[i].t1, pills[i + 1].t0 - o.outDur);   // one pill visible
    return pills.slice(0, o.maxPills);
  }

  function mount(host, events, opts) {
    const o = Object.assign({}, DEFAULTS, opts || {});
    const spans = (o.spans && o.spans.length) ? o.spans.slice().sort((a, b) => a.t0 - b.t0) : null;
    const filmOf = tr => { if (!spans) return tr; for (const s of spans) { const len = s.t1 - s.t0; if (tr >= s.src && tr < s.src + len) return s.t0 + (tr - s.src); } return null; };
    const pills = buildPills(events || [], o, filmOf);

    const layer = document.createElement('div');
    layer.id = o.id;
    layer.style.cssText = 'position:absolute;left:0;top:0;width:' + o.stage[0] + 'px;height:' + o.stage[1] + 'px;pointer-events:none;z-index:45;overflow:visible';
    layer.setAttribute('data-qa-allow-overlap', '');
    host.appendChild(layer);
    const els = pills.map(function (p, i) {
      const el = document.createElement('div');
      el.className = 'hud-pill hud-' + p.kind;
      el.style.cssText = 'position:absolute;left:50%;bottom:' + o.bottom + 'px;transform:translateX(-50%);opacity:0;display:flex;align-items:center;gap:8px;' +
        'height:36px;padding:0 14px;border-radius:18px;background:' + o.bg + ';color:' + o.fg + ';font:' + o.font + ';white-space:nowrap;' +
        'box-shadow:0 6px 18px rgba(0,0,0,0.28), inset 0 0 0 1px rgba(233,243,249,0.08);letter-spacing:0.01em';
      if (p.kind === 'shortcut') {
        p.caps.forEach(function (c, k) {
          if (k) { const plus = document.createElement('span'); plus.textContent = '+'; plus.style.cssText = 'opacity:0.6'; el.appendChild(plus); }
          const cap = document.createElement('span'); cap.textContent = c;
          cap.style.cssText = 'display:inline-flex;align-items:center;height:26px;padding:0 9px;border-radius:6px;background:' + o.capBg + ';color:' + o.cap + ';box-shadow:inset 0 -2px 0 rgba(0,0,0,0.35)';
          el.appendChild(cap);
        });
      } else {
        const lab = document.createElement('span'); lab.textContent = 'typed'; lab.style.cssText = 'opacity:0.55;font-size:12px;letter-spacing:0.08em;text-transform:uppercase'; el.appendChild(lab);
        const txt = document.createElement('span'); txt.className = 'hud-text'; txt.textContent = ''; el.appendChild(txt);
        const caret = document.createElement('span'); caret.textContent = '|'; caret.style.cssText = 'color:' + o.cap + ';margin-left:-4px'; el.appendChild(caret);
        p.txt = txt;
      }
      layer.appendChild(el);
      p.el = el;
      return el;
    });

    if (root.MOTION && pills.length) {
      root.MOTION.block(o.id + ':pills', function (tl) {
        pills.forEach(function (p) {
          const vis = Math.max(0.02, p.t1 - p.t0);
          const inD = Math.min(o.inDur, vis), outD = Math.min(o.outDur, vis - inD + 0.001);
          tl.fromTo(p.el, { opacity: 0, y: 10, scale: 0.86, xPercent: -50 }, { opacity: 1, y: 0, scale: 1, xPercent: -50, duration: inD, ease: 'back.out(1.6)', immediateRender: false, lazy: false }, Math.max(0, p.t0));
          tl.to(p.el, { opacity: 0, scale: 0.96, xPercent: -50, duration: Math.max(0.02, outD), ease: 'power2.in', lazy: false }, Math.max(0, p.t1 - outD));
        });
      }, { el: layer, start: 0, end: Infinity, hide: false });
    }

    /* pure text state at film time t */
    const lastText = new Map();
    function draw(t) {
      for (const p of pills) {
        if (p.kind !== 'typed') continue;
        let text = '';
        if (t >= p.t0) { let s = p.states[0].text; for (const st of p.states) { if (st.t <= t) s = st.text; else break; } text = s; }
        if (text.length > o.maxChars) text = '…' + text.slice(text.length - o.maxChars + 1);
        if (lastText.get(p) !== text) { p.txt.textContent = text; lastText.set(p, text); }
      }
    }
    let off = null;
    const h = { id: o.id, layer, pills, draw, seek: draw, opts: o, remove() { layer.remove(); if (off) off(); if (root.MOTION) root.MOTION.remove(o.id + ':pills'); } };
    off = onClock(draw);
    draw(0);
    return h;
  }

  root.HUD = { mount, buildPills, DEFAULTS, SPECIAL };
})(typeof window !== 'undefined' ? window : globalThis);
