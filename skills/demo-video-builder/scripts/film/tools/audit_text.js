#!/usr/bin/env node
/* audit_text.js — runtime text audit of a frame(t) scene: overflow, clipping, off-stage text, text overlap, the
   credit band, and (--contrast) WCAG AA contrast of every visible text element at sampled film times.

     node tools/audit_text.js scenes/film.html [--times 3.0,12.8] [--contrast] [--json] [--out out/audit_text.json]
                              [--end 32.03] [--strict]

   Times (default, read from the loaded scene itself): every shot t0 + 0.4 s, each lower-third window middle
   (FILM.acts t0 + 2), the title card at FILM.openEnd / 2, and the close at END - 0.5 / END - 0.05
   (END = TX.total unless --end). Each time is a cold __seek(t) (decode-aware, fonts.ready first).

   Per sample, for every element that owns a text node, is not display:none, passes checkVisibility and whose
   opacity chain is >= 0.5 (an element fading in at 0.3 is not judged yet):
     clipped_text        nearest ancestor with overflow hidden clips it: scrollWidth - clientWidth > 2 px or
                         scrollHeight - clientHeight > 2 px
     text_box_overflow   the union of the text's line rects exceeds its constraining container by > 2 px
                         horizontally; vertically by > max(2 px, 0.2 x font-size) when the container does not clip
     stage_overflow      the text rect leaves the 1280x720 stage (any side)
     credit_zone         text intersects the bottom 120 px (y >= 600) during the last 4 s — the band where
                         credit.py later stamps the mandatory FDE Demo Builder line
     text_overlap        two visible text blocks from different elements intersect by > 2 px on both axes
     low_contrast        (--contrast) ratio < 4.5:1, or < 3:1 for large text (>= 24 px, or >= 19 px bold); the
                         background is the median of the real composited pixels inside the text box, sampled
                         with the glyph paint made transparent (restored in a finally block), so pills, panel
                         edges and footage under a lower-third are measured as they are. The finding carries fg,
                         bg, ratio, required and a suggested colour nudged in the same direction (lighter on dark,
                         darker on light) until the ratio passes.
   Persistence: an issue seen at a single sampled time is 'info' (transient — a card mid-fade); the same
   issue (code + element) at >= 2 consecutive samples is an 'error'. low_contrast is 'warning' by default
   (`--strict` or qa.json "contrast": "error" makes it an error). Opt-outs: data-qa-ignore (skip the element),
   data-qa-allow-overflow, data-qa-allow-overlap, data-qa-allow-contrast.

   Output: a human table and {ok, errorCount, warningCount, times, findings:[{code, severity, selector, text,
   t, times, detail, ...}]} to --out (default out/audit_text.json). Exit 1 on errors. */
'use strict';
const puppeteer = require('puppeteer');
const path = require('path'); const fs = require('fs');

function chromePath() {
  if (process.env.PUPPETEER_EXECUTABLE_PATH) return process.env.PUPPETEER_EXECUTABLE_PATH;
  try { const p = puppeteer.executablePath(); if (fs.existsSync(p)) return p; } catch (e) {}
  return ['C:/Program Files/Google/Chrome/Application/chrome.exe', 'C:/Program Files (x86)/Google/Chrome/Application/chrome.exe',
          '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', '/usr/bin/google-chrome', '/usr/bin/chromium-browser'].find(fs.existsSync);
}
const argv = process.argv.slice(2);
const opt = (k, d) => { const i = argv.indexOf(k); return i >= 0 && i + 1 < argv.length ? argv[i + 1] : d; };
const has = k => argv.includes(k);
const SCENE = argv.find(a => !a.startsWith('--') && /\.html?(\?|$)/i.test(a));
if (!SCENE) { console.error('usage: node tools/audit_text.js scenes/film.html [--times t,...] [--contrast] [--json] [--out file] [--end s] [--strict]'); process.exit(2); }
const CONTRAST = has('--contrast'), STRICT = has('--strict'), JSON_OUT = has('--json');
const OUT = opt('--out', path.join(path.dirname(path.dirname(path.resolve(SCENE.split('?')[0]))), 'out', 'audit_text.json'));
const [sp, sq] = SCENE.split('?');
const URL = 'file://' + path.resolve(sp) + '?' + (sq ? sq + '&' : '') + 'render';
const STAGE_W = 1280, STAGE_H = 720, TOL = 2, CREDIT_Y = 600, CREDIT_SECS = 4.0, OPACITY_FLOOR = 0.5;
const FLAGS = ['--no-sandbox', '--hide-scrollbars', '--font-render-hinting=none', '--disable-lcd-text', '--force-color-profile=srgb',
               '--disable-background-timer-throttling', '--disable-renderer-backgrounding', '--allow-file-access-from-files', '--force-device-scale-factor=1'];

