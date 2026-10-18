# Demo script: Making Sense of Logs (5 minutes)

Spoken text is about 500 words plus 20 seconds of dialog audio, which is about 4:00 at a calm pace (140 words per minute). The rest of
the 5 minutes is buffer for pauses on the recordings.
Screen cues are in *italics*. Recordings are pre-run Claude Code sessions with this MCP server; play
them sped up and pause on the frames named in each cue. Log numbers come from
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

## 1:00 – 1:45 · Engineer (slide 2 + recording 1)

*Recording: `/engineer What failed on BGL on 11 June 2005, and what happened just before?`
Pause on the `search_logs` result, then on the `get_context` timeline.*

> The engineer asks: what failed? Claude counts fatal entries by node, over the whole log. One node:
> R30-M0-N9-C:J16-U01. 152,229 of 855,501 fatal entries, 17.8 percent. Full-text search names it: "data TLB
> error interrupt", non-stop from 17:17 to 23:39.
>
> And just before? `get_context` shows one line in the same second: an L2 cache read error. Three times in
> seven months, twice on this node.
>
> The hypothesis is a failing L2 cache, labelled as a hypothesis. The next check: processor diagnostics. If
> they fail, replace the card. If they pass, look at the job that ran at 17:17.

## 1:45 – 2:25 · Team lead (slide 3 + recording 2)

*Recording: `/team-lead Which problems keep recurring across BGL and OpenStack, and what should we look at first?`
Pause on the `count_logs` table by team and level, then on the `trend` result.*

> The team lead asks: what keeps coming back? That needs counts, not examples: every entry in both datasets,
> grouped by team. Then December against November.
>
> The winner is not the biggest number. It is the most persistent: "Link has been severed" on the I/O
> sockets, on 22 of 31 days, and not falling. Investigate first: HPC Applications. Second: Node OS confirms
> the 14 June event.

## 2:25 – 3:05 · Manager (slide 4 + recording 3)

*Recording: `/manager What should we prioritise from these logs?` Hold on the ranked list.*

> The manager gets no node names. Five ranked risks, each with an owner and one action. First: failing job
> launches, up 91 percent month over month, "permission denied" on program images. Owner: HPC Applications.
> Second: the broken links. Third: the faulty node, out of service until it passes diagnostics.
>
> And one honest line: these logs do not measure downtime or cost, so the answer does not invent them.

## 3:05 – 3:40 · Why you can trust the numbers (slide 5)

*Slide: one evidence footer with `[Q46]` and its SQL; below it the two numbers 152,734 = 152,734.*

> Every number carries a citation, like Q46. `show_evidence` returns the exact SQL, its time and its rows.
> And we checked against ground truth: a full-text count of "data TLB error interrupt" over all of BGL gives
> 152,734. BGL's own alert labels: exactly 152,734. Real counts, not a sample.

## 3:40 – 4:20 · Benchmarks (slide 6)

*Slide: title "Same questions, graded blind". Three bars, one per design, ours highlighted. Score and cost per
answer on each bar.*

> We did not guess which design works. We built three, gave them the same sealed questions for all three
> roles, and a grader scored the answers without knowing which design wrote them.
>
> Ours came out on top, and it was the cheapest per answer. *[TODO: final score and cost.]*
>
> What lost? A broad toolbox with many tools: more calls, more cost, a lower score. A lean server without an
> index: close, but behind. *[TODO: one number each.]*

**TODO when all runs finish:**

- [ ] Final score and cost per answer for each design
- [ ] Pick the commit we present, and use that version's numbers
- [ ] RCAEval result for metrics and traces, if it lands in time
- [ ] Slide footnote: model, number of questions, runs per question, blind grader

## 4:20 – 4:45 · Close (slide 7)

> So, back to that phone call. The engineer gets a cause to check, not a scroll bar. The team lead gets the
> pattern. The manager gets the priority. And every number is traceable to a query. Thank you.

---

## Slides

1. Dark title card "Lawrence Livermore National Laboratory · Blue Gene/L · Saturday, 11 June 2005, 17:17" with the ElevenLabs dialog and subtitles, then "152,229 fatal entries · one node · one evening", then the flow line
2. Engineer: the node, 152,229 of 855,501 (17.8%), the L2 line before the run
3. Team lead: counts by team table; "22 of 31 days"
4. Manager: the five ranked risks with owners
5. Evidence: `[Q46]` footer + 152,734 = 152,734
6. Benchmarks: blind rubric bars per design, cost per answer on each bar, comparability footnote
7. Close: the three answers in one line each

## Recording checklist

- Run each role prompt in a fresh Claude Code session on the loaded base corpus.
- Check that the live numbers match worked-investigation.md before recording. If a number differs,
  use the live number in the script.
- Keep each clip under 60 seconds after speed-up; cut waiting time, never the tool results.
