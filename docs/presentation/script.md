# Demo script: Making Sense of Logs (about 4:39, limit 4:59)

Presenters: Eugene Matsumura (A), Frederick Ortmanns (B), Deni Ismailov (C).

The estimate adds the recorded parts (intro 3 s, cold open 26.8 s, Eugene's reveal take 135 s, demo recording 20 s)
to the table's estimates for the takes not yet recorded; the total is to check once all takes are recorded, since
it could go past the 4:59 limit. Screen cues are in *italics*. Every spoken line below is the subtitle text in
`presentation/src/content.ts`; change both together. The demo recording is a pre-run Claude Code session with this
MCP server, shown muted in the live demo while Frederick narrates. Log numbers come from
[worked-investigation.md](../worked-investigation.md); world numbers from the sources named on screen; benchmark
numbers from serenedb-bench REPORT.md (night run 2).

| Time | Scene | Who | Slide |
|---|---|---|---|
| 0:00 – 0:03 | Intro card | — | 1 (title) |
| 0:03 – 0:30 | Cold open: the phone call | ElevenLabs voices | 2 |
| 0:30 – 2:14 | Reveal: the story, how often, RCAgent, templating, how it works | Eugene (A) (`s1-reveal.mp4`, 2:15 recorded, 1:44 at 1.3×) | 3 – 7 |
| 2:14 – 2:54 | Three roles, one split | Frederick (B) (`s2-roles.mp4`, 40 s) | 8 |
| 2:54 – 3:37 | Live demo | Frederick (B) (`s-demo.mp4`, 43 s; recording `demo.mp4`, 20 s) | 9 |
| 3:37 – 4:20 | Benchmarks | Deni (C) (`s6-benchmarks.mp4`, 43 s) | 10 – 12 |
| 4:20 – 4:26 | Star gag | — | — |

The close (slide 13) is only on the slides; the video has no close scene. Total 4:26 (limit 4:59), measured from the
real takes.

---

## 0:03 – 0:30 · Cold open: the phone call (slide 2)

*Dark screen. The caption types on, with a typewriter tick per character: "Lawrence Livermore National Laboratory ·
Blue Gene/L · Saturday, 11 June 2005 · 17:17". Real BGL lines scroll behind it, faster and redder; a low drone
swells under the call; subtitles of the five lines in the bottom bar. Keyboard taps after the last line. Then the
line goes dead: one hang-up click, and the last 0.4 s is a frozen picture in silence. Hard cut.*

| Voice (ElevenLabs v4) | Line |
| --- | --- |
| Engineer (Spence, tired, quiet) | "Yes, I'm looking at it. One node on Blue Gene/L, R30-M0-N9. Data TLB errors, fatal. Twenty-four thousand an hour." |
| Team lead (Hollie Sue, on the phone, worried) | "Has this happened before?" |
| Engineer | "I don't know. The log is millions of lines." |
| Manager (Jessica, on the phone, calm) | "How bad is it? Do we act tonight?" |
| Engineer | *(sigh)* "Give me a few hours." |

*Audio: `presentation/public/assets/dialog.mp3` (26.8 s; team lead and manager through a phone filter; credits in
`presentation/public/assets/CREDITS.md`). Sound effects: `scripts/sfx-cold.mjs`.*

## 0:30 – 2:45 · Reveal: the story, how often, RCAgent, templating, how it works (slides 3 – 7)

Eugene's recorded take `s1-reveal.mp4` (134.99 s). Times in brackets are from the start of the take.

*[0:00] Opens on black after the dead line; Eugene's facecam fades up full screen as he starts.*

**Eugene (A):**

> This is a story that really happened, on the Blue Gene/L, at the time the fastest supercomputer. And this is not
> rare, especially now in the age of generative AI.

*[0:18] Slide 3: "419 · unexpected failures in 54 days on one AI cluster" (Meta, The Llama 3 Herd of Models, 2024).
Eugene moves to the corner.*

> For example, Meta reported 419 unexpected failures in just 54 days in 2024.

*[0:27] Slide 4: "$2M · per hour of a high-impact outage" (New Relic Observability Forecast 2025).*

> A high-impact outage such as this costs a company around $2 million per hour.

*[0:36] Slide 5: "Introducing RCAgent" (RCAgent in gold).*

> To prevent this entire problem, we built RCAgent. It reads millions of log lines and finds the root cause in
> seconds.

*[0:49] Eugene's facecam full screen again.*

> To build this tool, we tried several approaches, including embedding the logs in SereneDB using vector search.

*[0:59] Slide 6: Templating, powered by Drain3 and SereneDB regex. Real BGL lines mask and fold into four template
cards; "4.6 million lines → 320 templates", source line Loghub-2.0 (BGL: 4,631,261 annotated lines, 320 templates).*

> But what really worked was templating. Millions of log lines are mostly the same few messages with different
> numbers. So using templating, we can fold them into a few hundred templates, so that the agent sees the whole
> picture without drowning in repetition.

*[1:21] Slide 7: How it works (the README diagram, `docs/img/flow.svg`), built step by step: You → Claude → MCP tools
(with Templating) → SereneDB; question, tool call, SQL; Q46 coming back; Evidence Q46; `show_evidence`.*

> But how does the whole pipeline work? You ask Claude, or any other agent, a question. And the agent then uses our
> RCAgent tools to run the search and templating inside SereneDB, which is very, very fast. And then the agent only
> gets back a short, complete summary. And this helps the agent not to drown in context. Every query is also saved,
> so we can trace back where the agent got its claims, and especially the exact data behind those claims.

*[2:15] End of take.*

## 2:45 – 3:19 · Three roles, one split (slide 8)

One scene, one presenter (Frederick (B), take `s2-roles.mp4`, about 30 s; design:
`docs/superpowers/specs/2026-10-19-three-way-split-design.md`). *The three
columns, Engineer / Team lead / Manager, fly in right away on Frederick's first sentence and build at the same time: question → the role's tool calls →
a one-line answer and its next step. At the end all three are lit, with a quick evidence beat: `[Q46]` →
152,734 = 152,734.*

**Frederick (B):**

> Same agent, same logs, three people asking at once. The engineer gets a cause: one node, data TLB errors, and
> an L2 cache read error just before. Next check: processor diagnostics. The team lead gets the pattern: "Link
> has been severed" on 22 of 31 days. Investigate first: HPC Applications. The manager gets the priority: five
> ranked risks, each with an owner, and no invented cost. And every number is a query: 152,734 counted,
> 152,734 in BGL's own labels.

## 3:19 – 3:39 · Live demo (slide 9)

*A real Claude Code session with the RCAgent MCP server, cut and sped up, shown muted as a screen inside the film;
Frederick narrates it live in the corner (take `s-demo.mp4`, ≈ 15–25 s).*

*Recording: `docs/video/engineer-test-run.mp4` (20 s, recorded by Frederick), used in the film as
`presentation/public/assets/demo.mp4`.*

*Slide 9 (without the video): "LIVE DEMO" and the three role prompts to type in Claude Code:
`/engineer What failed on BGL on 11 June 2005, and what happened just before?`,
`/team-lead Which problems keep recurring across BGL and OpenStack, and what should we look at first?`,
`/manager What should we prioritise from these logs?`*

## 3:39 – 4:17 · Benchmarks (slides 10 – 12)

**Deni (C):**

*Video, two calm shots to talk over (plain fades, no sound effects): the three steps appear one column at a
time as you name them (pipeline, score, "+N pts"), about 4 s apart; then cost per answer per step with "+93%",
"−67%" and the caption "3× cheaper … with the top score". Slide: the three designs in
the same order. Numbers in the video come from `benchmarks.json`; say the final ones.*

> How did we get here? Same sealed questions, graded blind, at every step. We started small: seven fixed tools.
> Then more tools: eighteen. No better score, and every answer cost almost twice as much. Then Drain3: it finds
> the log templates when a question comes in, and Claude can also run SQL. The best score, and the cheapest
> answer: about four times cheaper than eighteen tools. *(Final, night run 2: 93.5% / $0.26 · 92.9% / $0.46 ·
> 96.9% / $0.12 per answer.)*
>
> And it is not only logs. With metric and trace tools, on 116 held-out microservice incidents from RCAEval, it
> names the right root cause first 96 percent of the time, and in the top three 99 percent.

*Third shot (final numbers, RCAEval report `results/rca/REPORT-2026-10-18.md` on OrFrederick/serenedb-bench
`bench/R-OrFrederick`): 96.3% AC@1, 99.1% AC@3 (arm T, k=3, 348 trials, Claude Sonnet); on the 48-case test set
logs only 56% → 100% with metric and trace tools, $0.54 → $0.30 per answer. The metric and trace tools are PR #40
(`feat/metrics-traces`), not yet on main.*

**TODO when all runs finish:**

- [ ] Final score and cost per answer for each design
- [ ] Pick the commit we present, and use that version's numbers
- [x] RCAEval result for metrics and traces (third shot of the benchmark scene)
- [ ] Slide footnote: model, number of questions, runs per question, blind grader

## 4:17 – 4:33 · Close (slide 13)

**Eugene (A), Frederick (B), Deni (C):**

> So, back to that phone call. The engineer gets a cause to check, not a scroll bar. The team lead gets the
> pattern. The manager gets the priority. And every number is traceable to a query. Thank you.

---

## Slides (`out/slides.pdf`, 13 pages, rendered with `node scripts/slides.mjs` on CLAIX)

Every page carries SchubKI × SereneDB in the bottom right corner (the close shows it next to the repository link).

1. Title: National AI Hackathon 2026 · Making Sense of Logs · the README pitch · SchubKI × SereneDB
2. The call: caption and the five dialog lines with speakers
3. 419 unexpected failures in 54 days on one AI cluster (Meta, Llama 3 paper)
4. $2M per hour of a high-impact outage (New Relic Observability Forecast 2025)
5. Introducing RCAgent
6. Templating: four BGL templates, 4.6 million lines → 320 templates (Loghub-2.0)
7. How it works: the README diagram
8. Three roles: the split's final frame
9. Live demo: the three role prompts
10. Evidence
11. Benchmarks
12. Features
13. Close: the three answers in one line each, the repository link

## Recording checklist

- Eugene's reveal take is played at **1.3× speed** (pitch kept; 2:15 recorded, 1:44 played) so the talk fits 4:59:
  `ffmpeg -i IN -map 0:v:0 -map 0:a:0 -filter:v "setpts=PTS/1.3,scale=1920:1080" -r 30 -filter:a "atempo=1.3" -c:v libx264 -crf 22 -preset veryfast -pix_fmt yuv420p -c:a aac -movflags +faststart OUT.mp4`.
  The other takes play at normal speed.
- [x] `demo.mp4`: `docs/video/engineer-test-run.mp4` (20 s, Frederick), copied to `presentation/public/assets/demo.mp4`.
- Check that the live numbers match worked-investigation.md before recording. If a number differs,
  use the live number in the script.
- Cut and speed it up yourself to fit the `s-demo.mp4` take (≈ 15–25 s); the last frame holds if shorter.
