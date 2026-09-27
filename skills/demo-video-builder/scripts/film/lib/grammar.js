/* grammar.js — cinematic UI-film grammar as pure functions of the film clock t (seconds).
   Shared by every scene. Nothing here touches the DOM except applyCam/placeCursor (idempotent setters).
   Rules: references/cinematic-grammar.md */
window.G = (function () {
  'use strict';
  const clamp = (x, a, b) => Math.max(a, Math.min(b, x));
  const rmp = (t, a, b) => clamp((t - a) / (b - a), 0, 1);
  const lerp = (a, b, x) => a + (b - a) * x;
  const EZ = x => Math.sin(clamp(x, 0, 1) * Math.PI / 2);                  // sine-out (pushes, pulls)
  const EIO = x => 0.5 - 0.5 * Math.cos(clamp(x, 0, 1) * Math.PI);          // sine-in-out (pans, scrolls, cursor)
  const EOQ = x => 1 - Math.pow(1 - clamp(x, 0, 1), 4);                     // odometers / reveals

  /* ---------- camera: keyframes [{t0,dur,s,cx,cy}] ; state holds after each move; s=1 & centre = home ---------- */
  function camState(Q, t, stage = [1280, 720]) {
    let s = 1, cx = stage[0] / 2, cy = stage[1] / 2, ps = s, pcx = cx, pcy = cy;
    for (const m of Q) {
      if (t < m.t0) break;
      const u = (m.ease || EZ)(rmp(t, m.t0, m.t0 + m.dur));
      s = lerp(ps, m.s, u); cx = lerp(pcx, m.cx, u); cy = lerp(pcy, m.cy, u);
      if (t >= m.t0 + m.dur) { ps = m.s; pcx = m.cx; pcy = m.cy; }
    }
    return { s, cx, cy };
  }
  /* drift: +rate/s of scale from tStart while the camera would otherwise be still (2–3 %/s after a cut) */
  function applyCam(el, Q, t, stage = [1280, 720], drift = null) {
    let { s, cx, cy } = camState(Q, t, stage);
    if (drift && t >= drift.t0 && t < drift.t1) s *= 1 + drift.rate * (t - drift.t0);
    if (s < 1.0005) { el.style.transform = 'none'; return { s: 1, cx: stage[0] / 2, cy: stage[1] / 2 }; }
    const hw = stage[0] / 2 / s, hh = stage[1] / 2 / s;
    const ccx = clamp(cx, hw, stage[0] - hw), ccy = clamp(cy, hh, stage[1] - hh);
    el.style.transform = `translate(${(stage[0] / 2 - s * ccx).toFixed(2)}px,${(stage[1] / 2 - s * ccy).toFixed(2)}px) scale(${s.toFixed(4)})`;
    return { s, cx: ccx, cy: ccy };
  }
  /* helper: a push onto a rect [x,y,w,h] at scale s → keyframe centred on the rect */
  const pushTo = (t0, dur, s, rect) => ({ t0, dur, s, cx: rect[0] + rect[2] / 2, cy: rect[1] + rect[3] / 2 });
  const pullHome = (t0, dur = 1.0) => ({ t0, dur, s: 1, cx: 640, cy: 360 });

  /* ---------- typing: word chunks at cps, 0.5 s pause after ". ", 0.15 s after ", " or a line wrap marker "\n" ---------- */
  function typer(text, t0, cps = 70) {
    const toks = text.match(/\S+\s*/g) || [text];
    const sched = []; let t = t0, shown = '';
    for (const tok of toks) {
      const dur = tok.length / cps;
      sched.push({ tEnd: t + dur, text: shown + tok });
      shown += tok; t += dur;
      if (/[.!?]\s*$/.test(tok)) t += 0.5; else if (/[,;:]\s*$/.test(tok)) t += 0.15;
      if (tok.includes('\n')) t += 0.15;
    }
    const tDone = t;
    return {
      tDone,
      at(tt) { if (tt < t0) return ''; for (const s of sched) if (tt < s.tEnd) { /* partial within the chunk */
          const prev = sched[sched.indexOf(s) - 1]; const base = prev ? prev.text : '';
          const tok = s.text.slice(base.length); const tStart = prev ? prev.tEnd : t0;
          const n = Math.floor(clamp((tt - tStart) / (s.tEnd - tStart), 0, 1) * tok.length);
          return base + tok.slice(0, n); }
        return text; },
      caret(tt) { return tt >= t0 - 0.35 && tt < tDone + 0.9; }          // 2 px caret, no blink while typing
    };
  }

  /* ---------- odometer ---------- */
  function odo(from, to, t, t0, dur = 0.7, dec = 0, locale = 'en-US') {
    const u = EOQ(rmp(t, t0, t0 + dur));
    return (from + (to - from) * u).toLocaleString(locale, { minimumFractionDigits: dec, maximumFractionDigits: dec });
  }

  /* ---------- working state: plan lines replace every period s (6 px slide + shimmer handled by CSS class) ---------- */
  function planLine(lines, t, t0, period = 1.6) {
    if (t < t0) return { idx: -1, u: 0 };
    const k = Math.min(lines.length - 1, Math.floor((t - t0) / period));
    return { idx: k, u: rmp(t, t0 + k * period, t0 + k * period + 0.35) };
  }
  const timer = (t, t0, compressTo, from = 0) => {          // "1m 18s" style chip; compressTo seconds of real time shown over the wait
    const el = Math.max(0, t - t0) * (compressTo / 3.5);
    const s = Math.floor(from + el); return `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, '0')}s`;
  };

  /* ---------- staged prose: bold finding first, paragraph +0.5 s; returns opacities ---------- */
  const staged = (t, t0) => ({ head: rmp(t, t0, t0 + 0.3), body: rmp(t, t0 + 0.5, t0 + 0.9) });

  /* ---------- cursor: waypoints [{t0, x, y, dur?, hand?, click?}] → position + state (sine-in-out moves, parks) ---------- */
  function cursorAt(W, t) {
    if (!W.length || t < W[0].t0 - 0.01) return null;
    let cur = W[0], nxt = null;
    for (let i = 0; i < W.length; i++) { if (t >= W[i].t0) cur = W[i]; else { nxt = W[i]; break; } }
    let x = cur.x, y = cur.y;
    if (nxt) { const d = nxt.dur || 0.55; const u = EIO(rmp(t, nxt.t0 - d, nxt.t0)); x = lerp(cur.x, nxt.x, u); y = lerp(cur.y, nxt.y, u); }
    const clicking = cur.click && t >= cur.t0 && t < cur.t0 + 0.12;
    return { x, y, hand: !!(cur.hand), clicking, visible: !(cur.hide) };
  }
  const CURSOR_ARROW = '<svg viewBox="0 0 24 24"><path d="M5 3l14 8.5-6.2 1.4L9.6 19z" fill="#111" stroke="#fff" stroke-width="1.6" stroke-linejoin="round"/></svg>';
  const CURSOR_HAND = '<svg viewBox="0 0 24 24"><path d="M9 11V4.5a1.5 1.5 0 013 0V10 M12 10V3.5a1.5 1.5 0 013 0V10 M15 10V5a1.5 1.5 0 013 0v8.5a6.5 6.5 0 01-6.5 6.5H10a6 6 0 01-5-2.7L3.2 14.5A1.4 1.4 0 015.4 13l1.6 1.7V7.5a1.5 1.5 0 013 0V11" fill="#fff" stroke="#111" stroke-width="1.4" stroke-linejoin="round" stroke-linecap="round"/></svg>';
  function placeCursor(el, st) {
    if (!st || !st.visible) { el.style.opacity = 0; return; }
    el.style.opacity = 1; el.style.left = st.x + 'px'; el.style.top = st.y + 'px';
    const want = st.hand ? 'hand' : 'arrow';
    if (el.dataset.k !== want) { el.dataset.k = want; el.innerHTML = want === 'hand' ? CURSOR_HAND : CURSOR_ARROW; }
  }

  /* ---------- chapter card / dissolve helpers ---------- */
  const fadeInOut = (t, a, b, fi = 0.25, fo = 0.25) => Math.min(rmp(t, a, a + fi), 1 - rmp(t, b - fo, b));
  const words = (s, t, t0, step = 0.1, fade = 0.3) => s.split(' ').map((w, i) => `<span style="opacity:${rmp(t, t0 + i * step, t0 + i * step + fade).toFixed(3)}">${w}</span>`).join(' ');

  return { clamp, rmp, lerp, EZ, EIO, EOQ, camState, applyCam, pushTo, pullHome, typer, odo, planLine, timer, staged, cursorAt, placeCursor, fadeInOut, words };
})();
