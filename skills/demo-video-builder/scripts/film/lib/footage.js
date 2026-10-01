/* footage.js — the real-footage lane of a clock-driven film. Every pixel shown comes from the recording
   (extracted by extract_clips.py); this module only places, scrolls, uncovers and frames it.

   Clip kinds (window.CLIPS, written by extract_clips.py):
     still  one frame (or the per-pixel median of a window, which erases a wandering pointer)
     seq    real 30 fps motion: f_001.jpg … played on the film clock (play.at / from / rate / loop)
     page   a tall document stitched from the recording's parked scroll positions, scrolled for real;
            with `chrome`, drawn inside the app's own full screen (one chrome frame per parked position)

   Shot fields (window.SHOTS, see shots.example.js):
     t0 / t1 / clip        when, and which clip
     s0 / c0 / moves       camera: scale + centre on the 1280x720 stage; moves [{t0,dur,s,c,ease:'io'}]
     establish             {hold, dur}: open on the ORIGINAL full screen, hold, then push into s0/c0
     moves[].abs           true = coordinates already on the full screen (pull back: {s:1, c:[640,360], abs:true})
     y0 / scroll           page scroll (doc px): [{t0,dur,y}] eased like a browser (1-(1-u)^3)
     play                  seq timing {at, from, rate, loop:[a,b]}
     reveal                typed text uncovered word by word on the narration clock (see REVEAL)
     stream                a curtain that streams an answer in top-down {t0,dur,from,to,bg}
     seam                  a seamless hand-off (not counted as a cut by QA)

   FOOT.fullscreen(SHOTS, VIEW) maps an edit written in cropped views to full-screen coordinates, so a
   beat can open on the real screen and push into exactly the framing you designed. */
