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
	teamLead: 16,
	manager: 22,
};

/** Seconds at the end of the close during which the end card (slide 7) shows. */
export const END_CARD_SECONDS = 9;

/** Fixed-length scenes without an asset: the intro card before the cold open, the star gag at the very end. */
export const INTRO_SECONDS = 3;
export const STAR_SECONDS = 6;

/** Silence the facecam takes start and end with (handoff 3), excluded from subtitle timing. */
export const TAKE_PADDING_SECONDS = 1;
/** Ring before the first dialog line in dialog.mp3. */
export const DIALOG_LEAD_SECONDS = 2;

export type SceneId = 'intro' | 'star' | 'coldOpen' | 'reveal' | 'engineer' | 'teamLead' | 'manager' | 'evidence' | 'benchmarks' | 'close';

export type SceneTiming = {
	id: SceneId;
	label: string;
	/** Asset whose length sets the scene length; null for a fixed-length scene. */
	lengthFrom: AssetKey | null;
	frames: number;
	placeholder: boolean;
	/** Close only, when the joint take s7-close.mp4 is missing: the per-presenter clips, back to back. */
	parts?: ScenePart[];
};

export type ScenePart = {key: AssetKey; frames: number; placeholder: boolean};

/** The per-presenter close clips, in order, used when the joint take is missing. */
export const CLOSE_PARTS: AssetKey[] = ['s7a', 's7b', 's7c'];

const SCENES: {id: SceneId; label: string; lengthFrom: AssetKey | null; fixedSeconds?: number}[] = [
	{id: 'intro', label: '0  Intro card', lengthFrom: null, fixedSeconds: INTRO_SECONDS},
	{id: 'coldOpen', label: '1a Cold open', lengthFrom: 'dialog'},
	{id: 'reveal', label: '1b Reveal', lengthFrom: 's1'},
	{id: 'engineer', label: '2  Engineer', lengthFrom: 's2'},
	{id: 'teamLead', label: '3  Team lead', lengthFrom: 's3'},
	{id: 'manager', label: '4  Manager', lengthFrom: 's4'},
	{id: 'evidence', label: '5  Evidence', lengthFrom: 's5'},
	{id: 'benchmarks', label: '6  Benchmarks', lengthFrom: 's6'},
	{id: 'close', label: '7  Close', lengthFrom: 's7'},
	{id: 'star', label: '8  Star gag', lengthFrom: null, fixedSeconds: STAR_SECONDS},
];

export const secondsToFrames = (s: number) => Math.max(1, Math.ceil(s * FPS));

export const buildTimeline = (assets: ResolvedAssets): SceneTiming[] =>
	SCENES.map(({fixedSeconds, ...s}) => {
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
