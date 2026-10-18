// Prints each scene's length and the total, using the same calculateMetadata the render uses.
// Fails (exit 1) if the talk is over 4:59 or an asset cannot be read.
import {selectComposition} from '@remotion/renderer';
import {bundleProject} from './bundle.mjs';

const serveUrl = await bundleProject();
try {
	const comp = await selectComposition({serveUrl, id: 'Talk', logLevel: 'error'});
	console.log(`Scene lengths (${comp.fps} fps):\n${comp.props.report}`);
	console.log(`OK: ${comp.durationInFrames} frames = ${(comp.durationInFrames / comp.fps).toFixed(2)} s`);
} catch (e) {
	console.error(`\nCHECK FAILED\n${e.message}`);
	process.exit(1);
}