/* ------------------------------------------------------------------ in-page: default times from the scene globals */
function pageTimes(endOverride) {
  const T = window.TX, F = window.FILM || {}, SH = window.SHOTS || [];
  const END = endOverride || (T && T.total) || (window.__total) || 10;
  const ts = [];
  if (F.openEnd) ts.push(F.openEnd / 2);
  SH.forEach(s => { if (typeof s.t0 === 'number') ts.push(s.t0 + 0.4); });
  (F.acts || []).forEach(a => { if (typeof a.t0 === 'number') ts.push(a.t0 + 2); });
  ts.push(END - 0.5, END - 0.05);
  return { END, times: ts.filter(t => t >= 0 && t <= END).map(t => Math.round(t * 1000) / 1000).filter((v, i, a) => a.indexOf(v) === i).sort((a, b) => a - b) };
}

/* ------------------------------------------------------------------ in-page: the layout audit at the current frame */
function pageAudit(cfg) {
  const { t, END, TOL, CREDIT_Y, CREDIT_SECS, OPACITY_FLOOR, STAGE_W, STAGE_H } = cfg;
  const out = [];
  const stage = document.getElementById('stage') || document.body;
  const stageRect = stage.getBoundingClientRect();
  const sel = el => {
    if (el.id) return '#' + el.id;
    const parts = [];
    for (let e = el; e && e !== document.body && parts.length < 3; e = e.parentElement) {
      let s = e.tagName.toLowerCase();
      if (e.id) { parts.unshift('#' + e.id); break; }
      if (e.classList.length) s += '.' + Array.from(e.classList).slice(0, 2).join('.');
      const sib = e.parentElement ? Array.from(e.parentElement.children).filter(c => c.tagName === e.tagName) : [];
      if (sib.length > 1) s += ':nth-of-type(' + (sib.indexOf(e) + 1) + ')';
      parts.unshift(s);
    }
    return parts.join(' > ');
  };
  const opacityChain = el => { let o = 1; for (let e = el; e && e.nodeType === 1; e = e.parentElement) { o *= parseFloat(getComputedStyle(e).opacity || '1'); if (o < 0.01) break; } return o; };
  const ownsText = el => Array.from(el.childNodes).some(n => n.nodeType === 3 && n.textContent.trim().length > 0);
  const textRects = el => {
    const r = document.createRange(); const rects = [];
    Array.from(el.childNodes).forEach(n => { if (n.nodeType !== 3 || !n.textContent.trim()) return; r.selectNodeContents(n); Array.from(r.getClientRects()).forEach(x => { if (x.width > 0 && x.height > 0) rects.push(x); }); });
    if (!rects.length) return null;
    return { left: Math.min(...rects.map(x => x.left)), top: Math.min(...rects.map(x => x.top)), right: Math.max(...rects.map(x => x.right)), bottom: Math.max(...rects.map(x => x.bottom)) };
  };
  const clipAncestor = el => { for (let e = el.parentElement; e && e !== document.body; e = e.parentElement) { const cs = getComputedStyle(e); if (/(hidden|clip|scroll|auto)/.test(cs.overflow + cs.overflowX + cs.overflowY)) return e; } return null; };
  const items = [];
  const all = Array.from(stage.querySelectorAll('*'));
  for (const el of all) {
    if (!ownsText(el) || el.closest('[data-qa-ignore]')) continue;
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden') continue;
    if (el.checkVisibility && !el.checkVisibility({ opacityProperty: false, visibilityProperty: true })) continue;
    if (opacityChain(el) < OPACITY_FLOOR) continue;
    const tr = textRects(el);
    if (!tr) continue;
    const r = { left: tr.left - stageRect.left, top: tr.top - stageRect.top, right: tr.right - stageRect.left, bottom: tr.bottom - stageRect.top };
    const text = el.textContent.trim().replace(/\s+/g, ' ').slice(0, 60);
    const fontSize = parseFloat(cs.fontSize) || 16, bold = (parseInt(cs.fontWeight, 10) || 400) >= 700;
    items.push({ el, selector: sel(el), text, r, fontSize, bold, color: cs.color, allowOverflow: !!el.closest('[data-qa-allow-overflow]'), allowOverlap: !!el.closest('[data-qa-allow-overlap]'), allowContrast: !!el.closest('[data-qa-allow-contrast]') });
    // clipped_text
    if (cs.overflow !== 'visible' && ((el.scrollWidth - el.clientWidth > TOL) || (el.scrollHeight - el.clientHeight > TOL)) && !el.closest('[data-qa-allow-overflow]'))
      out.push({ code: 'clipped_text', selector: sel(el), text, detail: 'overflow ' + (el.scrollWidth - el.clientWidth) + 'x' + (el.scrollHeight - el.clientHeight) + ' px hidden' });
    // text_box_overflow vs nearest clipping container (or the element's own box when nothing clips)
    const ca = clipAncestor(el);
    const box = (ca || el).getBoundingClientRect();
    const vTol = ca ? TOL : Math.max(TOL, 0.2 * fontSize);
    if (!el.closest('[data-qa-allow-overflow]')) {
      const dx = Math.max(box.left - tr.left, tr.right - box.right), dy = Math.max(box.top - tr.top, tr.bottom - box.bottom);
      if (dx > TOL || dy > vTol) out.push({ code: 'text_box_overflow', selector: sel(el), text, detail: 'text exceeds ' + (ca ? sel(ca) : 'its box') + ' by ' + Math.round(Math.max(dx, 0)) + 'x' + Math.round(Math.max(dy, 0)) + ' px' });
      if (r.left < -TOL || r.top < -TOL || r.right > STAGE_W + TOL || r.bottom > STAGE_H + TOL)
        out.push({ code: 'stage_overflow', selector: sel(el), text, detail: 'text rect ' + [r.left, r.top, r.right, r.bottom].map(Math.round).join(',') + ' leaves the stage' });
    }
    if (t >= END - CREDIT_SECS && r.bottom > CREDIT_Y && r.top < STAGE_H)
      out.push({ code: 'credit_zone', selector: sel(el), text, detail: 'text at y ' + Math.round(r.top) + '-' + Math.round(r.bottom) + ' sits in the credit band (y >= ' + CREDIT_Y + ') during the last ' + CREDIT_SECS + ' s' });
  }
  for (let i = 0; i < items.length; i++) for (let j = i + 1; j < items.length; j++) {
    const a = items[i], b = items[j];
    if (a.allowOverlap || b.allowOverlap || a.el.contains(b.el) || b.el.contains(a.el)) continue;
    const ox = Math.min(a.r.right, b.r.right) - Math.max(a.r.left, b.r.left), oy = Math.min(a.r.bottom, b.r.bottom) - Math.max(a.r.top, b.r.top);
    if (ox > TOL && oy > TOL) out.push({ code: 'text_overlap', selector: a.selector + ' x ' + b.selector, text: a.text + ' | ' + b.text, detail: Math.round(ox) + 'x' + Math.round(oy) + ' px overlap' });
  }
  return { findings: out, items: items.map(it => ({ selector: it.selector, text: it.text, r: it.r, fontSize: it.fontSize, bold: it.bold, color: it.color, allowContrast: it.allowContrast })) };
}

