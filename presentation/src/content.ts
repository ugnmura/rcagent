// Every text and number on screen. Source of truth: docs/presentation/script.md.
// Each number names where it comes from: "WI" = docs/worked-investigation.md (section, transcript step),
// "script" = docs/presentation/script.md. Benchmark numbers come only from public/assets/benchmarks.json.
// Subtitle cues are the script's quotes, word for word, cut into readable pieces.

export const REPO_URL = 'github.com/ugnmura/serenedb-extractor';

// ---------------------------------------------------------------- presenters
export type PresenterId = 'A' | 'B' | 'C';
export type Presenter = {id: PresenterId; name: string; role?: string};

/** Placeholder names; fill in the real names (and an optional role line) here. */
export const presenters: Record<PresenterId, Presenter> = {
	A: {id: 'A', name: 'Presenter A'},
	B: {id: 'B', name: 'Presenter B'},
	C: {id: 'C', name: 'Presenter C'},
};

/** Who speaks in which facecam take: A the reveal, B the three roles, C the benchmarks. The close s7 is all three
 * (one joint take, or s7a/b/c). */
export const sectionPresenter = {
	s1: 'A',
	s2: 'B',
	sDemo: 'B',
	s6: 'C',
	s7a: 'A',
	s7b: 'B',
	s7c: 'C',
} as const satisfies Partial<Record<string, PresenterId>>;

/** The take in which each presenter first appears; their name tag shows there once. */
export const firstAppearance = {s1: 'A', s2: 'B', s6: 'C'} as const;

export const presenterOf = (assetKey: string): Presenter | null => {
	const id = (sectionPresenter as Record<string, PresenterId | undefined>)[assetKey];
	return id ? presenters[id] : null;
};

// ---------------------------------------------------------------- 0 intro card
export const intro = {
	event: 'National AI Hackathon 2026',
	// Logos: public/assets/logos/SOURCES.md. SchubKI has no logo file; its wordmark is text.
	schubki: {first: 'Schub', accent: 'KI', gold: '#D3A43F'},
	sereneLogo: 'assets/logos/serenedb-on-dark.svg',
	schubkiIcon: 'assets/logos/schubki-icon.png',
};

export const DRAMATIZATION_LABEL = 'Dramatization: real log data';

// ---------------------------------------------------------------- 1a cold open (slide 1)
export const coldOpen = {
	caption: 'Lawrence Livermore National Laboratory · Blue Gene/L · Saturday, 11 June 2005, 17:17',
	/** The caption as the three typed lines of the film title. */
	captionLines: ['Lawrence Livermore National Laboratory', 'Blue Gene/L', 'Saturday, 11 June 2005 · 17:17'],
	// Background log scroll: only real BGL lines, as quoted in docs/worked-investigation-transcript.md
	// (step 5, rows #222714 to #222719). Lines after the quoted ones repeat the run's message without a
	// timestamp, because their timestamps are not quoted (WI §1: 152,182 such entries on this node, step 3).
	log: {
		node: 'R30-M0-N9-C:J16-U01',
		level: 'FATAL',
		component: 'KERNEL',
		quoted: [
			{ts: '2005-06-11 17:17:44', message: 'machine check interrupt (bit=0x10): L2 DCU read error'},
			{ts: '2005-06-11 17:17:44', message: 'data TLB error interrupt'},
			{ts: '2005-06-11 17:17:45', message: 'data TLB error interrupt'},
			{ts: '2005-06-11 17:17:45', message: 'data TLB error interrupt'},
			{ts: '2005-06-11 17:17:45', message: 'data TLB error interrupt'},
			{ts: '2005-06-11 17:17:45', message: 'data TLB error interrupt'},
		],
		runMessage: 'data TLB error interrupt',
	},
	/** Start and end of each dialog line in public/assets/dialog.mp3, in seconds (measured when the file was stitched and checked with whisper.cpp:
	 * 2 s lead while the caption types, 0.35 s between lines). Used for the subtitles while that file is present. */
	dialogSeconds: [
		[2.0, 13.72],
		[14.07, 15.59],
		[15.94, 20.7],
		[21.05, 23.93],
		[24.28, 26.28],
	] as [number, number][],
	// script.md, dialog table. Speaker labels are the table's "Voice" column, shortened.
	dialog: [
		{
			speaker: 'Engineer',
			// R30-M0-N9: WI §1 [step 2]; "Twenty-four thousand an hour": WI §1 [step 4] (about 24,000 entries per hour)
			text: "Yes, I'm looking at it. One node on Blue Gene/L, R30-M0-N9. Data TLB errors, fatal. Twenty-four thousand an hour.",
		},
		{speaker: 'Team lead', text: 'Has this happened before?'},
		{speaker: 'Engineer', text: "I don't know. The log is millions of lines."},
		{speaker: 'Manager', text: 'How bad is it? Do we act tonight?'},
		{speaker: 'Engineer', text: 'Give me a few hours.'},
	],
};

