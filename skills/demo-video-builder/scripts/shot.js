#!/usr/bin/env node
/**
 * shot.js — QA still of a b-roll scene at time T, via the scene's window.__seek(t) (v2).
 *
 * Review composition/word-sync at key beats BEFORE spending a full render:
 *   node shot.js scenes/opener.html 12 qa/opener_12.png
 *
 * The scene must implement __seek(t) (see references/broll-scenes.md). The double-seek
 * lets CSS transitions settle so the still matches what the render will show.
 */
const puppeteer = require('puppeteer');
const path = require('path');
const fs = require('fs');

async function chromePath() {
  if (process.env.PUPPETEER_EXECUTABLE_PATH) return process.env.PUPPETEER_EXECUTABLE_PATH;
  try { const p = await puppeteer.executablePath(); if (fs.existsSync(p)) return p; } catch (e) { /* fall through */ }
  return ['C:/Program Files/Google/Chrome/Application/chrome.exe',
          'C:/Program Files (x86)/Google/Chrome/Application/chrome.exe',
          '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
          '/usr/bin/google-chrome', '/usr/bin/chromium-browser'].find(fs.existsSync);
}

const [SCENE, TSTR, OUT] = process.argv.slice(2);
if (!SCENE || !TSTR || !OUT) {
  console.error('usage: node shot.js <scene.html> <t seconds> <out.png>');
  process.exit(1);
}
const T = parseFloat(TSTR);

(async () => {
  const b = await puppeteer.launch({
    headless: 'new', executablePath: await chromePath(),
    args: ['--no-sandbox', '--hide-scrollbars', '--force-device-scale-factor=1.5', '--window-size=1280,760'],
  });
  const p = await b.newPage();
  await p.setViewport({ width: 1280, height: 720, deviceScaleFactor: 1.5 });
  await p.goto('file://' + path.resolve(SCENE) + '?render', { waitUntil: 'networkidle0' });
  await p.evaluate(t => { window.__seek(t); }, T);
  await new Promise(r => setTimeout(r, 700));      // let CSS transitions settle
  await p.evaluate(t => { window.__seek(t); }, T); // re-seek so canvas matches settled DOM
  await new Promise(r => setTimeout(r, 120));
  await p.screenshot({ path: OUT });
  await b.close();
  console.log('SHOT', T, OUT);
  process.exit(0);
})().catch(e => { console.error(e); process.exit(1); });
