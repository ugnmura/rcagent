import {bundle} from '@remotion/bundler';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

export const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

/** Bundle the Remotion project once; the result is a serve URL for selectComposition / renderStill. */
export const bundleProject = () =>
	bundle({
		entryPoint: path.join(root, 'src/index.ts'),
		publicDir: path.join(root, 'public'),
	});