/* ------------------------------------------------------------------ in-page: hide / restore glyph paint for the contrast pass */
function pageHideGlyphs() {
  const stage = document.getElementById('stage') || document.body;
  const saved = [];
  Array.from(stage.querySelectorAll('*')).forEach(el => {
    if (!Array.from(el.childNodes).some(n => n.nodeType === 3 && n.textContent.trim())) return;
    saved.push([el, el.style.color, el.style.webkitTextFillColor, el.style.textShadow]);
    el.style.color = 'transparent'; el.style.webkitTextFillColor = 'transparent'; el.style.textShadow = 'none';
  });
  window.__qaSaved = saved;
  return saved.length;
}
function pageRestoreGlyphs() {
  (window.__qaSaved || []).forEach(([el, c, f, s]) => { el.style.color = c; el.style.webkitTextFillColor = f; el.style.textShadow = s; });
  window.__qaSaved = null;
}
async function pageSampleBg(dataUrl, boxes) {
  const img = new Image(); img.src = dataUrl; await img.decode();
  const c = document.createElement('canvas'); c.width = img.naturalWidth; c.height = img.naturalHeight;
  const g = c.getContext('2d', { willReadFrequently: true }); g.drawImage(img, 0, 0);
  const sx = img.naturalWidth / 1280, sy = img.naturalHeight / 720;
  return boxes.map(b => {
    const x0 = Math.max(0, Math.floor(b.left * sx)), y0 = Math.max(0, Math.floor(b.top * sy));
    const w = Math.max(1, Math.min(c.width - x0, Math.ceil((b.right - b.left) * sx))), h = Math.max(1, Math.min(c.height - y0, Math.ceil((b.bottom - b.top) * sy)));
    const d = g.getImageData(x0, y0, w, h).data; const R = [], G = [], B = [];
    for (let i = 0; i < d.length; i += 4 * Math.max(1, Math.floor(d.length / 4 / 4000))) { R.push(d[i]); G.push(d[i + 1]); B.push(d[i + 2]); }
    const med = a => { a.sort((p, q) => p - q); return a[a.length >> 1]; };
    return [med(R), med(G), med(B)];
  });
}

