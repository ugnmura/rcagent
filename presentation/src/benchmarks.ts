// Shape of public/assets/benchmarks.json (handoff 4). Numbers come only from that file.

export type Design = {
	name: string;
	/** Lower-case name for running text ("cheaper than the broad toolbox"). */
	short?: string;
	score_pct: number | null;
	usd_per_answer: number | null;
	ours: boolean;
};

export type Benchmarks = {
	final: boolean;
	footnote: string;
	source?: string;
	/** Sealed questions and runs per question; the scene's setup shot and answer grid use them. */
	questions?: number;
	runs?: number;
	designs: Design[];
};

export const EMPTY_BENCHMARKS: Benchmarks = {
	final: false,
	footnote: 'TODO: public/assets/benchmarks.json is missing',
	designs: [],
};

/** Every design has a score and a cost. Numbers show whenever this holds; `final: false` adds a PLACEHOLDER tag. */
export const hasNumbers = (b: Benchmarks) =>
	b.designs.length > 0 && b.designs.every((d) => d.score_pct !== null && d.usd_per_answer !== null);
