// Asset contract: docs/presentation/handoffs/README.md ("Asset contract").
// Every file lives in public/assets/. Until it exists, a labelled placeholder of `placeholderSeconds` is shown.

export type AssetKind = 'audio' | 'facecam' | 'recording';

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
	engineerRec: {file: 'engineer.mp4', kind: 'recording', placeholderSeconds: 40, target: '≤ 40 s'},
	teamLeadRec: {file: 'team-lead.mp4', kind: 'recording', placeholderSeconds: 35, target: '≤ 35 s'},
	managerRec: {file: 'manager.mp4', kind: 'recording', placeholderSeconds: 35, target: '≤ 35 s'},
	s1: {file: 's1-reveal.mp4', kind: 'facecam', placeholderSeconds: 40, target: '≤ 40 s'},
	s2: {file: 's2-engineer.mp4', kind: 'facecam', placeholderSeconds: 45, target: '≤ 45 s'},
	s3: {file: 's3-team-lead.mp4', kind: 'facecam', placeholderSeconds: 40, target: '≤ 40 s'},
	s4: {file: 's4-manager.mp4', kind: 'facecam', placeholderSeconds: 40, target: '≤ 40 s'},
	s5: {file: 's5-evidence.mp4', kind: 'facecam', placeholderSeconds: 35, target: '≤ 35 s'},
	s6: {file: 's6-benchmarks.mp4', kind: 'facecam', placeholderSeconds: 40, target: '≤ 40 s'},
	s7: {file: 's7-close.mp4', kind: 'facecam', placeholderSeconds: 25, target: '≤ 25 s'},
} as const satisfies Record<string, AssetSpec>;

export type AssetKey = keyof typeof ASSETS;

export const BENCHMARKS_FILE = 'benchmarks.json';

/** What calculateMetadata found for one asset. */
export type ResolvedAsset = {
	present: boolean;
	seconds: number;
};

export type ResolvedAssets = Record<AssetKey, ResolvedAsset>;
