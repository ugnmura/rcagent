const pptxgen = require('pptxgenjs');
const fs = require('fs');
// Builds out/slides-with-notes.pptx: one full-bleed slide per rendered still (run `npm run slides` first), with
// each presenter's lines from docs/presentation/speakers.md as speaker notes.
// Usage (from presentation/): npm i --no-save pptxgenjs@3.12.0 && node scripts/pptx-notes.cjs
const path = require('path');
const root = path.join(__dirname, '..');
const [slidesDir = path.join(root, 'out/slides'), speakersMd = path.join(root, '../docs/presentation/speakers.md'),
  out = path.join(root, 'out/slides-with-notes.pptx')] = process.argv.slice(2);
const md = fs.readFileSync(speakersMd, 'utf8');

const section = (title) => {
  const i = md.indexOf('## ' + title);
  const rest = md.slice(i + 3);
  const end = rest.indexOf('\n## ');
  return end < 0 ? rest : rest.slice(0, end);
};
const quotes = (title) => section(title).split('\n').filter((l) => l.startsWith('> '))
  .map((l) => l.slice(2)).join(' ').split(' / ').map((s) => s.trim());
const closeLines = [...md.matchAll(/\| `s7-close-(.)\.mp4` \| . \| "(.*)" \|/g)].map((m) => m[2]);

const A = quotes('Presenter A: the reveal');
const roles = quotes('Presenter B: three roles');
const demo = quotes('Presenter B: live demo');
const bench = quotes('Presenter C: benchmarks');
if (A.length !== 13 || roles.length !== 5 || bench.length !== 6 || closeLines.length !== 3) throw new Error('speakers.md structure changed');

const note = (who, cue, lines) => `${who}${cue ? '  ·  ' + cue : ''}\n\n${lines.join('\n')}`;
const NOTES = [
  'No speaker. Intro card, 3 s. The phone call comes next.',
  note('Phone call (AI voices, dialog.mp3, no presenter)', 'Fallback if audio fails: Presenter A reads the three questions aloud', [
    'Engineer: Yes, I\'m looking at it. One node on Blue Gene/L, R30-M0-N9. Data TLB errors, fatal. Twenty-four thousand an hour.',
    'Team lead: Has this happened before?',
    'Engineer: I don\'t know. The log is millions of lines.',
    'Manager: How bad is it? Do we act tonight?',
    'Engineer: Give me a few hours.']),
  note('PRESENTER A', 'Look into the camera. Start quiet. Say the number rounded; the exact one is on screen', A.slice(0, 4)),
  note('PRESENTER A (continued)', '', A.slice(4, 6)),
  note('PRESENTER A (continued)', '', A.slice(6, 8)),
  note('PRESENTER A (continued)', 'Lift your energy on "So we flipped it"', A.slice(8)),
  note('PRESENTER B', 'Pause between the three roles so each column gets its moment', roles.slice(0, 4)),
  note('PRESENTER B (continued)', 'Talk to the audience, not to the screen', demo),
  note('PRESENTER B (continued)', 'Slow down: the two counts match line for line', roles.slice(4)),
  note('PRESENTER C', 'Name each design as it appears. The last line goes with the RCAEval result (96.3% first guess, 99.1% top three), which the video shows as a third shot', bench),
  note('ALL THREE', 'Look into the camera. C holds a beat after "Thank you!"',
    closeLines.map((l, i) => `${'ABC'[i]}: ${l}`)),
];

const ALT = ['Title: Making Sense of Logs, National AI Hackathon 2026, SchubKI x SereneDB',
  'The phone call on Blue Gene/L, Saturday 11 June 2005, as a dialog transcript',
  '152,229 fatal entries, one node, one evening', '4.7 million log lines in seven months',
  'Templating: 4.6 million lines become 320 templates', 'How it works: you, Claude, MCP tools, SereneDB, evidence Q46',
  'Three roles: engineer, team lead, manager each get a different answer; 152,734 = 152,734',
  'Live demo prompts for /engineer, /team-lead and /manager', 'Why you can trust the numbers: the Q46 SQL and 152,734 = 152,734',
  'Benchmarks: 7 fixed tools 93.5%, 18 fixed tools 92.9%, Drain3 + SQL 96.9% at $0.117 per answer',
  'Close: back to that phone call, every number traceable to a query, github.com/ugnmura/serenedb-extractor'];

const pres = new pptxgen();
pres.layout = 'LAYOUT_16x9';
pres.title = 'Making Sense of Logs';
pres.author = 'Team 68';
NOTES.forEach((n, i) => {
  const s = pres.addSlide();
  s.background = { color: '0B0D10' };
  s.addImage({ path: `${slidesDir}/Slide${i + 1}.png`, x: 0, y: 0, w: 10, h: 5.625, altText: ALT[i] });
  s.addNotes(n);
});
pres.writeFile({ fileName: out }).then((f) => console.log('wrote', f));
