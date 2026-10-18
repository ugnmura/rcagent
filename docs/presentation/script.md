# Demo script: Making Sense of Logs (about 2:20, limit 5 minutes)

Spoken text plus 20 seconds of dialog audio comes to about 2:20 at a calm pace (140 words per minute).
Screen cues are in *italics*. The one recording is a pre-run Claude Code session with this MCP server, shown
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

> **The reveal.** The voices are reconstructed. Everything else is real. Saturday, 11 June 2005, Lawrence
> Livermore National Laboratory. Blue Gene/L, then the fastest supercomputer on Earth. That one node wrote
> 152,229 fatal entries in a single evening. Tonight it could be CLAIX, here in Aachen.
>
> **The fact.** That machine wrote 4.7 million log lines in seven months. No human reads that. No AI prompt
> holds it either.
>
> **Our answer.** So we flipped it. The AI does not read the logs. SereneDB searches and counts every line,
> exactly. Claude asks the questions and explains the answers, and every number carries the query that proved
> it. Let's answer that phone call.

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

> Same agent, same logs, three people asking at once. The engineer gets a cause: one node, data TLB errors, and
> an L2 cache read error just before. Next check: processor diagnostics. The team lead gets the pattern: "Link
> has been severed" on 22 of 31 days. Investigate first: HPC Applications. The manager gets the priority: five
> ranked risks, each with an owner, and no invented cost. And every number is a query: 152,734 counted,
> 152,734 in BGL's own labels.

## Live demo (demo.mp4)

*A real Claude Code session with the serenedb-extractor MCP server, cut and sped up, shown muted as a screen inside the film; B narrates it live in the corner (take `s-demo.mp4`, ≈ 15–25 s).*

## 1:50 – 2:05 · Benchmarks (slide 4)

*Slide: title "Same questions, graded blind". Three bars, one per design, ours highlighted.*

> We didn't guess which design works. Three designs, the same sealed questions, graded blind. Ours scored
> highest, and it was the cheapest per answer. *[TODO: final score and cost.]*

**TODO when all runs finish:**

- [ ] Final score and cost per answer for each design
- [ ] Pick the commit we present, and use that version's numbers
- [ ] RCAEval result for metrics and traces, if it lands in time
- [ ] Slide footnote: model, number of questions, runs per question, blind grader

## 2:05 – 2:30 · Close (slide 5)

> So, back to that phone call. The engineer gets a cause to check, not a scroll bar. The team lead gets the
> pattern. The manager gets the priority. And every number is traceable to a query. Thank you.

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