// ---------------------------------------------------------------- 1b reveal (slide 1, continued)
export const reveal = {
	// 152,229: WI §1 [step 2]
	headline: ['152,229 fatal entries', 'one node', 'one evening'],
	/** Video shot: the counter rolls to this value; the words fade in under it. */
	counter: {value: '152,229', label: 'fatal entries · one node · one evening'}, // WI §1 [step 2]
	// 4.7 million: WI intro (4,747,963 BGL entries, 2005-06-03 to 2006-01-04); "seven months": script
	fact: {value: '4.7 million', label: 'log lines · seven months'},
	flow: ['Question', 'Agent picks a tool', 'SereneDB searches / counts', 'Evidence', 'Answer'],
	cues: [
		'Saturday, 11 June 2005, Lawrence Livermore National Laboratory.',
		'Blue Gene/L, then the fastest supercomputer on Earth.',
		// 152,229: WI §1 [step 2]
		'That one node wrote 152,229 fatal entries in a single evening.',
		'Tonight it could be CLAIX, here in Aachen.',
		// 4.7 million: WI intro (4,747,963 BGL entries, 2005-06-03 to 2006-01-04)
		'That machine wrote 4.7 million log lines in seven months.',
		'No human reads that. No AI prompt holds it either.',
		'So we flipped it. The AI does not read the logs.',
		'SereneDB searches and counts every line, exactly.',
		'Claude asks the questions and explains the answers,',
		'and every number carries the query that proved it.',
		"Let's answer that phone call.",
	],
	/** Index of the cue from which the headline card shows (the cue that says 152,229). */
	headlineFromCue: 2,
	/** Index of the cue from which the 4.7 million shot shows. */
	factFromCue: 4,
	/** Index of the cue from which the flow line shows ("So we flipped it."). */
	flowFromCue: 6,
};

// ---------------------------------------------------------------- 2 engineer (slide 2)
export const engineer = {
	title: 'Engineer: what failed, and what happened just before?',
	chapter: {title: 'The engineer', question: 'What failed? What came just before?'},
	prompt: '/engineer What failed on BGL on 11 June 2005, and what happened just before?',
	recordingCue: 'Pause on the search_logs result, then on the get_context timeline.',
	node: 'R30-M0-N9-C:J16-U01', // WI §1 [step 2]
	share: {
		part: '152,229', // WI §1 [step 2]
		whole: '855,501', // WI §1 [step 2]
		pct: '17.8%', // WI §1 [step 2]
	},
	message: 'data TLB error interrupt',
	window: '17:17 – 23:39', // WI §1 [step 4]: 17:17:44 to 23:39:32
	before: 'L2 DCU read error, same second', // WI §1 [step 5]
	/** The timeline shot: one line, then the flood. */
	beforeLine: {time: '17:17:44', text: 'L2 cache read error'}, // WI §1 [step 5]; words as spoken in the script
	runTimes: {from: '17:17', to: '23:39'}, // WI §1 [step 4]
	rarity: '3 times in 7 months · twice on this node', // WI §1 [step 7]
	hypothesis: 'Hypothesis: a failing L2 cache. Next check: processor diagnostics.',
	cues: [
		'The engineer asks: what failed?',
		'Claude counts fatal entries by node, over the whole log.',
		'One node: R30-M0-N9-C:J16-U01.',
		'152,229 of 855,501 fatal entries, 17.8 percent.',
		'Full-text search names it: "data TLB error interrupt",',
		'non-stop from 17:17 to 23:39.',
		'And just before? get_context shows one line in the same second:',
		'an L2 cache read error.',
		'Three times in seven months, twice on this node.',
		'The hypothesis is a failing L2 cache, labelled as a hypothesis.',
		'The next check: processor diagnostics.',
		'If they fail, replace the card.',
		'If they pass, look at the job that ran at 17:17.',
	],
};

