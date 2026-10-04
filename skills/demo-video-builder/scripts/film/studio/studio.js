/* studio.js — the preview studio's controller (served by tools/studio.py; see ui.html).

   The scene lives in an iframe at 1280x720 and exposes the render contract: window.__seek(t) (full reset,
   may return a Promise while images decode) and window.__step(t) (sequential, keeps caches). The studio is
   the only place a requestAnimationFrame loop is allowed: it is a VIEWER that asks the scene for frame(t)
   at the wall clock's pace; the scene itself stays a pure function of t, so what you scrub here is what
   render_frames.js will produce. Every seek is frame-quantised (round(t * fps) / fps) so the HUD's frame,
   phase and word agree with the renderer's frame grid.

   Hot reload: a long poll on /changes (the server stats the project every 500 ms) reloads the iframe with
   a cache-buster at the SAME t, re-fetches the manifest (seams / beats may have moved) and redraws.
   Taps: /tap?t= spawns the real renderer for one frame (9-14 s) and the still appears in the side panel.
   No external assets; no library. */
(function () {
  'use strict';
  const $ = s => document.querySelector(s);
  const S = { m: null, fps: 30, total: 0, t: 0, playing: false, win: null, version: 0, nocap: false, q: Promise.resolve(), busy: false, tapN: 0, reloadN: 0 };
  const iframe = $('#scene'), guides = $('#guides'), tl = $('#timeline'), scrub = $('#scrub');
  const clamp = (x, a, b) => Math.max(a, Math.min(b, x));
  const fmt = t => t.toFixed(3);
  const sleep = ms => new Promise(r => setTimeout(r, ms));

  /* ---------- manifest + scene ---------- */
  async function loadManifest() {
    const r = await fetch('/api/project'); S.m = await r.json();
    S.fps = S.m.fps || 30; S.total = S.m.total || S.total || 0;
    $('#projName').textContent = S.m.name + ' · ' + S.m.scene;
    placeGuides(); drawTimeline(); renderTaps(S.m.taps || []);
  }
  function sceneUrl(t) { return '/p/' + S.m.scene + '?t=' + fmt(t) + (S.nocap ? '&nocap' : '') + '&v=' + (S.version + '.' + S.reloadN); }
  function loadScene(t) {
    S.win = null; S.reloadN++;
    iframe.src = sceneUrl(t);
  }
  iframe.addEventListener('load', () => {
    S.win = iframe.contentWindow;
    try { if (S.win.__total) S.total = S.win.__total; } catch (e) { /* cross-origin never happens here */ }
    scrub.max = Math.round(S.total * S.fps);
    if (S.win && S.win.__seek) seek(S.t, false); else toast('scene has no window.__seek — not a clock-driven scene?');
    drawTimeline();
  });

  /* ---------- seeking (serialised: the scene may return a decode Promise) ---------- */
  function seek(t, step) {
    const frame = Math.round(clamp(t, 0, S.total || t) * S.fps); const tq = frame / S.fps;
    S.t = tq;
    S.q = S.q.then(async () => {
      if (!S.win || !S.win.__seek) return;
      S.busy = true;
      try {
        const fn = step && S.win.__step ? S.win.__step : S.win.__seek;
        await Promise.resolve(fn(tq));
      } catch (e) { toast('scene error: ' + (e && e.message)); }
      S.busy = false;
      hud();
    });
    return S.q;
  }
  function stepFrames(n) { stop(); const f = Math.round(S.t * S.fps) + n; seek(f / S.fps, n === 1); }

  /* ---------- play: rAF (viewer only) ---------- */
  let rafId = 0;
  function play() {
    if (S.playing) return stop();
    if (S.t >= S.total - 1e-6) S.t = 0;
    S.playing = true; $('#btnPlay').textContent = 'Pause'; $('#btnPlay').classList.add('primary');
    const t0 = performance.now() - S.t * 1000; let last = -1;
    const tick = now => {
      if (!S.playing) return;
      const t = (now - t0) / 1000; const frame = Math.floor(t * S.fps);
      if (t >= S.total) { seek(S.total, true); return stop(); }
      if (frame !== last && !S.busy) { last = frame; seek(frame / S.fps, true); }
      rafId = requestAnimationFrame(tick);
    };
    rafId = requestAnimationFrame(tick);
  }
  function stop() { S.playing = false; cancelAnimationFrame(rafId); $('#btnPlay').textContent = 'Play'; $('#btnPlay').classList.remove('primary'); }

  /* ---------- HUD ---------- */
  function phaseAt(t) { let cur = null; for (const p of (S.m && S.m.phases) || []) if (t >= p.start) cur = p; return cur; }
  function beatAt(t) { return ((S.m && S.m.beats) || []).find(b => t >= b.t0 && t < b.t1) || null; }
  function seamAt(t) { return ((S.m && S.m.seams) || []).find(s => t >= s.t0 && t <= s.t1) || null; }
  function camScale() {
    try { const el = S.win && S.win.document.querySelector('#camera'); const m = el && /scale\(([\d.]+)\)/.exec(el.style.transform || ''); return m ? parseFloat(m[1]) : 1; } catch (e) { return 1; }
  }
  function hud() {
    const t = S.t, frame = Math.round(t * S.fps);
    $('#hudT').textContent = fmt(t); $('#hudF').textContent = frame; $('#hudN').textContent = '/ ' + Math.round(S.total * S.fps);
    const ph = phaseAt(t); $('#hudPhase').textContent = ph ? ph.name : '—';
    const b = beatAt(t); $('#hudBeat').textContent = b ? ('%02d ' + b.title).replace('%02d', String(b.n).padStart(2, '0')) : '—';
    $('#hudCam').textContent = camScale().toFixed(2) + '×';
    const sm = seamAt(t); const hs = $('#hudSeam'); hs.textContent = sm ? sm.id : '—'; hs.classList.toggle('live', !!sm);
    scrub.value = frame;
    words(t, ph); drawTimeline();
  }
  function words(t, ph) {
    const box = $('#words');
    if (!ph) { box.innerHTML = '<div class="muted">no phase at this t</div>'; return; }
    const W = (S.m.words || {})[ph.name] || []; let now = -1;
    W.forEach((w, i) => { if (ph.start + w.t <= t) now = i; });
    box.innerHTML = '<span class="ph">' + esc(ph.name) + ' · ' + W.length + ' words</span>' +
      W.map((w, i) => '<span class="w' + (i <= now ? ' said' : '') + (i === now ? ' now' : '') + '" title="' + (ph.start + w.t).toFixed(3) + '">' + esc(w.w) + '</span>').join('');
    const el = box.querySelector('.now'); if (el && el.scrollIntoView) el.scrollIntoView({ block: 'nearest' });
  }
  const esc = s => String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

  /* ---------- stage scaling + guides ---------- */
  function fit() {
    const box = $('#stageBox'); const w = box.clientWidth, h = box.clientHeight; const s = Math.min(w / 1280, h / 720);
    const x = (w - 1280 * s) / 2, y = (h - 720 * s) / 2;
    for (const el of [iframe, guides]) el.style.transform = 'translate(' + x.toFixed(1) + 'px,' + y.toFixed(1) + 'px) scale(' + s.toFixed(4) + ')';
  }
  function rect(el, r) { el.style.left = r[0] + 'px'; el.style.top = r[1] + 'px'; el.style.width = r[2] + 'px'; el.style.height = r[3] + 'px'; }
  function placeGuides() {
    if (!S.m) return;
    rect($('#gTitle'), S.m.guides.title_safe); rect($('#gAction'), S.m.guides.action_safe); rect($('#gCaption'), S.m.captions.box);
    $('#gCaption span').textContent = 'caption lane · y ≥ ' + S.m.captions.box[1] + (S.m.captions.style ? ' · ' + S.m.captions.style : '');
    syncGuideChecks();
  }
  function syncGuideChecks() {
    $('#gTitle').classList.toggle('hidden', !$('#ckTitle').checked); $('#gAction').classList.toggle('hidden', !$('#ckAction').checked);
    $('#gCaption').classList.toggle('hidden', !$('#ckCaption').checked); $('.g.cross').classList.toggle('hidden', !$('#ckCross').checked);
  }
  ['#ckTitle', '#ckAction', '#ckCaption', '#ckCross'].forEach(id => $(id).addEventListener('change', syncGuideChecks));
  $('#ckNocap').addEventListener('change', e => { S.nocap = e.target.checked; loadScene(S.t); });
  function toggleGuides() { const on = guides.classList.toggle('off'); $('#btnGuides').classList.toggle('on', !on); }

  /* ---------- timeline canvas ---------- */
  const ROW = { phase: [2, 18], beat: [21, 35], seam: [38, 50], cam: [54, 94], ruler: [96, 118] };
  function x_of(t, W) { return S.total ? (t / S.total) * W : 0; }
  function drawTimeline() {
    const dpr = window.devicePixelRatio || 1; const W = tl.clientWidth, H = tl.clientHeight;
    if (tl.width !== Math.round(W * dpr) || tl.height !== Math.round(H * dpr)) { tl.width = Math.round(W * dpr); tl.height = Math.round(H * dpr); }
    const c = tl.getContext('2d'); c.setTransform(dpr, 0, 0, dpr, 0, 0); c.clearRect(0, 0, W, H);
    c.font = '600 10px "Segoe UI", Arial, sans-serif'; c.textBaseline = 'middle';
    if (!S.m || !S.total) { c.fillStyle = 'rgba(233,243,249,.5)'; c.fillText('no clock: scenes/timing_<name>.js or vo/<name>_phases.json missing', 10, 20); return; }
    /* phases */
    (S.m.phases || []).forEach((p, i) => {
      const x0 = x_of(p.start, W), x1 = x_of(p.start + p.dur, W);
      c.fillStyle = i % 2 ? 'rgba(32,74,86,.9)' : 'rgba(32,74,86,.55)'; c.fillRect(x0, ROW.phase[0], x1 - x0, ROW.phase[1] - ROW.phase[0]);
      c.fillStyle = '#E9F3F9'; c.save(); c.beginPath(); c.rect(x0, ROW.phase[0], x1 - x0, 16); c.clip(); c.fillText(p.name, x0 + 4, (ROW.phase[0] + ROW.phase[1]) / 2); c.restore();
    });
    /* beats */
    (S.m.beats || []).forEach(b => {
      const x0 = x_of(b.t0, W), x1 = x_of(b.t1, W);
      c.fillStyle = 'rgba(129,169,171,.18)'; c.fillRect(x0, ROW.beat[0], x1 - x0, ROW.beat[1] - ROW.beat[0]);
      c.fillStyle = '#81A9AB'; c.fillRect(x0, ROW.beat[0], 1, ROW.beat[1] - ROW.beat[0]);
      c.save(); c.beginPath(); c.rect(x0, ROW.beat[0], x1 - x0 - 2, 14); c.clip(); c.fillStyle = '#ECDEC3'; c.fillText(String(b.n).padStart(2, '0') + ' ' + b.title, x0 + 4, (ROW.beat[0] + ROW.beat[1]) / 2); c.restore();
    });
    /* seams: coloured band t0..t1, a bright line at the cut */
    (S.m.seams || []).forEach(s => {
      const x0 = x_of(s.t0, W), x1 = x_of(s.t1, W), xc = x_of(s.cut, W);
      c.fillStyle = 'rgba(229,107,94,.35)'; c.fillRect(x0, ROW.seam[0], Math.max(2, x1 - x0), ROW.seam[1] - ROW.seam[0]);
      c.fillStyle = '#E56B5E'; c.fillRect(xc - 0.5, ROW.seam[0] - 2, 1.5, ROW.seam[1] - ROW.seam[0] + 4);
    });
    c.fillStyle = 'rgba(233,243,249,.45)'; c.fillText('seams ' + (S.m.seams || []).length, 4, (ROW.seam[0] + ROW.seam[1]) / 2 + 0);
    /* camera: scale trace per shot (1× at the bottom of the row, the peak at the top) */
    const cam = S.m.camera; const y0 = ROW.cam[1], y1 = ROW.cam[0];
    c.strokeStyle = 'rgba(129,169,171,.3)'; c.beginPath(); c.moveTo(0, y0 + .5); c.lineTo(W, y0 + .5); c.stroke();
    if (cam && cam.shots && cam.shots.length) {
      const peak = Math.max(1.3, ...cam.shots.map(sh => sh.trace.reduce((m, p) => Math.max(m, p[1]), 1)));
      const yOf = s => y0 - ((s - 1) / (peak - 1)) * (y0 - y1 - 6);
      c.strokeStyle = 'rgba(129,169,171,.3)'; c.setLineDash([2, 4]); c.beginPath(); c.moveTo(0, yOf(peak) + .5); c.lineTo(W, yOf(peak) + .5); c.stroke(); c.setLineDash([]);
      c.fillStyle = 'rgba(233,243,249,.45)'; c.fillText('zoom ' + peak.toFixed(2) + '×', 4, yOf(peak) + 7); c.fillText('1×', 4, y0 - 7);
      cam.shots.forEach(sh => {
        c.strokeStyle = '#81A9AB'; c.lineWidth = 1.5; c.beginPath();
        sh.trace.forEach((p, i) => { const x = x_of(p[0], W), y = yOf(p[1]); i ? c.lineTo(x, y) : c.moveTo(x, y); }); c.stroke(); c.lineWidth = 1;
        const est = (sh.windows && sh.windows.establish) || [];
        est.forEach(w => { c.fillStyle = 'rgba(232,200,116,.25)'; c.fillRect(x_of(w[0], W), y1, x_of(w[1], W) - x_of(w[0], W), y0 - y1); });
      });
    } else { c.fillStyle = 'rgba(233,243,249,.35)'; c.fillText('camera trace: run  node scenes/lib/camera.js --curves  → out/camera_curves.json', 4, (y0 + y1) / 2); }
    /* live camera dot */
    const cs = camScale(); if (cam && cam.shots && cam.shots.length) { const peak = Math.max(1.3, ...cam.shots.map(sh => sh.trace.reduce((m, p) => Math.max(m, p[1]), 1))); const y = y0 - ((cs - 1) / (peak - 1)) * (y0 - y1 - 6); c.fillStyle = '#E8C874'; c.beginPath(); c.arc(x_of(S.t, W), y, 3, 0, Math.PI * 2); c.fill(); }
    /* ruler */
    const step = S.total > 90 ? 10 : S.total > 40 ? 5 : S.total > 15 ? 2 : 1;
    c.fillStyle = 'rgba(233,243,249,.5)';
    for (let s = 0; s <= S.total; s += step) { const x = x_of(s, W); c.fillRect(x, ROW.ruler[0], 1, 5); c.fillText(s + 's', x + 3, ROW.ruler[0] + 5); }
    /* playhead */
    const xp = x_of(S.t, W); c.fillStyle = '#E8C874'; c.fillRect(xp - 0.5, 0, 1.5, ROW.ruler[0] + 4);
    c.beginPath(); c.moveTo(xp - 5, 0); c.lineTo(xp + 5, 0); c.lineTo(xp, 6); c.closePath(); c.fill();
  }
  let dragging = false;
  const tAtEvent = e => clamp((e.clientX - tl.getBoundingClientRect().left) / tl.clientWidth, 0, 1) * S.total;
  tl.addEventListener('mousedown', e => { dragging = true; stop(); seek(tAtEvent(e), false); });
  window.addEventListener('mousemove', e => { if (dragging) seek(tAtEvent(e), false); });
  window.addEventListener('mouseup', () => { dragging = false; });
  scrub.addEventListener('input', () => { stop(); seek(parseInt(scrub.value, 10) / S.fps, false); });

  /* ---------- hot reload (long poll) ---------- */
  async function pollChanges() {
    for (;;) {
      try {
        const r = await fetch('/changes?since=' + S.version); const j = await r.json();
        if (j.version > S.version) { const first = S.version === 0; S.version = j.version; if (!first && j.changed.length) await onChanged(j.changed); }
      } catch (e) { await sleep(1000); }
    }
  }
  async function onChanged(list) {
    const box = $('#changes'); if (box.querySelector('.muted')) box.innerHTML = '';
    const d = document.createElement('div'); d.innerHTML = '<b>v' + S.version + '</b> ' + esc(list.join(', ')); box.prepend(d);
    toast('reloaded at t=' + fmt(S.t) + ' · ' + list.slice(0, 3).join(', ') + (list.length > 3 ? ' +' + (list.length - 3) : ''));
    const wasPlaying = S.playing; stop();
    await loadManifest(); loadScene(S.t);
    if (wasPlaying) iframe.addEventListener('load', () => play(), { once: true });
  }

  /* ---------- tap + QA ---------- */
  function renderTaps(list) {
    const box = $('#taps'); box.innerHTML = '';
    list.slice().sort().reverse().forEach(name => box.appendChild(tapCard('out/taps/' + name, name)));
  }
  function tapCard(png, label) {
    const a = document.createElement('a'); a.href = '/p/' + png + '?n=' + (++S.tapN); a.target = '_blank';
    a.innerHTML = '<img alt=""><span></span>'; a.querySelector('img').src = a.href; a.querySelector('span').textContent = label.replace(/^tap_/, '').replace(/\.png$/, '');
    return a;
  }
  async function tap() {
    const b = $('#btnTap'); if (b.classList.contains('busy')) return; b.classList.add('busy'); $('#tapStatus').textContent = 'rendering frame ' + Math.round(S.t * S.fps) + ' through render_frames.js…';
    try {
      const r = await fetch('/tap?t=' + fmt(S.t)); const j = await r.json();
      if (j.ok) { $('#tapStatus').textContent = j.wall_s + ' s · ' + (j.renderer && j.renderer.gl || '') + ' · ' + Math.round(j.size / 1024) + ' KB'; $('#taps').prepend(tapCard(j.png, 'f' + String(j.frame).padStart(5, '0') + ' · ' + j.t.toFixed(2) + 's')); toast('tap → ' + j.png); }
      else { $('#tapStatus').textContent = 'failed'; const e = document.createElement('a'); e.className = 'err'; e.textContent = j.error + (j.stderr ? ' — ' + j.stderr.slice(-300) : ''); $('#taps').prepend(e); }
    } catch (e) { $('#tapStatus').textContent = 'failed: ' + e.message; }
    b.classList.remove('busy');
  }
  async function qa() {
    const b = $('#btnQA'); if (b.classList.contains('busy')) return; b.classList.add('busy'); $('#qaStatus').textContent = 'running lint_scene.py…';
    try {
      const r = await fetch('/qa'); const j = await r.json(); const box = $('#qa');
      if (j.error) { box.innerHTML = '<div class="bad">' + esc(j.error) + '</div>'; }
      else {
        const counts = Object.entries(j.counts || {}).map(([k, v]) => v + ' ' + k).join(' · ') || 'no findings';
        box.innerHTML = '<div class="' + (j.ok ? 'ok' : 'bad') + '">' + (j.ok ? 'clean' : 'findings') + ' · exit ' + j.exit + ' · ' + j.wall_s + ' s · ' + esc(counts) + '</div>' +
          (j.findings || []).slice(0, 60).map(f => '<div class="row"><span class="sev ' + esc(f.severity || '') + '">' + esc(f.severity || '') + '</span><span>' + esc(f.code || '') + (f.line ? ':' + f.line : '') + ' — ' + esc(f.message || '') + '</span></div>').join('') +
          (j.raw ? '<pre class="muted">' + esc(j.raw) + '</pre>' : '');
      }
      $('#qaStatus').textContent = j.ok ? 'clean' : 'see findings';
    } catch (e) { $('#qaStatus').textContent = 'failed: ' + e.message; }
    b.classList.remove('busy');
  }

  /* ---------- toast, keys, wiring ---------- */
  let toastTimer = 0;
  function toast(msg) { const el = $('#toast'); el.textContent = msg; el.classList.add('show'); clearTimeout(toastTimer); toastTimer = setTimeout(() => el.classList.remove('show'), 2600); }
  window.addEventListener('keydown', e => {
    if (e.target && /^(INPUT|TEXTAREA)$/.test(e.target.tagName) && e.target.type !== 'range' && e.target.type !== 'checkbox') return;
    const n = e.shiftKey ? 10 : 1;
    if (e.key === 'ArrowRight') { stepFrames(n); e.preventDefault(); }
    else if (e.key === 'ArrowLeft') { stepFrames(-n); e.preventDefault(); }
    else if (e.key === ' ') { play(); e.preventDefault(); }
    else if (e.key === 'Home') { stop(); seek(0, false); }
    else if (e.key === 'End') { stop(); seek(S.total, false); }
    else if (e.key === 't' || e.key === 'T') tap();
    else if (e.key === 'q' || e.key === 'Q') qa();
    else if (e.key === 'g' || e.key === 'G') toggleGuides();
    else if (e.key === 'r' || e.key === 'R') loadScene(S.t);
  });
  $('#btnPlay').addEventListener('click', play); $('#btnTap').addEventListener('click', tap); $('#btnQA').addEventListener('click', qa);
  $('#btnGuides').addEventListener('click', toggleGuides); $('#btnReload').addEventListener('click', () => loadScene(S.t));
  new ResizeObserver(() => { fit(); drawTimeline(); }).observe($('#stageBox'));
  window.addEventListener('resize', () => { fit(); drawTimeline(); });

  (async () => {
    await loadManifest();
    const q = new URLSearchParams(location.search); S.t = parseFloat(q.get('t') || '0') || 0;
    fit(); loadScene(S.t); pollChanges();
  })();
  window.STUDIO = { seek, step: stepFrames, play, stop, tap, qa, state: S };   // for scripting / puppeteer tests
})();
