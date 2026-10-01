/* overlays.js — graphic overlays on the finished frame (window.OVL): lower thirds, data callouts / stat
   cards, pull-quotes, the hairline viewfinder / PiP frame for a real screen inside a recreated scene, and the
   promoted hero word with the yield rule. Pure functions of the film clock t plus a spec object; the DOM for
   each spec is built ONCE (keyed by spec.id) inside the host you pass, then only opacity / transform /
   clip-path change per frame (never letter-spacing, size, weight or blur — those reflow or shimmer).

   Overlay law: overlays live in SCREEN SPACE, outside #camera, so a camera push can never move them out of
   title-safe. Every element carries data-ov="lt|callout|quote|hero|pip" so gates/overlay_gate.py can
   measure it; add data-ov-bleed="1" to a deliberate edge-kiss to opt out of the safe-zone check.

   Usage (scene):   <div id="ovl"></div>   (absolute, inset 0, z above footage, below #black)
     const lt = OVL.lowerThird($('#ovl'), t, { id:'lt-nb', t0: P.nb, dur: 4.8, label:'THE ANALYST',
                                               text:'Build it where the data is.', variant:'cardless' });
     lane.draw($('#cap'), t, { avoid: lt.visible ? [lt.rect] : [] });          // the lane lifts above a lower third
     OVL.callout($('#ovl'), t, { id:'c1', t0: wt('nb','counts'), dur: 4, zone:'lower-right', kicker:'LATE DELIVERIES',
                                 value:{ from: 0, to: 23, dec: 0 }, detail:'last week · 3 regions', style:'swiss' });
     OVL.hero($('#ovl'), t, { id:'h1', t0: wt('answer','governed') - 0.08, dur: 2.4, text:'governed', style:'keynote' });

   All tokens are measured at 1920x1080 and scaled by stage height (1280x720 stage → ×0.667).
   Doctrine + the measured table: references/captions-and-overlays.md. Everything here is fictional (Acme). */
