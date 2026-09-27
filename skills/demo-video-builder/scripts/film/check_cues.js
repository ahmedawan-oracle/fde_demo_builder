/* check_cues.js — every wt('phase','word') cue in the film must resolve to a real spoken word; a cue that
   silently falls back to its phase start is a sync bug waiting to happen.
     node check_cues.js scenes/timing_film_data.js scenes/shots.js scenes/film.html [more files…]
   Also checks highlight cues (HL[clip][i].cue = ['phase','word']) found in the shot file. Exit 1 on any miss. */
const fs = require('fs'), path = require('path');
const [timing, ...files] = process.argv.slice(2);
if (!timing || !files.length) { console.error('usage: node check_cues.js <timing_data.js> <file> [file…]'); process.exit(2); }
const T = require(path.resolve(path.dirname(process.argv[1]), 'scenes/lib/timeline.js')).load(timing);
const re = /wt\(\s*'([A-Za-z0-9_]+)'\s*,\s*(?:'([^']*)'|"([^"]*)")/g;
let bad = 0, n = 0;
const miss = (where, ph, w) => {
  const list = T.WORDS[ph];
  if (!list) { console.log('MISSING PHASE   ' + where + '  ' + ph); return 1; }
  if (!list.some(x => T.norm(x.w) === T.norm(w))) {
    console.log('UNRESOLVED CUE  ' + where + '  wt(' + ph + ', ' + w + ')\n                phase words: ' + list.map(x => x.w).join(' '));
    return 1;
  }
  return 0;
};
for (const f of files) {
  const src = fs.readFileSync(f, 'utf8'); let m;
  while ((m = re.exec(src))) { n++; bad += miss(f, m[1], m[2] !== undefined ? m[2] : m[3]); }
  const hr = /cue:\s*\[\s*'([A-Za-z0-9_]+)'\s*,\s*'([^']*)'/g;
  while ((m = hr.exec(src))) { n++; bad += miss(f + ' (highlight)', m[1], m[2]); }
}
console.log(bad ? 'FAIL ' + bad + ' of ' + n + ' cues' : 'OK ' + n + ' cues all resolve');
process.exit(bad ? 1 : 0);
