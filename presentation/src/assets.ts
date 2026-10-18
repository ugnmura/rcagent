// Asset contract: docs/presentation/handoffs/README.md ("Asset contract").
// Every file lives in public/assets/. Until it exists, a labelled placeholder of `placeholderSeconds` is shown.

export type AssetKind = 'audio' | 'facecam' | 'recording' | 'music';

export type AssetSpec = {
	file: string;
	kind: AssetKind;
	/** Length used while the file is missing (the target length from the contract / handoff 3). */
	placeholderSeconds: number;
	/** Human-readable target from the contract, shown on the placeholder. */
	target: string;
};

export const ASSETS = {
	dialog: {file: 'dialog.mp3', kind: 'audio', placeholderSeconds: 20, target: '18–24 s'},
	/** One terminal recording of the three role prompts, played sped up as the split's proof clip. */
	rolesRec: {file: 'roles.mp4', kind: 'recording', placeholderSeconds: 18, target: 'any length (played ~3×)'},
	s1: {file: 's1-reveal.mp4', kind: 'facecam', placeholderSeconds: 40, target: '≤ 40 s'},
	/** Presenter B's single take for the three roles, all in parallel. */
	s2: {file: 's2-roles.mp4', kind: 'facecam', placeholderSeconds: 30, target: '≤ 30 s'},
	s6: {file: 's6-benchmarks.mp4', kind: 'facecam', placeholderSeconds: 20, target: '≤ 22 s'},
	s7: {file: 's7-close.mp4', kind: 'facecam', placeholderSeconds: 25, target: '≤ 25 s'},
	/** Used only while s7-close.mp4 (the joint take) is missing: one close clip per presenter, back to back. */
	s7a: {file: 's7-close-a.mp4', kind: 'facecam', placeholderSeconds: 8, target: '≤ 8 s'},
	s7b: {file: 's7-close-b.mp4', kind: 'facecam', placeholderSeconds: 8, target: '≤ 8 s'},
	s7c: {file: 's7-close-c.mp4', kind: 'facecam', placeholderSeconds: 8, target: '≤ 8 s'},
	/** Optional music bed under the whole talk (loops, low, ducked under voices). Missing = silence, no placeholder. */
	music: {file: 'music.mp3', kind: 'music', placeholderSeconds: 0, target: 'optional, any length (loops)'},
} as const satisfies Record<string, AssetSpec>;

export type AssetKey = keyof typeof ASSETS;

export const BENCHMARKS_FILE = 'benchmarks.json';

/** What calculateMetadata found for one asset. */
export type ResolvedAsset = {
	present: boolean;
	seconds: number;
};

export type ResolvedAssets = Record<AssetKey, ResolvedAsset>;
