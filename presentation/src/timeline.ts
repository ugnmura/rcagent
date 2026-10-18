import type {AssetKey, ResolvedAssets} from './assets';

export const FPS = 30;
export const WIDTH = 1920;
export const HEIGHT = 1080;
/** Hard limit for the whole talk: 4:59. */
export const MAX_SECONDS = 299;

// ---- Tunables for handoff 5 (one constant per scene) ----

/** Seconds the slide shows before the screen recording takes over (the first quote of the section). */
export const SLIDE_SECONDS: Record<'engineer' | 'teamLead' | 'manager', number> = {
	engineer: 20,
	teamLead: 12,
	manager: 22,
};

/** Seconds at the end of the close during which the end card (slide 7) shows. */
export const END_CARD_SECONDS = 9;

/** Silence the facecam takes start and end with (handoff 3), excluded from subtitle timing. */
export const TAKE_PADDING_SECONDS = 1;
/** Ring before the first dialog line in dialog.mp3. */
export const DIALOG_LEAD_SECONDS = 2;

export type SceneId = 'coldOpen' | 'reveal' | 'engineer' | 'teamLead' | 'manager' | 'evidence' | 'benchmarks' | 'close';

export type SceneTiming = {
	id: SceneId;
	label: string;
	/** Asset whose length sets the scene length. */
	lengthFrom: AssetKey;
	frames: number;
	placeholder: boolean;
};

const SCENES: {id: SceneId; label: string; lengthFrom: AssetKey}[] = [
	{id: 'coldOpen', label: '1a Cold open', lengthFrom: 'dialog'},
	{id: 'reveal', label: '1b Reveal', lengthFrom: 's1'},
	{id: 'engineer', label: '2  Engineer', lengthFrom: 's2'},
	{id: 'teamLead', label: '3  Team lead', lengthFrom: 's3'},
	{id: 'manager', label: '4  Manager', lengthFrom: 's4'},
	{id: 'evidence', label: '5  Evidence', lengthFrom: 's5'},
	{id: 'benchmarks', label: '6  Benchmarks', lengthFrom: 's6'},
	{id: 'close', label: '7  Close', lengthFrom: 's7'},
];

export const secondsToFrames = (s: number) => Math.max(1, Math.ceil(s * FPS));

export const buildTimeline = (assets: ResolvedAssets): SceneTiming[] =>
	SCENES.map((s) => ({
		...s,
		frames: secondsToFrames(assets[s.lengthFrom].seconds),
		placeholder: !assets[s.lengthFrom].present,
	}));

export const totalFrames = (scenes: SceneTiming[]) => scenes.reduce((a, s) => a + s.frames, 0);

export const fmt = (frames: number) => {
	const s = frames / FPS;
	const m = Math.floor(s / 60);
	return `${m}:${(s - m * 60).toFixed(1).padStart(4, '0')}`;
};

/** Per-scene report, also used as the error message when the talk is too long. */
export const describeTimeline = (scenes: SceneTiming[], assets: ResolvedAssets): string => {
	const lines = scenes.map(
		(s) =>
			`  ${s.label.padEnd(14)} ${fmt(s.frames).padStart(6)}  ${s.placeholder ? 'placeholder' : 'asset      '}  (${s.lengthFrom})`,
	);
	const total = totalFrames(scenes);
	lines.push(`  ${'TOTAL'.padEnd(14)} ${fmt(total).padStart(6)}  limit ${fmt(MAX_SECONDS * FPS)}`);
	const warnings = recordingWarnings(scenes, assets);
	return [...lines, ...warnings.map((w) => `  WARNING: ${w}`)].join('\n');
};

const RECORDING_SLOTS: {scene: SceneId; rec: AssetKey; split: number}[] = [
	{scene: 'engineer', rec: 'engineerRec', split: SLIDE_SECONDS.engineer},
	{scene: 'teamLead', rec: 'teamLeadRec', split: SLIDE_SECONDS.teamLead},
	{scene: 'manager', rec: 'managerRec', split: SLIDE_SECONDS.manager},
];

/** A real recording longer than its slot is cut at the end of the scene; say so. */
export const recordingWarnings = (scenes: SceneTiming[], assets: ResolvedAssets): string[] =>
	RECORDING_SLOTS.flatMap(({scene, rec, split}) => {
		const t = scenes.find((s) => s.id === scene)!;
		const slot = t.frames / FPS - split;
		const a = assets[rec];
		if (a.present && a.seconds > slot + 0.05) {
			return [`${rec} is ${a.seconds.toFixed(1)} s but its slot is ${slot.toFixed(1)} s; the end is cut. Tune SLIDE_SECONDS.${scene}.`];
		}
		return [];
	});

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
