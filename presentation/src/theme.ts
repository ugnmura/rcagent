import {loadFont as loadInter} from '@remotion/google-fonts/Inter';
import {loadFont as loadMono} from '@remotion/google-fonts/JetBrainsMono';

const inter = loadInter('normal', {weights: ['400', '600', '800'], subsets: ['latin']});
const mono = loadMono('normal', {weights: ['400', '600'], subsets: ['latin']});

export const font = {
	sans: inter.fontFamily,
	/** Only for SQL, tool calls and node names. */
	mono: mono.fontFamily,
};

export const color = {
	bg: '#0d1117',
	panel: '#161b22',
	line: '#30363d',
	text: '#e6edf3',
	muted: '#9aa4af',
	/** The one accent: "ours" and highlighted numbers. */
	accent: '#f5a524',
	placeholder: '#ff5c8a',
};

export const size = {
	title: 64,
	body: 44,
	small: 40,
	subtitle: 46,
};

/** Room kept free at the bottom of a slide in the video for subtitles and the facecam corner. */
export const VIDEO_BOTTOM_RESERVE = 250;
export const FACECAM_CORNER = {size: 230, margin: 44};
