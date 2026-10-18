// Shape of public/assets/benchmarks.json (handoff 4). Numbers come only from that file.

export type Design = {
	name: string;
	/** The design as a step of the story ("Start small", "More tools", "Add Drain3"); designs are listed in that order. */
	step?: string;
	/** Stages between question and answer, drawn as chips; `added` names the chip that is new in this step. */
	pipeline?: string[];
	added?: string;
	/** One line under the name: how the design answers a question. */
	detail?: string;
	/** Name for running text ("cheaper per answer than 18 fixed tools"). */
	short?: string;
	score_pct: number | null;
	usd_per_answer: number | null;
	ours: boolean;
};

/** RCAEval root-cause result for the metric and trace tools (benchmarks.json `rca`). */
export type Rca = {
	final: boolean;
	title: string;
	source: string;
	ac1_pct: number;
	ac3_pct: number;
	logs_only_pct: number;
	with_metrics_pct: number;
	logs_only_usd: number;
	with_metrics_usd: number;
	compare_note: string;
	report: string;
};

export type Benchmarks = {
	final: boolean;
	footnote: string;
	source?: string;
	/** Sealed questions and runs per question; the scene's setup shot and answer grid use them. */
	questions?: number;
	runs?: number;
	designs: Design[];
	rca?: Rca;
};

export const EMPTY_BENCHMARKS: Benchmarks = {
	final: false,
	footnote: 'TODO: public/assets/benchmarks.json is missing',
	designs: [],
};

/** Every design has a score and a cost. Numbers show whenever this holds; `final: false` adds a PLACEHOLDER tag. */
export const hasNumbers = (b: Benchmarks) =>
	b.designs.length > 0 && b.designs.every((d) => d.score_pct !== null && d.usd_per_answer !== null);
