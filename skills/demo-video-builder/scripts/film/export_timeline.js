/* export_timeline.js — cut times and the narration clock for build/QA tools.
     node export_timeline.js scenes/timing_film_data.js scenes/shots.js  → out/timeline.json
   A cut = FILM.openEnd, FILM.close and every shot start that is not a `seam` hand-off. */
const path = require('path'), fs = require('fs');
const [timing, shots] = process.argv.slice(2);
global.window = global;
const here = path.dirname(process.argv[1]);
require(path.resolve(here, 'scenes/lib/grammar.js'));
global.TX = require(path.resolve(here, 'scenes/lib/timeline.js')).load(timing);
require(path.resolve(here, 'scenes/lib/footage.js'));
require(path.resolve(shots));
const F = global.FILM || {}, SH = global.SHOTS || [];
const cuts = [F.openEnd, F.close].concat(SH.filter(s => !s.seam).map(s => s.t0)).filter(x => typeof x === 'number')
  .map(x => +x.toFixed(3)).filter((v, i, a) => a.indexOf(v) === i).sort((a, b) => a - b);
fs.mkdirSync(path.resolve(here, 'out'), { recursive: true });
const out = { total: TX.total, cuts: cuts, phases: TX.PHASES.phases };
fs.writeFileSync(path.resolve(here, 'out/timeline.json'), JSON.stringify(out, null, 1));
console.log('total ' + TX.total.toFixed(2) + ' s | ' + cuts.length + ' cuts -> out/timeline.json');
