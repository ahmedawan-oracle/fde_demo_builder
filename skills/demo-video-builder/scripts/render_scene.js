#!/usr/bin/env node
/**
 * render_scene.js — record a word-synced b-roll scene to 1920x1080 MP4, muxed with its VO (v2).
 *
 * Companion to gen_vo_multivoice.py + scenes/broll_*.html. Unlike render_bookend.js
 * (fixed duration, optional audio), this reads the VO length, starts the scene's clock
 * WITH the recording, and compensates the recorder's spin-up with a fixed audio delay —
 * the scene must use the same constant (DELAY = 0.45 s ↔ adelay=450) so every word-keyed
 * animation lands on its word. See references/broll-scenes.md for the full scene contract.
 *
 *   npm i puppeteer puppeteer-screen-recorder
 *   node render_scene.js scenes/opener.html vo_opener.mp3 out/seg1_opener.mp4
 */
const puppeteer = require('puppeteer');
const { PuppeteerScreenRecorder } = require('puppeteer-screen-recorder');
const { execFileSync } = require('child_process');
const path = require('path');
const fs = require('fs');

// Bundled Chromium if puppeteer downloaded one; else PUPPETEER_EXECUTABLE_PATH; else system Chrome.
async function chromePath() {
  if (process.env.PUPPETEER_EXECUTABLE_PATH) return process.env.PUPPETEER_EXECUTABLE_PATH;
  try { const p = await puppeteer.executablePath(); if (fs.existsSync(p)) return p; } catch (e) { /* fall through */ }
  return ['C:/Program Files/Google/Chrome/Application/chrome.exe',
          'C:/Program Files (x86)/Google/Chrome/Application/chrome.exe',
          '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
          '/usr/bin/google-chrome', '/usr/bin/chromium-browser'].find(fs.existsSync);
}

const [SCENE, VO, OUT] = process.argv.slice(2);
if (!SCENE || !VO || !OUT) {
  console.error('usage: node render_scene.js <scene.html> <vo.mp3> <out.mp4>');
  process.exit(1);
}
const VF = 'scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30,format=yuv420p';
const ENC = ['-c:v', 'libx264', '-preset', 'medium', '-crf', '20', '-pix_fmt', 'yuv420p', '-r', '30',
             '-c:a', 'aac', '-ar', '44100', '-ac', '2'];
const dur = f => parseFloat(execFileSync('ffprobe',
  ['-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', f]).toString().trim());

(async () => {
  const d = dur(VO);
  const b = await puppeteer.launch({
    headless: 'new', executablePath: await chromePath(),
    args: ['--no-sandbox', '--hide-scrollbars', '--force-device-scale-factor=1.5', '--window-size=1280,760'],
  });
  const p = await b.newPage();
  await p.setViewport({ width: 1280, height: 720, deviceScaleFactor: 1.5 });
  await p.goto('file://' + path.resolve(SCENE) + '?render', { waitUntil: 'networkidle0' });
  const raw = OUT.replace(/\.mp4$/, '_raw.mp4');
  const rec = new PuppeteerScreenRecorder(p, { fps: 30, videoFrame: { width: 1920, height: 1080 }, aspectRatio: '16:9' });
  await rec.start(raw);
  await p.evaluate(() => { window.__start && window.__start(); });  // clock starts WITH the recording
  await new Promise(r => setTimeout(r, (d + 2.4) * 1000));          // VO + fade-out tail
  await rec.stop(); await b.close();
  // adelay=450 must equal the scene's DELAY=0.45 — that pair is the sync contract.
  execFileSync('ffmpeg', ['-y', '-i', raw, '-i', VO,
    '-filter_complex', `[0:v]${VF}[v];[1:a]adelay=450:all=1,apad[a]`,
    '-map', '[v]', '-map', '[a]', '-shortest', ...ENC, OUT], { stdio: 'inherit' });
  console.log('DONE', OUT, dur(OUT) + 's');
  process.exit(0);
})().catch(e => { console.error(e); process.exit(1); });