// ---------------------------------------------------------------- 3 team lead (slide 3)
export const teamLead = {
	title: 'Team lead: what keeps coming back?',
	chapter: {title: 'The team lead', question: 'What keeps coming back?'},
	// WI §2 "The numbers" table [step 9]: BGL entries at level FATAL, by team, whole corpus; top two teams only
	// (the next, Control System, has 3 FATAL and would read as an empty bar).
	fatalBars: [
		{team: 'Node OS', value: '626,756'},
		{team: 'HPC Applications', value: '228,536'},
	],
	fatalBarsLabel: 'BGL fatal entries, by team',
	// WI §2 [step 21]: "Link has been severed" on 22 of 31 days in December, +4% against November
	persistent: {message: 'Link has been severed', days: 22, of: 31, trend: '+4%', trendLabel: 'not falling'},
	first: {label: 'Investigate first', team: 'HPC Applications'},
	prompt: '/team-lead Which problems keep recurring across BGL and OpenStack, and what should we look at first?',
	recordingCue: 'Pause on the count_logs table by team and level, then on the trend result.',
	// WI §2 "The numbers" table [step 9]: entries by team and level, whole corpus.
	table: [
		{team: 'Node OS', log: 'BGL', levels: '626,756 FATAL · 3,698,211 INFO'},
		{team: 'HPC Applications', log: 'BGL', levels: '228,536 FATAL'},
		{team: 'Control System', log: 'BGL', levels: '88,529 ERROR · 49 FAILURE · 3 FATAL'},
		{team: 'Hardware Reliability', log: 'BGL', levels: '23,825 ERROR · 19,213 SEVERE · 23,356 WARNING · 1,665 FAILURE'},
		{team: 'Virtualization', log: 'OpenStack', levels: '3,071 WARNING'},
		{team: 'Compute Service', log: 'OpenStack', levels: '45 WARNING · 8 ERROR'},
		{team: 'Identity & Access', log: 'OpenStack', levels: '2 CRITICAL · 2 ERROR · 2 WARNING'},
	],
	highlight: {
		message: '"Link has been severed"',
		// WI §2 [step 21]: 22 of 31 days in December, +4% against November
		days: '22 of 31 days',
		detail: 'in December · not falling',
		first: 'Investigate first: HPC Applications',
	},
	cues: [
		'The team lead asks: what keeps coming back?',
		'That needs counts, not examples:',
		'every entry in both datasets, grouped by team.',
		'Then December against November.',
		'The winner is not the biggest number. It is the most persistent:',
		'"Link has been severed" on the I/O sockets,',
		'on 22 of 31 days, and not falling.',
		'Investigate first: HPC Applications.',
		'Second: Node OS confirms the 14 June event.',
	],
};

// ---------------------------------------------------------------- 4 manager (slide 4)
export const manager = {
	title: 'Manager: what do we act on first?',
	chapter: {title: 'The manager', question: 'What do we act on first?'},
	// WI §3, ranked list; labels shortened to at most five words, owners as in WI §3.
	cards: [
		{label: 'Failing job launches, rising', owner: 'HPC Applications', counter: 91}, // +91%: WI §3 item 1 [step 21]
		{label: 'Broken compute-to-I/O links', owner: 'HPC Applications'},
		{label: 'One faulty node', owner: 'Node OS'},
		{label: 'Machine-wide burst, 14 June', owner: 'Node OS'}, // WI §3 item 4 [step 13]
		{label: 'Cloud warnings only', owner: 'Virtualization · Cloud API'},
	],
	limit: "Logs don't measure downtime or cost.",
	prompt: '/manager What should we prioritise from these logs?',
	recordingCue: 'Hold on the ranked list.',
	// WI §3, ranked list. Only numbers the script speaks are shown.
	risks: [
		// +91%: WI §3 item 1 [step 21]
		{risk: 'Failing job launches, rising (+91% month over month)', owner: 'HPC Applications'},
		// 22 of 31 days: WI §3 item 2 [step 21]
		{risk: 'Broken compute-to-I/O links, 22 of 31 days', owner: 'HPC Applications'},
		{risk: 'One faulty node: out of service until diagnostics pass', owner: 'Node OS'},
		{risk: 'Machine-wide fault burst on 14 June', owner: 'Node OS'},
		{risk: 'Cloud warnings (warnings only)', owner: 'Virtualization, Cloud API'},
	],
	honest: 'These logs do not measure downtime or cost, so the answer does not invent them.',
	cues: [
		'The manager gets no node names.',
		'Five ranked risks, each with an owner and one action.',
		'First: failing job launches, up 91 percent month over month,',
		'"permission denied" on program images. Owner: HPC Applications.',
		'Second: the broken links.',
		'Third: the faulty node, out of service until it passes diagnostics.',
		'And one honest line: these logs do not measure downtime or cost,',
		'so the answer does not invent them.',
	],
};

