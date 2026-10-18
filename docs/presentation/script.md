# Demo script: Making Sense of Logs (about 2:20, limit 5 minutes)

Spoken text plus 20 seconds of dialog audio comes to about 2:20 at a calm pace (140 words per minute).
Screen cues are in *italics*. Per presenter, with delivery notes: [speakers.md](speakers.md). The one recording is a pre-run Claude Code session with this MCP server, shown
muted in the live demo while B narrates. Log numbers come from
[worked-investigation.md](../worked-investigation.md); benchmark numbers from serenedb-bench REPORT.md (night run 2).

---

## 0:00 – 1:00 · Why this matters: a phone call, a fact, our answer (slide 1)

*Slide 1: dark screen, caption "Lawrence Livermore National Laboratory · Blue Gene/L · Saturday, 11 June 2005,
17:17". A phone rings. The dialog below plays as AI-generated audio (about 20 seconds) with subtitles. Corner
label: "Dramatization: real log data, AI-generated voices".*

| Voice | Line |
| --- | --- |
| Engineer on call (tired, quiet) | "Yes, I'm looking at it. One node on Blue Gene/L, R30-M0-N9. Data TLB errors, fatal. Twenty-four thousand an hour." |
| Team lead (worried) | "Has this happened before?" |
| Engineer | "I don't know. The log is millions of lines." |
| Manager (calm, firm) | "How bad is it? Do we act tonight?" |
| Engineer | "Give me a few hours." *(sigh, keyboard, scrolling)* |

> **A:** The voices are made up. The logs are real. Blue Gene/L. Back then, the fastest computer on Earth. One
> node: a hundred and fifty-two thousand fatal errors, in one evening. Tonight, that could be CLAIX, here in
> Aachen. The whole machine wrote 4.7 million lines in seven months. Nobody reads that. No prompt holds it. But
> lines repeat. Drain3 folds them into templates: 4.6 million lines, 320 templates. So we flipped it. The AI
> never reads the logs. SereneDB counts every line, exactly. Claude asks the questions and explains, and every
> number carries its query. Let's answer that phone call.

*Production: generate the dialog with ElevenLabs (three distinct voices; its dialogue mode or one clip per line,
stitched), export MP3, embed on slide 1 with auto-play. Fallback if audio fails: the presenter reads the three
questions aloud.*

## 1:00 – 1:30 · Three roles, one split (slide 2)

One scene, one presenter (B, take `s2-roles.mp4`, about 30 s; design:
`docs/superpowers/specs/2026-10-19-three-way-split-design.md`). *The three
columns, Engineer / Team lead / Manager, fly in right away on B's first sentence and build at the same time: question → the role's tool calls →
a one-line answer and its next step. At the end all three are lit, with a quick evidence beat: `[Q46]` →
152,734 = 152,734.*

**B:**

> Same agent, same logs, three people asking. The engineer gets a cause: one node, an L2 cache error just
> before. Next: processor diagnostics. The team lead gets the pattern: "Link has been severed", 22 of 31 days.
> First stop: HPC Applications. The manager gets the priority: five ranked risks, each with an owner. No made-up
> costs. And every number is a real query: our count matches BGL's own labels, line for line.

## Live demo (demo.mp4)

*A real Claude Code session with the serenedb-extractor MCP server, cut and sped up, shown muted as a screen inside the film; B narrates it live in the corner (take `s-demo.mp4`, ≈ 15–25 s).*

**B:**

> And that's not an animation. This is the real session, sped up. Watch Claude pick different tools for each
> role: search and context for the engineer, counts and trends for the team lead, a ranked list for the manager.
> And every answer cites the query behind it.

## 1:50 – 2:18 · Benchmarks (slide 4)

*Video, two calm shots to talk over (plain fades, no sound effects): the three steps appear one column at a
time as you name them (pipeline, score, "+N pts"), about 4 s apart; then cost per answer per step with "+93%",
"−67%" and the caption "3× cheaper … with the top score". Slide: the three designs in
the same order. Numbers in the video come from `benchmarks.json`; say the final ones.*

> **C:** How do we know it works? Thirty sealed questions, five runs each, graded blind, at every step. We
> started small: seven fixed tools. 93.5 percent. Then more tools: eighteen. No better score, and every answer
> cost almost twice as much. Then we went back to a small set of core tools, and added Drain3 templates and Claude's own SQL. The best score, 96.9 percent, and about four times cheaper than eighteen tools. And it's not only logs.
> With metrics and traces, on 116 microservice incidents, it names the right root cause first 96 percent of the
> time.

*Third shot (final numbers, RCAEval report `results/rca/REPORT-2026-10-18.md` on OrFrederick/serenedb-bench
`bench/R-OrFrederick`): 96.3% AC@1, 99.1% AC@3 (arm T, k=3, 348 trials, Claude Sonnet); on the 48-case test set
logs only 56% → 100% with metric and trace tools, $0.54 → $0.30 per answer. The metric and trace tools are PR #40
(`feat/metrics-traces`), not yet on main.*

**TODO when all runs finish:**

- [ ] Final score and cost per answer for each design
- [ ] Pick the commit we present, and use that version's numbers
- [x] RCAEval result for metrics and traces (third shot of the benchmark scene)
- [ ] Slide footnote: model, number of questions, runs per question, blind grader

## 2:05 – 2:30 · Close (slide 5)

> **a:** So, that phone call? The engineer gets a cause, not a scroll bar.
>
> **b:** The team lead gets the pattern. Every number traces to a query.
>
> **c:** The manager gets the priority, not a guess. Thank you!

---

## Slides

1. Dark title card "Lawrence Livermore National Laboratory · Blue Gene/L · Saturday, 11 June 2005, 17:17" with the ElevenLabs dialog and subtitles, then "152,229 fatal entries · one node · one evening", then the flow line
2. Three roles: the split's final frame, all three columns built (Question / Evidence / Next step)
3. Evidence: `[Q46]` footer + 152,734 = 152,734
4. Benchmarks: blind rubric bars per design, cost per answer on each bar, comparability footnote
5. Close: the three answers in one line each

## Recording checklist

- Record `demo.mp4`: a real session on the loaded base corpus, e.g. the three role prompts (handoff 2).
- Check that the live numbers match worked-investigation.md before recording. If a number differs,
  use the live number in the script.
- Cut and speed it up yourself to fit the `s-demo.mp4` take (≈ 15–25 s); the last frame holds if shorter.