(function (root) {
  'use strict';
  const G = root.G || {};
  const clamp = (x, a, b) => Math.max(a, Math.min(b, x));
  const rmp = (t, a, b) => (b <= a ? (t >= b ? 1 : 0) : clamp((t - a) / (b - a), 0, 1));
  const lerp = (a, b, x) => a + (b - a) * x;
  const EO2 = u => 1 - Math.pow(1 - clamp(u, 0, 1), 2);          // power2-out
  const EO3 = u => 1 - Math.pow(1 - clamp(u, 0, 1), 3);          // power3-out
  const EO4 = u => 1 - Math.pow(1 - clamp(u, 0, 1), 4);          // power4-out
  const EI2 = u => { u = clamp(u, 0, 1); return u * u; };        // power2-in
  const EIO = u => 0.5 - 0.5 * Math.cos(clamp(u, 0, 1) * Math.PI);
  const BACK = u => { u = clamp(u, 0, 1); const s = 1.6; return 1 + (s + 1) * Math.pow(u - 1, 3) + s * Math.pow(u - 1, 2); };  // back-out(1.6)
  const esc = s => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  const norm = s => String(s).toLowerCase().replace(/[^a-z0-9]/g, '');
  const SANS = "'Segoe UI','Helvetica Neue',Arial,sans-serif", MONO = "Consolas,'Courier New',monospace", SERIF = "Georgia,'Times New Roman',serif";   // single quotes: safe inside style="…"
  const STAGE = [1280, 720];
  const K = () => STAGE[1] / 1080;                                 // 1080-measured px → stage px
  const px = v => (v * K()).toFixed(2) + 'px';
  const odo = G.odo || function (from, to, t, t0, dur, dec) { const u = EO4(rmp(t, t0, t0 + dur)); return (from + (to - from) * u).toLocaleString('en-US', { minimumFractionDigits: dec || 0, maximumFractionDigits: dec || 0 }); };

  /* ---------- registry: every spec drawn (or declared) is listed for the QA gate: OVL.windows() ---------- */
  const REG = new Map();
  const reg = (kind, s) => { const id = s.id || kind + '-' + (+s.t0).toFixed(2); if (!REG.has(id)) REG.set(id, { kind: kind, id: id, t0: s.t0, t1: s.t0 + (s.dur || 0), text: s.text || s.kicker || '' }); return id; };
  const windows = () => Array.from(REG.values()).sort((a, b) => a.t0 - b.t0);
  const declare = list => list.forEach(s => reg(s.kind || 'lt', s));

  /* ---------- DOM: one child per spec id inside the host; hidden outside its window ---------- */
  function ensure(host, id, kind, build) {
    host.__ov = host.__ov || {};
    if (host.__ov[id]) return host.__ov[id];
    if (!host.__ovInit) { host.__ovInit = true; host.style.pointerEvents = 'none'; }
    const el = document.createElement('div');
    el.setAttribute('data-ov', kind); el.setAttribute('data-ovid', id);
    el.style.position = 'absolute'; el.style.visibility = 'hidden'; el.style.opacity = '0';
    build(el); host.appendChild(el); host.__ov[id] = el; return el;
  }
  const hide = el => { el.style.visibility = 'hidden'; el.style.opacity = '0'; };
  const show = el => { el.style.visibility = 'visible'; };
  const rectOf = el => { const r = el.getBoundingClientRect(); return [r.left, r.top, r.width, r.height]; };
  function fitPx(text, font, maxW, base, min, step) {              // shrink-to-fit via CAP.fitText (canvas in the browser)
    if (root.CAP && root.CAP.fitText) return root.CAP.fitText(text, { font: font, maxWidth: maxW, base: base, min: min, step: step || 2, mode: typeof document !== 'undefined' ? 'canvas' : 'estimate' }).px;
    return base;
  }

  /* ================================================================== lower third ==================
     spec: { id, t0, dur: 4.8, label: 'THE ANALYST', text: 'Build it where the data is.', variant: 'card'|'cardless'|'dark',
             accent: '#E56B5E', side: 'left'|'right', left: 120, bottom: 116 }   (left/bottom in 1080 px)
     card: clip-path inset(0 100% 0 0) → 0 over 0.55 s power3-out at +0.10, accent tab scaleY 0.45 s at +0.28,
           line y22 → 0 0.5 s at +0.34, label at +0.44; exit y+18 + opacity 0 over 0.35 s power2-in, then hidden.
     cardless: line y28 → 0 0.55 s power3-out at +0.10, 6 px rule scaleX 0 → 1 0.5 s power4-out at +0.30, label y16 → 0 at +0.46;
           exit label 0.3 s, rule retracts 0.3 s, line lifts −16 px 0.32 s; text-shadow for legibility over footage.
     dark: the card recipe on charcoal #16181d radius 14 — pick it when the footage under it is bright or busy.
     Returns { visible, rect:[x,y,w,h] (stage px, for the lane's avoid list), el }. Give it ≥ 4.8 s so the exit plays. */
  /* variant 'auto': charcoal card when the probed lane luma of the phase is bright (> 150), cardless otherwise.
     Reads window.CAPTIONS.luma[spec.phase] (node lib/captions.js … --luma out/caption_luma.json) or spec.luma (a mean 0-255). */
  function autoVariant(s) {
    const L = s.luma !== undefined ? s.luma : (root.CAPTIONS && root.CAPTIONS.luma && s.phase && root.CAPTIONS.luma[s.phase] ? root.CAPTIONS.luma[s.phase].mean : null);
    return L === null ? 'cardless' : (L > 150 ? 'dark' : 'cardless');
  }
  function lowerThird(host, t, s) {
    const id = reg('lt', s), dur = s.dur || 4.8, v = (s.variant || 'cardless') === 'auto' ? autoVariant(s) : (s.variant || 'cardless'), accent = s.accent || '#E56B5E';
    const el = ensure(host, id, 'lt', el => {
      const left = s.left !== undefined ? s.left : (v === 'cardless' ? 130 : 120), bottom = s.bottom !== undefined ? s.bottom : (v === 'cardless' ? 120 : 110);
      el.style[s.side === 'right' ? 'right' : 'left'] = px(left); el.style.bottom = px(bottom); el.style.fontFamily = SANS;
      const maxW = 0.62 * STAGE[0];
      if (v === 'cardless') {
        const fs = fitPx(s.text, '700 ' + Math.round(60 * K()) + 'px ' + SANS, maxW, Math.round(60 * K()), Math.round(36 * K()));
        el.innerHTML = '<div class="lt-line" style="font:700 ' + fs + 'px/1.02 ' + SANS + ';color:#fff;letter-spacing:-0.01em;white-space:nowrap;text-shadow:0 ' + px(2) + ' ' + px(22) + ' rgba(0,0,0,.45)">' + esc(s.text) + '</div>' +
          '<div class="lt-rule" style="height:' + px(6) + ';width:100%;background:' + esc(accent) + ';border-radius:' + px(3) + ';margin:' + px(14) + ' 0;transform-origin:0 50%"></div>' +
          '<div class="lt-label" style="font:400 ' + px(28) + '/1.2 ' + SANS + ';color:#e7eaf0;letter-spacing:0.04em;text-transform:uppercase;white-space:nowrap;text-shadow:0 ' + px(2) + ' ' + px(16) + ' rgba(0,0,0,.45)">' + esc(s.label || '') + '</div>';
      } else {
        const dark = v === 'dark', bg = dark ? '#16181d' : '#ffffff', ink = dark ? '#f2f3f5' : '#0f1115', sub = dark ? '#aeb4c0' : '#5a6170';
        const fs = fitPx(s.text, '700 ' + Math.round(52 * K()) + 'px ' + SANS, maxW, Math.round(52 * K()), Math.round(34 * K()));
        el.style.display = 'flex'; el.style.alignItems = 'stretch'; el.style.borderRadius = px(14); el.style.overflow = 'hidden';
        el.style.boxShadow = '0 ' + px(14) + ' ' + px(44) + ' rgba(15,17,21,.18)';
        el.innerHTML = '<div class="lt-tab" style="width:' + px(12) + ';background:' + esc(accent) + ';flex-shrink:0;transform-origin:50% 0"></div>' +
          '<div class="lt-body" style="background:' + bg + ';padding:' + px(22) + ' ' + px(40) + ' ' + px(24) + ' ' + px(30) + ';display:flex;flex-direction:column;gap:' + px(7) + '">' +
          '<div class="lt-label" style="font:600 ' + px(20) + '/1.2 ' + SANS + ';color:' + esc(accent) + ';letter-spacing:0.16em;text-transform:uppercase;white-space:nowrap">' + esc(s.label || '') + '</div>' +
          '<div class="lt-line" style="font:700 ' + fs + 'px/1.06 ' + SANS + ';color:' + ink + ';letter-spacing:-0.015em;white-space:nowrap">' + esc(s.text) + '</div>' +
          '<div class="lt-sub" style="display:none;color:' + sub + '"></div></div>';
      }
    });
    const u = t - s.t0;
    if (u < 0 || u >= dur - 0.05) { hide(el); return { visible: false, rect: null, el: el }; }
    show(el);
    const line = el.querySelector('.lt-line'), label = el.querySelector('.lt-label'), rule = el.querySelector('.lt-rule'), tab = el.querySelector('.lt-tab');
    if (v === 'cardless') {
      const a = EO3(rmp(u, 0.10, 0.65)), b = EO4(rmp(u, 0.30, 0.80)), c = EO3(rmp(u, 0.46, 0.96));
      const xl = EI2(rmp(u, dur - 0.55, dur - 0.25)), xr = EI2(rmp(u, dur - 0.50, dur - 0.20)), xn = EI2(rmp(u, dur - 0.45, dur - 0.13));
      line.style.opacity = (a * (1 - xn)).toFixed(3); line.style.transform = 'translateY(' + ((1 - a) * 28 * K() - xn * 16 * K()).toFixed(2) + 'px)';
      rule.style.transform = 'scaleX(' + (b * (1 - xr)).toFixed(4) + ')';
      label.style.opacity = (c * (1 - xl)).toFixed(3); label.style.transform = 'translateY(' + ((1 - c) * 16 * K()).toFixed(2) + 'px)';
      el.style.opacity = '1'; el.style.transform = 'none';
    } else {
      const wipe = EO3(rmp(u, 0.10, 0.65)), tb = EO2(rmp(u, 0.28, 0.73)), a = EO3(rmp(u, 0.34, 0.84)), b = EO3(rmp(u, 0.44, 0.94));
      const x = EI2(rmp(u, dur - 0.50, dur - 0.15));
      el.style.clipPath = 'inset(0 ' + ((1 - wipe) * 100).toFixed(2) + '% 0 0)';
      tab.style.transform = 'scaleY(' + tb.toFixed(4) + ')';
      line.style.opacity = a.toFixed(3); line.style.transform = 'translateY(' + ((1 - a) * 22 * K()).toFixed(2) + 'px)';
      label.style.opacity = b.toFixed(3); label.style.transform = 'translateY(' + ((1 - b) * 22 * K()).toFixed(2) + 'px)';
      el.style.opacity = (1 - x).toFixed(3); el.style.transform = 'translateY(' + (x * 18 * K()).toFixed(2) + 'px)';
    }
    return { visible: true, rect: rectOf(el), el: el };
  }

  /* ================================================================== data callout / stat card ==============
     spec: { id, t0, dur, zone: 'lower-right'|'lower-left'|'side-panel'|'glass', kicker, value: {from, to, dec, prefix, suffix},
             detail, accent, style: 'swiss'|'minimal'|'terminal'|'glass', width (1080 px, default 520) }
     card fade 0.4 s power2-out + y12 rise; kicker +0.05; odometer G.odo(from, to, t, t0+0.3, 0.7, dec); rule grow-x 0.5 s
     power3-out at +0.65; detail at +1.05; exit 0.35 s power2-in from t0+dur−0.35. A callout RESTATES a figure that is
     visible on the real screen (claims.json) — it never introduces one, and never sits on the product's own text. */
  const CARD = {
    swiss:    { bg: '#ffffff', ink: '#111111', sub: '#444444', accent: '#B23A2E', font: SANS, radius: 0, top: 4, bottom: 1, shadow: '0 18px 50px -18px rgba(0,0,0,.35)' },
    minimal:  { bg: '#ffffff', ink: '#000000', sub: '#555555', accent: '#000000', font: SANS, radius: 6, top: 0, bottom: 1, shadow: '0 18px 50px -18px rgba(0,0,0,.30)' },
    terminal: { bg: '#0d1117', ink: '#c9d1d9', sub: '#8b949e', accent: '#3fb950', kicker: '#d29922', font: MONO, radius: 10, top: 0, bottom: 1, shadow: '0 18px 50px -18px rgba(0,0,0,.6)' },
    glass:    { bg: 'rgba(15,16,22,.82)', ink: '#ffffff', sub: '#c9cdd6', accent: '#E8C874', font: SANS, radius: 18, top: 0, bottom: 1, shadow: '0 30px 80px -20px rgba(0,0,0,.45)' }
  };
  function callout(host, t, s) {
    const id = reg('callout', s), dur = s.dur || 4.0, st = CARD[s.style] || CARD[s.zone === 'glass' ? 'glass' : 'swiss'];
    const accent = s.accent || st.accent, kcol = st.kicker || accent, w = s.width || (s.zone === 'side-panel' ? 1920 * 0.42 - 2 * 64 : s.zone === 'glass' ? 660 : 520);
    const el = ensure(host, id, 'callout', el => {
      el.style.width = px(w); el.style.boxSizing = 'border-box'; el.style.fontFamily = st.font; el.style.background = st.bg; el.style.color = st.ink;
      el.style.borderRadius = px(st.radius); el.style.boxShadow = st.shadow; el.style.padding = px(34) + ' ' + px(40) + ' ' + px(30);
      if (st.top) el.style.borderTop = px(st.top) + ' solid ' + accent;
      if (s.zone === 'side-panel') { el.style.right = px(64); el.style.top = px(64); el.style.minHeight = px(1080 - 128); }
      else if (s.zone === 'glass') { el.style.left = px(48); el.style.top = px(460); }
      else if (s.zone === 'lower-left') { el.style.left = px(120); el.style.bottom = px(116); }
      else { el.style.right = px(120); el.style.bottom = px(116); }
      const val = s.value || {}, dec = val.dec || 0;
      el.innerHTML = '<div class="co-k" style="font:600 ' + px(16) + '/1.2 ' + st.font + ';letter-spacing:0.28em;text-transform:uppercase;color:' + esc(kcol) + '">' + esc(s.kicker || '') + '</div>' +
        '<div class="co-v" style="font:800 ' + px(60) + '/1.05 ' + st.font + ';letter-spacing:-0.025em;margin-top:' + px(10) + ';font-variant-numeric:tabular-nums;color:' + (s.style === 'terminal' ? esc(accent) : st.ink) + '">' +
          esc(val.prefix || '') + '<span class="co-n">' + esc(odo(val.from || 0, val.to || 0, 1e9, 0, 1, dec)) + '</span>' + esc(val.suffix || '') + '</div>' +
        '<div class="co-r" style="height:' + px(3) + ';width:100%;background:' + esc(accent) + ';margin:' + px(16) + ' 0 ' + px(14) + ';transform-origin:0 50%"></div>' +
        '<div class="co-d" style="font:400 ' + px(26) + '/1.3 ' + st.font + ';color:' + st.sub + '">' + esc(s.detail || '') + '</div>' +
        (st.bottom ? '<div style="height:' + px(st.bottom) + ';background:' + (s.style === 'terminal' || s.style === 'glass' ? 'rgba(255,255,255,.18)' : st.ink) + ';margin-top:' + px(22) + '"></div>' : '');
    });
    const u = t - s.t0;
    if (u < 0 || u >= dur) { hide(el); return { visible: false, rect: null, el: el }; }
    show(el);
    const a = EO2(rmp(u, 0, 0.4)), x = EI2(rmp(u, dur - 0.35, dur));
    el.style.opacity = (a * (1 - x)).toFixed(3); el.style.transform = 'translateY(' + ((1 - a) * 12 * K()).toFixed(2) + 'px)';
    el.querySelector('.co-k').style.opacity = EO2(rmp(u, 0.05, 0.45)).toFixed(3);
    const val = s.value || {};
    el.querySelector('.co-n').textContent = odo(val.from || 0, val.to || 0, t, s.t0 + 0.3, 0.7, val.dec || 0);
    el.querySelector('.co-v').style.opacity = EO2(rmp(u, 0.25, 0.55)).toFixed(3);
    el.querySelector('.co-r').style.transform = 'scaleX(' + EO3(rmp(u, 0.65, 1.15)).toFixed(4) + ')';
    el.querySelector('.co-d').style.opacity = EO2(rmp(u, 1.05, 1.45)).toFixed(3);
    return { visible: true, rect: rectOf(el), el: el };
  }

  /* ================================================================== pull-quote card ==================
     spec: { id, t0, dur, kicker, lines: ['…'], attribution, style: 'editorial'|'minimal', zone: 'center'|'lower-left', width }
     reveal: kicker → quote words (step 0.1 s, fade 0.3 s) → rule grow-x → attribution; exit 0.35 s power2-in.
     Italic is allowed here only because it is a literal quotation (verbatim from the narration or the screen). */
  function quote(host, t, s) {
    const id = reg('quote', s), dur = s.dur || 5.0, ed = (s.style || 'editorial') === 'editorial';
    const bg = ed ? '#f1e8d5' : '#ffffff', ink = ed ? '#0e1018' : '#111111', accent = s.accent || (ed ? '#E56B5E' : '#111111');
    const w = s.width || 880, words = (s.lines || []).join(' ').split(/\s+/).filter(Boolean);
    const el = ensure(host, id, 'quote', el => {
      el.style.width = px(w); el.style.boxSizing = 'border-box'; el.style.background = bg; el.style.color = ink; el.style.padding = px(44) + ' ' + px(52) + ' ' + px(40);
      el.style.borderLeft = px(ed ? 10 : 2) + ' solid ' + accent; el.style.boxShadow = '0 24px 60px -24px rgba(0,0,0,.35)';
      if (s.zone === 'lower-left') { el.style.left = px(120); el.style.bottom = px(116); } else { el.style.left = '50%'; el.style.top = '50%'; el.style.transform = 'translate(-50%,-50%)'; }
      el.innerHTML = '<div class="q-k" style="font:600 ' + px(16) + '/1.2 ' + SANS + ';letter-spacing:0.28em;text-transform:uppercase;color:' + esc(accent) + '">' + esc(s.kicker || '') + '</div>' +
        '<div class="q-t" style="font:italic 400 ' + px(44) + '/1.25 ' + SERIF + ';margin-top:' + px(16) + '">' + words.map(x => '<span style="opacity:0">' + esc(x) + '</span>').join(' ') + '</div>' +
        '<div class="q-r" style="height:' + px(2) + ';width:' + px(120) + ';background:' + esc(accent) + ';margin:' + px(20) + ' 0 ' + px(14) + ';transform-origin:0 50%"></div>' +
        '<div class="q-a" style="font:400 ' + px(22) + '/1.3 ' + SANS + ';letter-spacing:0.02em;opacity:.8">' + esc(s.attribution || '') + '</div>';
    });
    const u = t - s.t0;
    if (u < 0 || u >= dur) { hide(el); return { visible: false, rect: null, el: el }; }
    show(el);
    const a = EO2(rmp(u, 0, 0.4)), x = EI2(rmp(u, dur - 0.35, dur));
    el.style.opacity = (a * (1 - x)).toFixed(3);
    el.querySelector('.q-k').style.opacity = EO2(rmp(u, 0.05, 0.45)).toFixed(3);
    el.querySelectorAll('.q-t span').forEach((sp, i) => { sp.style.opacity = rmp(u, 0.3 + i * 0.1, 0.6 + i * 0.1).toFixed(3); });
    const tq = 0.3 + words.length * 0.1 + 0.2;
    el.querySelector('.q-r').style.transform = 'scaleX(' + EO3(rmp(u, tq, tq + 0.5)).toFixed(4) + ')';
    el.querySelector('.q-a').style.opacity = (0.8 * EO2(rmp(u, tq + 0.3, tq + 0.7))).toFixed(3);
    return { visible: true, rect: rectOf(el), el: el };
  }

  /* ================================================================== hairline viewfinder + PiP frame ========
     hairline(host, rect, {id, accent, opacity}) — a static decorative frame around a rect (stage px): inset 2 px accent
     stroke + 6 px stroke at 13 % alpha + 1 px dark outer, four 24 px corner ticks (4 px strokes). Marks "this is the real
     product" around a PiP inside a recreated interlude. Never over full-bleed video.
     pip(t, spec) — the tween of the real-screen rect for a picture-in-picture: {t0, dur: 0.6, from:[0,0,W,H], to:'top-right'|'bottom-right'|[x,y,w,h]}
     → { rect, s, tx, ty, u } (power2-inOut). The scene applies it to #clipWrap as translate/scale (footage.js owns the
     clip; this helper only computes the geometry) and draws the frame with pipFrame(host, t, spec). Pill chrome: radius 14,
     ring 0 0 0 4px rgba(255,255,255,.7) + 0 0 0 5px rgba(0,0,0,.18), shadow 0 24px 60px -20px rgba(0,0,0,.45). */
  const PIP_RECTS = { 'top-right': [1432, 28, 460, 258], 'bottom-right': [1480, 760, 400, 300] };
  function hairline(host, rect, o) {
    o = o || {}; const id = o.id || 'hairline', accent = o.accent || '#E56B5E';
    const el = ensure(host, id, 'pip', el => {
      el.innerHTML = ['tl', 'tr', 'bl', 'br'].map(c => '<span class="hl-tick ' + c + '" style="position:absolute;width:' + px(24) + ';height:' + px(24) + ';' +
        (c[0] === 't' ? 'top:-3px;border-top:' : 'bottom:-3px;border-bottom:') + px(4) + ' solid ' + esc(accent) + ';' +
        (c[1] === 'l' ? 'left:-3px;border-left:' : 'right:-3px;border-right:') + px(4) + ' solid ' + esc(accent) + '"></span>').join('');
      el.style.boxShadow = 'inset 0 0 0 2px ' + accent + ', inset 0 0 0 6px ' + rgba(accent, 0.13) + ', 0 0 0 1px rgba(0,0,0,.1)';
      el.setAttribute('data-ov-bleed', '1');                       // the frame hugs the PiP; the PiP itself is the safe-zone subject
    });
    el.style.left = rect[0].toFixed(2) + 'px'; el.style.top = rect[1].toFixed(2) + 'px'; el.style.width = rect[2].toFixed(2) + 'px'; el.style.height = rect[3].toFixed(2) + 'px';
    const op = o.opacity === undefined ? 1 : o.opacity;
    if (op <= 0) hide(el); else { show(el); el.style.opacity = op.toFixed(3); }
    return el;
  }
  function rgba(hex, a) { const m = /^#([0-9a-f]{6})$/i.exec(hex); if (!m) return hex; return 'rgba(' + parseInt(m[1].slice(0, 2), 16) + ',' + parseInt(m[1].slice(2, 4), 16) + ',' + parseInt(m[1].slice(4, 6), 16) + ',' + a + ')'; }
  function pip(t, s) {
    const from = s.from || [0, 0, STAGE[0], STAGE[1]], to = Array.isArray(s.to) ? s.to : (PIP_RECTS[s.to || 'top-right']).map(v => v * K());
    const u = EIO(rmp(t, s.t0, s.t0 + (s.dur || 0.6))), r = from.map((v, i) => lerp(v, to[i], u));
    const sc = r[2] / STAGE[0];
    return { rect: r, u: u, s: sc, tx: r[0], ty: r[1], transform: 'translate(' + r[0].toFixed(2) + 'px,' + r[1].toFixed(2) + 'px) scale(' + sc.toFixed(4) + ')', active: t >= s.t0 };
  }
  function pipFrame(host, t, s) {
    const p = pip(t, s), id = reg('pip', Object.assign({ id: s.id || 'pip' }, s));
    const el = ensure(host, id, 'pip', el => { el.style.borderRadius = px(14); el.setAttribute('data-ov-bleed', '1'); });
    el.style.left = p.rect[0].toFixed(2) + 'px'; el.style.top = p.rect[1].toFixed(2) + 'px'; el.style.width = p.rect[2].toFixed(2) + 'px'; el.style.height = p.rect[3].toFixed(2) + 'px';
    const ring = p.u;
    el.style.boxShadow = '0 0 0 ' + (4 * ring).toFixed(2) + 'px rgba(255,255,255,.7), 0 0 0 ' + (5 * ring).toFixed(2) + 'px rgba(0,0,0,.18), 0 ' + px(24) + ' ' + px(60) + ' ' + px(-20) + ' rgba(0,0,0,' + (0.45 * ring).toFixed(3) + ')';
    if (p.u <= 0) hide(el); else { show(el); el.style.opacity = '1'; }
    if (s.hairline) hairline(host, p.rect, { id: id + '-hair', accent: s.accent, opacity: p.u });
    return p;
  }

  /* ================================================================== promoted hero word (yield rule) ========
     spec: { id, t0, dur: 2.4, text: 'governed', style: 'keynote'|'ink'|'documentary', accent, apex: false, dim: 0.12, cue: [phase, word] }
     Scarcity (QA-enforced): ≤ 1 per beat, never two co-visible, ≥ 0.6 s air between windows, ≤ qa.json hero_max_per_film (2),
     one apex per film. Size: fit to 0.9·W from 0.22·H down to the 0.18·H floor (never smaller — widen the box). Entrance
     clip wipe-up 0.6 s power4-out (documentary: rise), dwell ≥ 1 s, exit 0.45 s power2-in to opacity 0. The lane yields:
     dims to 0.55 from t0 − 0.2 s to t1 + 0.9 s and hides the promoted word's own group during the window. Over footage the
     word gets a LOCAL 10–15 % dim plate under its own box (never a frame-wide grade); never over readable product text. */
  const HERO = {
    keynote:     { font: SANS, weight: 800, ink: '#ffffff', upper: true, tracking: '-0.045em', wipe: true },
    ink:         { font: SANS, weight: 700, ink: '#111418', upper: false, tracking: '-0.03em', wipe: true },
    documentary: { font: SANS, weight: 700, ink: '#F5EFE6', upper: false, tracking: '-0.015em', wipe: false }
  };
  function hero(host, t, s) {
    const id = reg('hero', s), dur = s.dur || 2.4, st = HERO[s.style] || HERO.keynote, text = st.upper ? String(s.text).toUpperCase() : String(s.text);
    const el = ensure(host, id, 'hero', el => {
      const W = STAGE[0], H = STAGE[1], base = Math.round(0.22 * H), floor = Math.round(0.18 * H);
      const fit = fitPx(text, st.weight + ' ' + base + 'px ' + st.font, 0.9 * W, base, floor);
      let tracking = st.tracking;
      if (s.apex && root.CAP && root.CAP.measure) {                 // apex: a short word fills toward 93 % of the usable width with tracking ≤ +0.32em
        const wpx = root.CAP.measure(text, st.weight + ' ' + fit + 'px ' + st.font, 'canvas'), want = 0.93 * 0.8 * W;
        if (wpx < want && text.length > 1) tracking = Math.min(0.32, (want - wpx) / Math.max(1, text.length - 1) / fit).toFixed(3) + 'em';
      }
      el.style.left = '50%'; el.style.top = '50%'; el.style.transform = 'translate(-50%,-50%)'; el.style.whiteSpace = 'nowrap'; el.style.textAlign = 'center';
      el.innerHTML = '<div class="hero-plate" style="position:absolute;left:-12%;top:-30%;width:124%;height:160%;border-radius:50%;background:radial-gradient(ellipse, rgba(0,0,0,' + (s.dim === undefined ? 0.12 : s.dim) + ') 40%, rgba(0,0,0,0) 72%)"></div>' +
        '<div class="hero-w" style="position:relative;font:' + st.weight + ' ' + fit + 'px/1.05 ' + st.font + ';color:' + esc(s.accent || st.ink) + ';letter-spacing:' + tracking + '">' + esc(text) + '</div>';
    });
    if (root.CAP && root.CAP.lane) root.CAP.lane.yield(s.t0, s.t0 + dur, [s.text]);   // every frame (idempotent): the lane dims from t0 - 0.2 s, before the hero is first drawn
    const u = t - s.t0;
    if (u < 0 || u >= dur) { hide(el); return { visible: false, rect: null, el: el }; }
    show(el);
    const a = EO4(rmp(u, 0, 0.6)), x = EI2(rmp(u, dur - 0.45, dur)), w = el.querySelector('.hero-w'), plate = el.querySelector('.hero-plate');
    if (st.wipe) { w.style.clipPath = 'inset(' + ((1 - a) * 100).toFixed(2) + '% 0 0 0)'; w.style.transform = 'translateY(' + ((1 - a) * 0.12 * STAGE[1] * 0.2).toFixed(2) + 'px)'; }
    else { w.style.clipPath = 'none'; w.style.transform = 'translateY(' + ((1 - a) * 18 * K()).toFixed(2) + 'px)'; w.style.opacity = a.toFixed(3); }
    plate.style.opacity = (EO2(rmp(u, -0.2, 0.35)) * (1 - x)).toFixed(3);
    el.style.opacity = (1 - x).toFixed(3);
    return { visible: true, rect: rectOf(w), el: el };
  }

  /* ---------- QA helpers: hero scarcity rules evaluated on the registry (also run by overlay_gate.py) ---------- */
  function heroCheck(list, maxPerFilm) {
    const H = (list || windows()).filter(w => w.kind === 'hero').sort((a, b) => a.t0 - b.t0), bad = [];
    if (H.length > (maxPerFilm || 2)) bad.push(H.length + ' hero windows > ' + (maxPerFilm || 2));
    for (let i = 1; i < H.length; i++) {
      if (H[i].t0 < H[i - 1].t1) bad.push(H[i - 1].id + ' and ' + H[i].id + ' co-visible');
      else if (H[i].t0 - H[i - 1].t1 < 0.6) bad.push((H[i].t0 - H[i - 1].t1).toFixed(2) + ' s air between ' + H[i - 1].id + ' and ' + H[i].id + ' (< 0.6)');
    }
    return bad;
  }

  const OVL = { STAGE, CARD, HERO, PIP_RECTS, lowerThird, autoVariant, callout, quote, hairline, pip, pipFrame, hero, windows, declare, heroCheck, EO2, EO3, EO4, EI2, EIO, BACK,
    setStage: (w, h) => { STAGE[0] = w; STAGE[1] = h; } };
  if (typeof module !== 'undefined' && module.exports) module.exports = OVL;
  if (typeof window !== 'undefined') root.OVL = OVL;
})(typeof window !== 'undefined' ? window : globalThis);