/* ------------------------------------------------------------------ node: WCAG maths */
function parseColor(s) {
  const m = /rgba?\(\s*([\d.]+)[,\s]+([\d.]+)[,\s]+([\d.]+)/.exec(s || '');
  return m ? [parseFloat(m[1]), parseFloat(m[2]), parseFloat(m[3])] : [0, 0, 0];
}
const lum = ([r, g, b]) => { const f = c => { c /= 255; return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4); }; return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b); };
const ratio = (a, b) => { const la = lum(a), lb = lum(b); return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05); };
const hex = c => '#' + c.map(v => Math.round(Math.max(0, Math.min(255, v))).toString(16).padStart(2, '0')).join('');
function suggest(fg, bg, need) {           // nudge L toward the passing side, same hue (mix with white or black)
  const lighter = lum(bg) < 0.18;
  for (let k = 1; k <= 20; k++) {
    const u = k / 20, target = lighter ? 255 : 0;
    const c = fg.map(v => v + (target - v) * u);
    if (ratio(c, bg) >= need) return hex(c);
  }
  return lighter ? '#ffffff' : '#000000';
}

(async () => {
  const b = await puppeteer.launch({ headless: 'new', executablePath: chromePath(), args: FLAGS });
  const p = await b.newPage();
  const pageErrors = [];
  p.on('pageerror', e => pageErrors.push(e.message));
  await p.setViewport({ width: STAGE_W, height: STAGE_H, deviceScaleFactor: 1 });
  await p.goto(URL, { waitUntil: 'load', timeout: 120000 });
  await p.evaluate(() => document.fonts.ready);
  await new Promise(r => setTimeout(r, 300));
  const endOverride = opt('--end') ? parseFloat(opt('--end')) : null;
  const tinfo = await p.evaluate(pageTimes, endOverride);
  const END = tinfo.END;
  const times = opt('--times') ? opt('--times').split(',').map(parseFloat).filter(x => !isNaN(x)) : tinfo.times;
  const raw = [];                                   // [{t, findings:[...]}]
  for (const t of times) {
    await p.evaluate(t => { document.body.classList.remove('pre'); return window.__seek(t); }, t);
    await p.evaluate(() => document.body.offsetHeight);
    const res = await p.evaluate(pageAudit, { t, END, TOL, CREDIT_Y, CREDIT_SECS, OPACITY_FLOOR, STAGE_W, STAGE_H });
    const findings = res.findings;
    if (CONTRAST && res.items.length) {
      try {
        await p.evaluate(pageHideGlyphs);
        const shot = await p.screenshot({ type: 'png', encoding: 'base64', clip: { x: 0, y: 0, width: STAGE_W, height: STAGE_H } });
        await p.evaluate(pageRestoreGlyphs);                               // restore FIRST, then measure
        const bgs = await p.evaluate(pageSampleBg, 'data:image/png;base64,' + shot, res.items.map(i => i.r));
        res.items.forEach((it, i) => {
          if (it.allowContrast) return;
          const fg = parseColor(it.color), bg = bgs[i];
          const large = it.fontSize >= 24 || (it.fontSize >= 19 && it.bold);
          const need = large ? 3.0 : 4.5, r = ratio(fg, bg);
          if (r < need) findings.push({ code: 'low_contrast', selector: it.selector, text: it.text, detail: `${r.toFixed(2)}:1 < ${need}:1 (${large ? 'large' : 'normal'} ${Math.round(it.fontSize)} px) fg ${hex(fg)} on bg ${hex(bg)} — try ${suggest(fg, bg, need)}`,
                                        fg: hex(fg), bg: hex(bg), ratio: +r.toFixed(2), required: need, suggested: suggest(fg, bg, need) });
        });
      } finally { await p.evaluate(pageRestoreGlyphs); }
    }
    raw.push({ t, findings });
  }
  await b.close();
  // persistence: same code+selector at >= 2 consecutive samples -> error; single sample -> info
  const byKey = new Map();
  raw.forEach((s, idx) => s.findings.forEach(f => {
    const k = f.code + '|' + f.selector; const e = byKey.get(k) || { ...f, times: [], idxs: [] };
    e.times.push(s.t); e.idxs.push(idx); e.detail = f.detail; byKey.set(k, e);
  }));
  const findings = [];
  for (const e of byKey.values()) {
    const consecutive = e.idxs.some((v, i) => i > 0 && v === e.idxs[i - 1] + 1);
    let sev = consecutive ? 'error' : 'info';
    if (e.code === 'low_contrast') sev = STRICT ? (consecutive ? 'error' : 'warning') : 'warning';
    delete e.idxs; e.t = e.times[0]; e.severity = sev; findings.push(e);
  }
  findings.sort((a, b) => ({ error: 0, warning: 1, info: 2 }[a.severity] - { error: 0, warning: 1, info: 2 }[b.severity]) || a.t - b.t);
  const errorCount = findings.filter(f => f.severity === 'error').length + (pageErrors.length ? 1 : 0);
  const warningCount = findings.filter(f => f.severity === 'warning').length;
  const report = { ok: errorCount === 0, errorCount, warningCount, times, end: END, contrast: CONTRAST, pageErrors: pageErrors.slice(0, 5), findings };
  fs.mkdirSync(path.dirname(OUT), { recursive: true }); fs.writeFileSync(OUT, JSON.stringify(report, null, 1));
  if (JSON_OUT) console.log(JSON.stringify(report, null, 1));
  else {
    console.log(`audit_text  ${times.length} samples (${times.map(t => t.toFixed(2)).join(', ')})  END ${END.toFixed(2)}${CONTRAST ? '  + contrast' : ''}`);
    for (const f of findings) if (f.severity !== 'info' || has('--verbose'))
      console.log(`  ${f.severity.toUpperCase().padEnd(7)} ${f.code.padEnd(18)} ${f.selector.slice(0, 40).padEnd(40)} t=${f.times.map(x => x.toFixed(2)).join(',')}  ${f.detail}${f.text ? '  "' + f.text.slice(0, 40) + '"' : ''}`);
    for (const e of pageErrors) console.log('  PAGEERROR ' + e);
    console.log(`text layout: ${errorCount} error(s), ${warningCount} warning(s), ${findings.filter(f => f.severity === 'info').length} transient -> ${path.relative(process.cwd(), OUT)}`);
  }
  process.exit(errorCount ? 1 : 0);
})().catch(e => {
  const msg = String(e && e.message || e);
  if (/3221225595|0xC0000409|STATUS_STACK_BUFFER_OVERRUN/i.test(msg)) console.error('Chrome crashed on launch (STATUS_STACK_BUFFER_OVERRUN): set PUPPETEER_EXECUTABLE_PATH to the system Chrome.');
  console.error(msg); process.exit(4);
});
