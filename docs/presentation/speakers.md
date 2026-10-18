# Speaker scripts: Making Sense of Logs

What each presenter says to camera, in order. These are the narration quotes of [script.md](script.md),
rewritten to be spoken, not read. `presentation/src/content.ts` holds the same words as cues: the reveal and the
split time their shots on them, so if you change a sentence, change the cue too (same number of cues, same order).

Pace: about 140 words a minute, a little faster in the reveal. `/` marks a beat: a short pause where the picture
changes. Start and end every take on 1 s of silence (handoff 3).

| Presenter | Takes | Target | Spoken |
|---|---|---|---|
| A | `s1-reveal.mp4`, `s7-close-a.mp4` | ≤ 40 s, ≤ 8 s | ≈ 40 s at a brisk pace, ≈ 7 s |
| B | `s2-roles.mp4`, `s-demo.mp4`, `s7-close-b.mp4` | ≈ 30 s, 15–25 s, ≤ 8 s | ≈ 31 s, ≈ 22 s, ≈ 7 s |
| C | `s6-benchmarks.mp4`, `s7-close-c.mp4` | see the note under C, ≤ 8 s | ≈ 42 s, ≈ 6 s |

The phone call before A is AI audio (`dialog.mp3`), not a presenter.

## Say it right

- **Blue Gene/L**: "blue gene L". **CLAIX**: "clay-x". **Drain3**: "drain three".
- **152,229**: "a hundred and fifty-two thousand". The exact number is on screen; round it when you say it.
- **4.7 million**, **4.6 million**: two different numbers on purpose (all of BGL; the annotated Loghub subset).
- Say "lines" or "entries" for counts, "incidents" only for RCAEval.

---

## Presenter A: the reveal (`s1-reveal.mp4`, full screen, then corner)

Comes straight after the phone hangs up. Look into the camera. Start quiet, like you are letting people in on
something, and lift on "So we flipped it".

> The voices are made up. The logs are real. /
> Blue Gene/L. Back then, the fastest computer on Earth. /
> One node: a hundred and fifty-two thousand fatal errors, in one evening. /
> Tonight, that could be CLAIX, here in Aachen. /
> The whole machine wrote 4.7 million lines in seven months. /
> Nobody reads that. No prompt holds it. /
> But lines repeat. Drain3 folds them into templates: /
> 4.6 million lines, 320 templates. /
> So we flipped it. The AI never reads the logs. /
> SereneDB counts every line, exactly. /
> Claude asks the questions and explains, /
> and every number carries its query. /
> Let's answer that phone call.

Shots land on: "One node" (the headline), "The whole machine" (the fact), "But lines repeat" (templates), "So we flipped it" (the How-it-works diagram).

## Presenter B: three roles (`s2-roles.mp4`, corner)

One take. The three columns build at the same time on screen; you name each role's answer in turn. Pause
between the roles so each column gets its moment, and slow down for the last line: the screen shows 152,734 = 152,734 while you say it.

> Same agent, same logs, three people asking. /
> The engineer gets a cause: one node, an L2 cache error just before. Next: processor diagnostics. /
> The team lead gets the pattern: "Link has been severed", 22 of 31 days. First stop: HPC Applications. /
> The manager gets the priority: five ranked risks, each with an owner. No made-up costs. /
> And every number is a real query: our count matches BGL's own labels, line for line.

## Presenter B: live demo (`s-demo.mp4`, corner, over `demo.mp4`)

The screen recording plays muted next to you. Talk to the viewer, not to the screen. If the recording shows
only one or two roles, drop the others from the middle sentence.

> And that's not an animation. This is the real session, sped up. /
> Watch Claude pick different tools for each role: search and context for the engineer, counts and trends for
> the team lead, a ranked list for the manager. /
> And every answer cites the query behind it.

## Presenter C: benchmarks (`s6-benchmarks.mp4`, corner)

The three designs appear one at a time, about 4 s apart: say each as it appears. Then the cost shot, then the
RCAEval shot. This is the "we tested it" moment: confident, not salesy.

> How do we know it works? Thirty sealed questions, five runs each, graded blind, at every step. /
> We started small: seven fixed tools. 93.5 percent. /
> Then more tools: eighteen. No better score, and every answer cost almost twice as much. /
> Then Drain3: it finds the log templates per question, and Claude writes its own SQL. /
> The best score, 96.9 percent, and about four times cheaper than eighteen tools. /
> And it's not only logs. With metrics and traces, on 116 microservice incidents, it names the right root
> cause first 96 percent of the time.

Numbers: `presentation/public/assets/benchmarks.json` (final: 93.5% / $0.26, 92.9% / $0.46, 96.9% / $0.12;
RCAEval AC@1 96.3%). The screen shows "3.9× cheaper than 18 fixed tools".

Note: handoff 3 still says s6 ≤ 15 s, from before the RCAEval shot was added. These words take about 42 s. The
whole talk is about 3:10 against a 4:59 limit, so the longer take fits; `npm run check` prints the total.

## The close: all three (full screen)

Look into the camera. Either one joint take (`s7-close.mp4`, all three in frame, in this order) or three
clips with hard cuts, each ≤ 8 s:

| File | Who | Line |
|---|---|---|
| `s7-close-a.mp4` | A | "So, that phone call? The engineer gets a cause, not a scroll bar." |
| `s7-close-b.mp4` | B | "The team lead gets the pattern. Every number traces to a query." |
| `s7-close-c.mp4` | C | "The manager gets the priority, not a guess. Thank you!" |

C's "Thank you" is the last word of the talk before the star gag: smile, and hold the camera for a beat after
it.