// ---------------------------------------------------------------- 5 evidence (slide 5)
export const evidence = {
	title: 'Why you can trust the numbers',
	// Handle as named in the script. The regenerated transcript numbers this call Q127 (step 23); a live session
	// assigns its own handle, so handoff 5 replaces "Q46" with the one in the recording.
	handle: 'Q46',
	call: "count_logs(log_tables=['bgl'], group_by=['level'], text='data TLB error interrupt')",
	// Exact SQL: docs/worked-investigation-transcript.md, step 23, Q127.5
	sql: `SELECT k0, count(*) AS n FROM (SELECT 1 AS one, coalesce(("level")::varchar, '(none)') AS k0 FROM extractor.lt_bgl WHERE TRUE AND TRUE AND ("message")::varchar ILIKE '%data TLB error interrupt%' ESCAPE '\\') GROUP BY k0`,
	measured: 'exact count · every entry in scope · no sampling',
	tool: 'count_logs',
	/** Readable excerpt of `sql` (same query, middle elided). */
	sqlExcerpt: [
		'SELECT k0, count(*) AS n FROM (',
		'  SELECT … "level" AS k0 FROM extractor.lt_bgl',
		"  WHERE \"message\" ILIKE '%data TLB error interrupt%'",
		') GROUP BY k0',
	],
	snapCaption: "full-text count = BGL's own labels",
	left: {value: '152,734', label: 'full-text count of "data TLB error interrupt" over all of BGL'}, // WI [step 23]
	right: {value: '152,734', label: "lines BGL's own alert labels mark KERNDTLB"}, // WI [step 24]
	cues: [
		'Every number carries a citation, like Q46.',
		'show_evidence returns the exact SQL, its time and its rows.',
		'And we checked against ground truth:',
		'a full-text count of "data TLB error interrupt" over all of BGL gives 152,734.',
		"BGL's own alert labels: exactly 152,734.",
		'Real counts, not a sample.',
	],
};

// ---------------------------------------------------------------- 6 benchmarks (slide 6)
export const benchmarks = {
	title: 'Same questions, graded blind',
	todo: 'Numbers pending: final benchmark run',
	placeholder: 'PLACEHOLDER NUMBERS · benchmarks still running',
	setup: {questions: 'sealed questions', runs: 'runs each', blind: 'graded blind'},
	costTitle: 'Cost per answer',
	andTop: 'with the top score:',
	perAnswer: 'per answer',
	rca: {ac1: 'right root cause, first guess', ac3: 'in the top three', logsOnly: 'logs only', withMetrics: 'with metric + trace tools'},
	cheaper: 'cheaper per answer than',
	cues: [
		'How did we get here? Same sealed questions, graded blind, at every step.',
		'We started small: seven fixed tools.',
		'Then more tools: eighteen. A better score, but every answer cost twice as much.',
		'Then Drain3: it finds the log templates when a question comes in, and Claude gets eight core tools plus run_sql.',
		'The best score, and the cheapest answer: three times cheaper.',
		'And it is not only logs. On 116 held-out microservice incidents it names the right root cause first 96 percent of the time.',
	],
};