(function (root) {
  'use strict';
  const G = root.G, clamp = G.clamp, rmp = G.rmp, lerp = G.lerp, EZ = G.EZ, EIO = G.EIO;

  /* ---------- uncover already-typed glyphs word by word as they are spoken ---------- */
  const REVEAL = {
    points(r, T) {
      const L = r.lines[0], W = T.WORDS[r.sync], base = T.P[r.sync], pts = [];
      let prev = L[0];
      r.ends.forEach(function (e, i) {
        const wi = W[Math.min(i, W.length - 1)], ti = base + wi.t, nx = W[i + 1] ? base + W[i + 1].t : ti + 0.4;   // tolerate token-count drift
        pts.push([ti - (r.lead || 0.05), prev], [ti + Math.min(0.30, nx - ti), e]);
        prev = e;
      });
      const last = pts[pts.length - 1];
      pts.push([last[0] + (L[2] - prev) / (r.tailPxs || 300), L[2]]);
      return pts;
    },
    total(r) { return r.lines.reduce((a, L) => a + (L[2] - L[0]), 0); },
    progress(r, T, t) {
      const pts = REVEAL.points(r, T);
      if (t <= pts[0][0]) return 0;
      for (let i = 1; i < pts.length; i++) {
        if (t <= pts[i][0]) { const a = pts[i - 1], b = pts[i], u = (t - a[0]) / Math.max(1e-6, b[0] - a[0]); return (a[1] + (b[1] - a[1]) * u) - r.lines[0][0]; }
      }
      return REVEAL.total(r);
    },
    end(r, T) { const p = REVEAL.points(r, T); return p[p.length - 1][0]; },
    first(r, T) { return REVEAL.points(r, T)[0][0]; }
  };

  /* ---------- cropped-view edit → full-screen coordinates (+ establishing push) ---------- */
  // VIEW[clip] = [x, y, w] of the source rect the edit was designed in (page band, or old crop).
  function fullscreen(SHOTS, VIEW, frameW) {
    const W = frameW || 1920, K = 1280 / W;
    const clampC = (s, c) => { const hw = 640 / s, hh = 360 / s;
      return s < 1.0005 ? [640, 360] : [clamp(c[0], hw, 1280 - hw), clamp(c[1], hh, 720 - hh)]; };
    SHOTS.forEach(function (sh) {
      const R = VIEW[sh.clip] || [0, 0, W], f = R[2] / W;
      const conv = (s, c) => { const cc = clampC(s, c); return { s: s / f, c: [R[0] * K + cc[0] * f, R[1] * K + cc[1] * f] }; };
      const a = conv(sh.s0 || 1, sh.c0 || [640, 360]);
      // a move with abs:true is already in full-screen stage coords (e.g. pull back to the whole screen: s 1, c [640,360])
      sh.moves = (sh.moves || []).map(m => { if (m.abs) return m; const b = conv(m.s, m.c); return Object.assign({}, m, { s: b.s, c: b.c }); });
      if (sh.establish) {                                 // the original screen first, then the zoom
        sh.moves.unshift({ t0: sh.t0 + sh.establish.hold, dur: sh.establish.dur, s: a.s, c: a.c, ease: 'io' });
        sh.s0 = 1; sh.c0 = [640, 360];
      } else { sh.s0 = a.s; sh.c0 = a.c; }
    });
    return SHOTS;
  }

  /* ---------- the lane ---------- */
  function create(o) {
    // o: {T (timeline: P, WORDS, wt), CL (clips), HL (highlights), base ('../broll/'), els: {wrap, img, reveal,
    //     stillHl, stillCurtain, pageView, pageDoc, pageImg, pageHl, pageCurtain}}
    const T = o.T, CL = o.CL, HL = o.HL || {}, base = o.base || '../broll/', E = o.els;
    let clipName = null, revealKey = null, pending = [];
    const id = s => document.getElementById(s);
    const op = (e, v) => { if (e) e.style.opacity = clamp(v, 0, 1).toFixed(3); };
    const kOf = n => 1280 / (CL[n].kind === 'page' ? (CL[n].chrome ? 1920 : CL[n].band[2]) : CL[n].crop[2]);
    function setSrc(img, src) { if (img.getAttribute('src') === src) return; img.setAttribute('src', src); pending.push(img.decode().catch(() => {})); }

    function hlHTML(name, docMode) {
      const k = kOf(name), c = CL[name];
      return (HL[name] || []).map(function (h) {
        const x = (docMode ? h.r[0] : h.r[0] - c.crop[0]) * k, y = (docMode ? h.r[1] : h.r[1] - c.crop[1]) * k;
        const st = 'left:' + x.toFixed(1) + 'px;top:' + y.toFixed(1) + 'px;' + (h.kind === 'tag' ? '' : 'width:' + (h.r[2] * k).toFixed(1) + 'px;height:' + (h.r[3] * k).toFixed(1) + 'px;');
        return '<div class="hl ' + h.kind + '" id="hl_' + h.id + '" style="' + st + '">' + (h.kind === 'tag' ? h.label : '') + '</div>';
      }).join('');
    }
    function useClip(name) {
      if (clipName === name) return;
      const c = CL[name], k = kOf(name);
      E.stillHl.innerHTML = ''; E.pageHl.innerHTML = '';
      E.wrap.style.background = c.bg || '#fff';
      if (c.kind === 'page') {
        E.img.style.display = c.chrome ? 'block' : 'none';
        const pv = E.pageView.style; pv.display = 'block';
        if (c.chrome) { const b = c.band; pv.left = (b[0] * k) + 'px'; pv.top = (b[1] * k) + 'px'; pv.width = (b[2] * k) + 'px'; pv.height = (b[3] * k) + 'px'; pv.background = c.bg || '#fff'; }
        else { pv.left = '0px'; pv.top = '0px'; pv.width = '1280px'; pv.height = '720px'; pv.background = 'transparent'; }
        E.pageDoc.style.width = (c.w * k) + 'px'; E.pageImg.style.width = (c.w * k) + 'px';
        E.pageDoc.style.height = (c.h * k) + 'px'; E.pageImg.style.height = (c.h * k) + 'px';
        setSrc(E.pageImg, base + name + '/page.jpg');
        E.pageHl.innerHTML = hlHTML(name, true);
      } else {
        E.pageView.style.display = 'none'; E.img.style.display = 'block';
        E.stillHl.innerHTML = hlHTML(name, false);
      }
      clipName = name;
    }
    function seqFrame(sh, t) {
      const c = CL[sh.clip], n = c.frames, from = (sh.play && sh.play.from) || 1;
      if (sh.play && sh.play.map) return 1 + Math.floor(clamp(sh.play.map(t), 0, 1) * (n - 1) + 1e-6);   // speed ramp: map(t) → 0..1 of the clip
      const at = sh.play ? sh.play.at : sh.t0, rate = (sh.play && sh.play.rate) || 1, dt = Math.max(0, t - at);
      // rate may be a number or a speed-ramp lane [[t, rate], …] (lib/vfx.js VFX.ramp — trapezoid integral of the lane)
      let f = (Array.isArray(rate) && root.VFX && root.VFX.ramp) ? root.VFX.ramp.frameAt(rate, dt, c.fps, n, from) : from + Math.floor(dt * c.fps * (Array.isArray(rate) ? 1 : rate) + 1e-6);
      if (f > n) {
        if (sh.play && sh.play.loop) { const a = sh.play.loop[0] + 1, b = sh.play.loop[1] + 1; f = a + ((f - n - 1) % (b - a + 1)); }
        else f = n;
      }
      return f;
    }
    function scrollY(sh, t) {
      let y = sh.y0 || 0;
      for (const k of (sh.scroll || [])) { const u = 1 - Math.pow(1 - clamp((t - k.t0) / k.dur, 0, 1), 3); y = lerp(y, k.y, u); }
      return y;
    }
    function curtain(el, sh, t, k) {
      const s = sh.stream;
      if (!s) { el.style.display = 'none'; return; }
      const u = EZ(rmp(t, s.t0, s.t0 + s.dur)), line = lerp(s.from, s.to, u), gone = rmp(t, s.t0 + s.dur, s.t0 + s.dur + 0.25);
      if (gone >= 1) { el.style.display = 'none'; return; }
      el.style.display = 'block';
      el.style.background = 'linear-gradient(to bottom,rgba(255,255,255,0) 0,' + (s.bg || '#fff') + ' 26px,' + (s.bg || '#fff') + ' 100%)';
      el.style.top = (line * k - 26).toFixed(1) + 'px'; el.style.height = '2600px'; el.style.opacity = (1 - gone).toFixed(3);
    }
    function drawReveal(sh, t) {
      const r = sh && sh.reveal;
      if (!r) { if (revealKey) { E.reveal.innerHTML = ''; revealKey = null; } return; }
      const c = CL[sh.clip], k = kOf(sh.clip), ox = c.crop[0], oy = c.crop[1], key = sh.clip + '@' + sh.t0;
      if (revealKey !== key) {
        E.reveal.innerHTML = r.lines.map((L, i) => '<div class="rv-plate" id="rvp' + i + '" style="background:' + (r.bg || '#fff') + '"></div>').join('') + '<div class="rv-caret" id="rvc"></div>';
        revealKey = key;
      }
      const done = REVEAL.end(r, T), first = REVEAL.first(r, T);
      let left = REVEAL.progress(r, T, t), cur = -1, cx = 0, cyTop = 0, cyH = 0;
      r.lines.forEach(function (L, i) {
        const w = L[2] - L[0], e = id('rvp' + i); let x0 = L[0];
        if (left >= w) { left -= w; e.style.display = 'none'; return; }
        if (cur < 0) { cur = i; x0 = L[0] + left; cx = x0; cyTop = L[1]; cyH = L[3] - L[1]; left = 0; }
        e.style.display = 'block';
        e.style.left = ((x0 - ox) * k).toFixed(1) + 'px'; e.style.top = ((L[1] - oy) * k).toFixed(1) + 'px';
        e.style.width = ((L[2] - x0 + 2) * k).toFixed(1) + 'px'; e.style.height = ((L[3] - L[1]) * k).toFixed(1) + 'px';
      });
      const caret = id('rvc');
      if (t >= done || cur < 0) { caret.style.display = 'none'; return; }
      caret.style.display = (t < first ? (Math.floor((t - sh.t0) * 2) % 2 === 0) : true) ? 'block' : 'none';
      caret.style.left = ((cx - ox) * k).toFixed(1) + 'px'; caret.style.top = ((cyTop + 3 - oy) * k).toFixed(1) + 'px';
      caret.style.height = ((cyH - 5) * k).toFixed(1) + 'px'; caret.style.background = r.caret || '#1C1815';
    }
    function drawHighlights(t, name) {
      (HL[name] || []).forEach(function (h) {
        const e = id('hl_' + h.id); if (!e) return;
        const a = T.wt(h.cue[0], h.cue[1], h.cue[2]) + (h.dt || 0);
        const out = h.until ? 1 - rmp(t, T.wt(h.until[0], h.until[1]), T.wt(h.until[0], h.until[1]) + 0.3) : 1;
        op(e, rmp(t, a, a + 0.32) * out);
      });
    }
    function camFor(sh, t) {
      let s = sh.s0 || 1, cx = (sh.c0 || [640, 360])[0], cy = (sh.c0 || [640, 360])[1];
      for (const m of (sh.moves || [])) { const u = (m.ease === 'io' ? EIO : EZ)(rmp(t, m.t0, m.t0 + m.dur)); s = lerp(s, m.s, u); cx = lerp(cx, m.c[0], u); cy = lerp(cy, m.c[1], u); }
      if (sh.drift) s += (t - sh.t0) * sh.drift;
      return { s: s, cx: cx, cy: cy };
    }

    /* draw one shot at film time t → camera state {s,cx,cy}; returns decode promises in .pending */
    function draw(sh, t) {
      pending = [];
      useClip(sh.clip); op(E.wrap, 1);
      const c = CL[sh.clip], k = kOf(sh.clip);
      if (c.kind === 'seq') setSrc(E.img, base + sh.clip + '/f_' + String(seqFrame(sh, t)).padStart(3, '0') + '.jpg');
      else if (c.kind === 'still') setSrc(E.img, base + sh.clip + '/f_001.jpg');
      if (c.kind === 'page') {
        const y = scrollY(sh, t);
        if (c.chrome) { let i = 0; c.offsets.forEach((o2, j) => { if (o2 <= y + 40) i = j; }); setSrc(E.img, base + sh.clip + '/chrome_' + i + '.jpg'); }
        E.pageDoc.style.transform = 'translateY(' + (-y * k).toFixed(2) + 'px)';
        curtain(E.pageCurtain, sh, t, k); E.stillCurtain.style.display = 'none';
      } else { curtain(E.stillCurtain, sh, t, k); E.pageCurtain.style.display = 'none'; }
      drawReveal(sh, t);
      drawHighlights(t, sh.clip);
      const cam = camFor(sh, t); cam.pending = pending; return cam;
    }
    function hide() { op(E.wrap, 0); drawReveal(null, 0); }
    function reset() { clipName = null; revealKey = null; E.reveal.innerHTML = ''; }
    function shotAt(SH, t) { let cur = null; for (const s of SH) { if (t >= s.t0 && t < (s.t1 === undefined ? 1e9 : s.t1)) cur = s; else if (t < s.t0) break; } return cur; }
    return { draw, hide, reset, shotAt, scrollY };
  }

  root.FOOT = { create, fullscreen, REVEAL };
})(typeof window !== 'undefined' ? window : globalThis);
