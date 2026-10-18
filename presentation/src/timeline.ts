import type {AssetKey, ResolvedAssets} from './assets';

export const FPS = 30;
export const WIDTH = 1920;
export const HEIGHT = 1080;
/** Hard limit for the whole talk: 4:59. */
export const MAX_SECONDS = 299;

// ---- Tunables for handoff 5 (one constant per scene) ----

/** The split scene: silent hold between the manager's take (s4) and the evidence take (s5), where "all lit" lands. */
export const SPLIT_HOLD_SECONDS = 0.8;
/** Playback speed of roles.mp4 in the split's proof clip. */
export const PROOF_RATE = 3;

/** Seconds at the end of the close during which the end card (slide 7) shows. */
export const END_CARD_SECONDS = 9;

/** Fixed-length scenes without an asset: the intro card before the cold open, the star gag at the very end. */
export const INTRO_SECONDS = 3;
export const STAR_SECONDS = 6;

/** Silence the facecam takes start and end with (handoff 3), excluded from subtitle timing. */
export const TAKE_PADDING_SECONDS = 1;
/** Ring before the first dialog line in dialog.mp3. */
export const DIALOG_LEAD_SECONDS = 2;

export type SceneId = 'intro' | 'star' | 'coldOpen' | 'reveal' | 'split' | 'benchmarks' | 'close';

export type SceneTiming = {
	id: SceneId;
	label: string;
	/** Asset whose length sets the scene length; null for a fixed-length scene. */
	lengthFrom: AssetKey | null;
	frames: number;
	placeholder: boolean;
	/** The takes played back to back: the split (s2, s3, s4, hold, s5), and the close when s7-close.mp4 is missing. */
	parts?: ScenePart[];
};

export type ScenePart = {key: AssetKey; frames: number; placeholder: boolean};

/** The per-presenter close clips, in order, used when the joint take is missing. */
export const CLOSE_PARTS: AssetKey[] = ['s7a', 's7b', 's7c'];

/** The split's takes, in order: engineer (A), team lead (B), manager (C), evidence (B). The hold sits before s5. */
export const SPLIT_PARTS: AssetKey[] = ['s2', 's3', 's4', 's5'];

/** Start frame of each split part within the scene, including the hold before s5. */
export const splitStarts = (parts: ScenePart[]): number[] => {
	const hold = secondsToFrames(SPLIT_HOLD_SECONDS);
	let at = 0;
	return parts.map((p, i) => {
		if (i === parts.length - 1) at += hold;
		const from = at;
		at += p.frames;
		return from;
	});
};

const SCENES: {id: SceneId; label: string; lengthFrom: AssetKey | null; fixedSeconds?: number}[] = [
	{id: 'intro', label: '0  Intro card', lengthFrom: null, fixedSeconds: INTRO_SECONDS},
	{id: 'coldOpen', label: '1a Cold open', lengthFrom: 'dialog'},
	{id: 'reveal', label: '1b Reveal', lengthFrom: 's1'},
	{id: 'split', label: '2  Three roles', lengthFrom: 's2'},
	{id: 'benchmarks', label: '3  Benchmarks', lengthFrom: 's6'},
	{id: 'close', label: '4  Close', lengthFrom: 's7'},
	{id: 'star', label: '5  Star gag', lengthFrom: null, fixedSeconds: STAR_SECONDS},
];

export const secondsToFrames = (s: number) => Math.max(1, Math.ceil(s * FPS));

export const buildTimeline = (assets: ResolvedAssets): SceneTiming[] =>
	SCENES.map(({fixedSeconds, ...s}) => {
		if (s.id === 'split') {
			const parts = SPLIT_PARTS.map((key) => ({key, frames: secondsToFrames(assets[key].seconds), placeholder: !assets[key].present}));
			const starts = splitStarts(parts);
			return {
				...s,
				frames: starts[starts.length - 1] + parts[parts.length - 1].frames,
				placeholder: parts.some((p) => p.placeholder),
				parts,
			};
		}
		if (s.id === 'close' && !assets.s7.present) {
			const parts = CLOSE_PARTS.map((key) => ({
				key,
				frames: secondsToFrames(assets[key].seconds),
				placeholder: !assets[key].present,
			}));
			return {
				...s,
				frames: parts.reduce((a, p) => a + p.frames, 0),
				placeholder: parts.some((p) => p.placeholder),
				parts,
			};
		}
		return {
			...s,
			frames: secondsToFrames(s.lengthFrom ? assets[s.lengthFrom].seconds : (fixedSeconds ?? 1)),
			placeholder: s.lengthFrom ? !assets[s.lengthFrom].present : false,
		};
	});

export const totalFrames = (scenes: SceneTiming[]) => scenes.reduce((a, s) => a + s.frames, 0);

export const fmt = (frames: number) => {
	const s = frames / FPS;
	const m = Math.floor(s / 60);
	return `${m}:${(s - m * 60).toFixed(1).padStart(4, '0')}`;
};

/** Per-scene report, also used as the error message when the talk is too long. */
export const describeTimeline = (scenes: SceneTiming[], assets: ResolvedAssets): string => {
	const lines = scenes.flatMap((s) => [
		`  ${s.label.padEnd(14)} ${fmt(s.frames).padStart(6)}  ${s.lengthFrom === null ? 'fixed      ' : s.placeholder ? 'placeholder' : 'asset      '}  (${s.parts ? s.parts.map((p) => p.key).join(' + ') : (s.lengthFrom ?? 'timeline.ts')})`,
		...(s.parts ?? []).map(
			(p) => `    ${p.key.padEnd(12)} ${fmt(p.frames).padStart(6)}  ${p.placeholder ? 'placeholder' : 'asset      '}`,
		),
	]);
	const total = totalFrames(scenes);
	lines.push(`  ${'TOTAL'.padEnd(14)} ${fmt(total).padStart(6)}  limit ${fmt(MAX_SECONDS * FPS)}`);
	lines.push(`  ${'music.mp3'.padEnd(14)} ${assets.music.present ? 'present (loops under the talk)' : 'absent, optional (silence)'}`);
	return lines.join('\n');
};

export const assertWithinLimit = (scenes: SceneTiming[], assets: ResolvedAssets) => {
	if (totalFrames(scenes) > MAX_SECONDS * FPS) {
		throw new Error(
			`The talk is ${fmt(totalFrames(scenes))}, over the 4:59 limit. Shorten a take.\n${describeTimeline(scenes, assets)}`,
		);
	}
};

/**
 * Subtitle cue timing: cues share the spoken part of the scene in proportion to their length.
 * Returns [startFrame, endFrame) per cue, relative to the scene start.
 */
export const cueFrames = (
	cues: readonly string[],
	sceneFrames: number,
	leadSeconds = TAKE_PADDING_SECONDS,
	tailSeconds = TAKE_PADDING_SECONDS,
): [number, number][] => {
	const start = Math.round(leadSeconds * FPS);
	const end = Math.max(start + cues.length, sceneFrames - Math.round(tailSeconds * FPS));
	const weights = cues.map((c) => c.length + 12);
	const sum = weights.reduce((a, b) => a + b, 0);
	let acc = 0;
	return weights.map((w) => {
		const from = start + Math.round((acc / sum) * (end - start));
		acc += w;
		const to = start + Math.round((acc / sum) * (end - start));
		return [from, to];
	});
};
