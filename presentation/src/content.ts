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

/** Who speaks in which facecam take. The close s7 is all three (one joint take, or s7a/b/c). */
export const sectionPresenter = {
	s1: 'A',
	s2: 'A',
	s3: 'B',
	s5: 'B',
	s4: 'C',
	s6: 'C',
	s7a: 'A',
	s7b: 'B',
	s7c: 'C',
} as const satisfies Partial<Record<string, PresenterId>>;

/** The take in which each presenter first appears; their name tag shows there once. */
export const firstAppearance = {s1: 'A', s3: 'B', s4: 'C'} as const;

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

export const DRAMATIZATION_LABEL = 'Dramatization: real log data, AI-generated voices';

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
		'The voices are reconstructed. Everything else is real.',
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
	headlineFromCue: 3,
	/** Index of the cue from which the 4.7 million shot shows. */
	factFromCue: 5,
	/** Index of the cue from which the flow line shows ("So we flipped it."). */
	flowFromCue: 7,
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
	cues: [
		'We did not guess which design works.',
		'We built three, gave them the same sealed questions for all three roles,',
		'and a grader scored the answers without knowing which design wrote them.',
		'Ours came out on top, and it was the cheapest per answer.',
		'What lost? A broad toolbox with many tools:',
		'more calls, more cost, a lower score.',
		'A lean server without an index: close, but behind.',
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

// ---------------------------------------------------------------- 8 star gag (after the close)
export const star = {
	repo: {owner: 'serenedb', name: 'serenedb'},
	caption: 'As requested. Several times.',
};
