// Renders single frames of the talk as PNGs, for looking at a shot without the Studio.
// Usage: node scripts/stills.mjs name:frame [name:frame ...]  ->  out/name.png
import {renderStill, selectComposition} from '@remotion/renderer';
import {mkdir} from 'node:fs/promises';
import path from 'node:path';
import {bundleProject, root} from './bundle.mjs';

const args = process.argv.slice(2);
if (args.length === 0) {
	console.error('Usage: node scripts/stills.mjs name:frame [name:frame ...]');
	process.exit(1);
}
await mkdir(path.join(root, 'out'), {recursive: true});
const serveUrl = await bundleProject();
const composition = await selectComposition({serveUrl, id: 'Talk', logLevel: 'error'});
for (const arg of args) {
	const [name, frame] = arg.split(':');
	const output = path.join(root, 'out', `${name}.png`);
	await renderStill({composition, serveUrl, output, frame: Number(frame), imageFormat: 'png', logLevel: 'error'});
	console.log(`frame ${frame} -> ${path.relative(root, output)}`);
}