// ---------------------------------------------------------------- 7 close (slide 7)
export const close = {
	title: 'Back to that phone call',
	answers: [
		{role: 'Engineer', line: 'a cause to check, not a scroll bar'},
		{role: 'Team lead', line: 'the pattern'},
		{role: 'Manager', line: 'the priority'},
	],
	traceable: 'Every number is traceable to a query.',
	cardLine: 'Every number traceable to a query',
	cues: [
		'So, back to that phone call.',
		'The engineer gets a cause to check, not a scroll bar.',
		'The team lead gets the pattern. The manager gets the priority.',
		'And every number is traceable to a query. Thank you.',
	],
};

// ---------------------------------------------------------------- 2 three roles, one split (s2, presenter B, one take)
// Replaces the separate engineer, team lead, manager and evidence scenes. Three minimal cards (icon, role, a short
// question); each role takes centre stage in turn with at most three short facts, then all three come back lit with a
// one-line answer and the evidence equation. Numbers come from the role blocks above (each sourced there). In a fact,
// `count` names the part that counts up and `ring` adds the days ring. `at` names the cue on which each beat lands.
export type SplitFact = {text: string; count?: string; ring?: boolean; tone?: 'accent' | 'muted'};
export type SplitRole = {role: string; icon: 'probe' | 'loop' | 'bars'; question: string; answer: SplitFact; facts: SplitFact[]};
const persist = teamLead.persistent; // WI §2 [step 21]: 22 of 31 days, not falling
export const split = {
	header: {ask: 'Three people ask about the same logs', answer: 'Each of them gets a different answer'},
	roles: [
		{
			role: 'Engineer',
			icon: 'probe',
			question: 'What failed?',
			answer: {text: `One node · ${engineer.share.pct}`, count: engineer.share.pct}, // WI §1 [step 2]
			facts: [
				{text: `One node · ${engineer.share.pct} of fatal entries`, count: engineer.share.pct}, // WI §1 [step 2]
				{text: 'L2 cache error just before'}, // WI §1 [step 5]
				{text: 'Next: processor diagnostics', tone: 'accent'},
			],
		},
		{
			role: 'Team lead',
			icon: 'loop',
			question: 'What keeps coming back?',
			answer: {text: `${persist.days} of ${persist.of} days`, count: String(persist.days)},
			facts: [
				{text: `"${persist.message}"`},
				{text: `${persist.days} of ${persist.of} days · ${persist.trendLabel}`, count: String(persist.days), ring: true},
				{text: `${teamLead.first.label}: ${teamLead.first.team}`, tone: 'accent'},
			],
		},
		{
			role: 'Manager',
			icon: 'bars',
			question: 'What should we fix first?',
			answer: {text: `#1 job launches +${manager.cards[0].counter}%`, count: `+${manager.cards[0].counter}%`}, // WI §3 item 1
			facts: [
				{text: `${manager.cards.length} ranked risks, each with an owner`, count: String(manager.cards.length)}, // WI §3
				{text: `#1 job launches +${manager.cards[0].counter}%`, count: `+${manager.cards[0].counter}%`}, // WI §3 item 1
				{text: 'No made-up downtime or cost figures', tone: 'muted'},
			],
		},
	] as SplitRole[],
	/** The evidence beat under the cards: the engineer's full-text count against BGL's own labels. */
	evidence: {left: evidence.left.value, right: evidence.right.value, caption: evidence.snapCaption}, // WI [steps 23, 24]
	cues: [
		'Same agent, same logs, three people asking at once.',
		'The engineer gets a cause: one node, data TLB errors, and an L2 cache read error just before. Next check: processor diagnostics.',
		"The team lead gets the pattern: 'Link has been severed' on 22 of 31 days. Investigate first: HPC Applications.",
		'The manager gets the priority: five ranked risks, each with an owner, and no invented cost.',
		"And every number is a query: 152,734 counted, 152,734 in BGL's own labels.",
	],
	/** Cue indices: the cards come in on `liftoff`; engineer, team lead, manager take centre stage in turn; then all lit. */
	at: {liftoff: 0, engineer: 1, teamLead: 2, manager: 3, allLit: 4},
};

// ---------------------------------------------------------------- 8 star gag (after the close)
export const star = {
	repo: {owner: 'serenedb', name: 'serenedb'},
	caption: 'As requested.',
};
