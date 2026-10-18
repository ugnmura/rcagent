// Shape of public/assets/benchmarks.json (handoff 4). Numbers come only from that file.

export type Design = {
	name: string;
	score_pct: number | null;
	usd_per_answer: number | null;
	ours: boolean;
};

export type Benchmarks = {
	final: boolean;
	footnote: string;
	source?: string;
	designs: Design[];
};

export const EMPTY_BENCHMARKS: Benchmarks = {
	final: false,
	footnote: 'TODO: public/assets/benchmarks.json is missing',
	designs: [],
};

/** Numbers are shown only when the file is final and every value is filled. */
export const isComplete = (b: Benchmarks) =>
	b.final && b.designs.length > 0 && b.designs.every((d) => d.score_pct !== null && d.usd_per_answer !== null);
