# Three-way split: one scene for the three roles

Date: 2026-10-19 · Status: design, awaiting approval · Applies to: `presentation/` (Remotion), `docs/presentation/`

## Why

The middle of the talk drags. Engineer, team lead and manager each run the same beat: chapter card → animated
slide (16–22 s) → screen recording at real speed. That is about 2:05 of one rhythm repeated three times, then
two "trust us" sections in a row (evidence 35 s, benchmarks 40 s).

The judges score mostly on what the middle shows (role insight 30 %, search + analytics 25 %, recommendations
25 %). So the content stays; the repetition goes. Judges can run the repo with their own model, so the video
does not need three full recordings. One well-animated scene that shows the three roles side by side explains
it once, and its final frame shows the brief's own test at a glance: the **questions, evidence and actions**
differ per role, not just the answer length.

The 5-minute limit is a ceiling, not a target. The new talk is about 3:30.

**The bar: it has to be satisfying to watch.** Every beat moves on a spoken cue, nothing sits still waiting,
and the motion has weight: the same polish as the reworked star gag (eased curves, overshoot springs, glow,
small particles where something lands, sound effects on the beats).

## Goals

- Replace scenes 2–5 (engineer, team lead, manager, evidence) with **one split scene**.
- Keep all three presenters presenting, each owning one role, with coherent hand-offs.
- Keep a short piece of **real footage** so the video reads as a working prototype, not a mockup.
- Show query evidence (the brief requires "the query evidence behind them") inside the split.
- Shorten benchmarks to one beat.

## Non-goals

- No change to the intro card, cold open, reveal, close or star gag.
- No new numbers. Every number on screen already exists in `src/content.ts` with its source (WI / script).
- No renders: the user previews in Remotion Studio.

## Anti-goals (failure even if it technically works)

- Three columns that look like a static table with a voice over it. Something must move on every cue.
- Columns that differ only in wording length. The rows must show different questions, different evidence,
  different actions.
- Text too small to read: the final frame has to be readable at 1080p in a few seconds.
- Hand-offs that feel like three separate chapters again.

## The new talk

| # | Scene | Who | Length now | Length new |
|---|---|---|---|---|
| 0 | Intro card | — | 0:03 | unchanged |
| 1a | Cold open (dialog) | — | 0:20 | unchanged |
| 1b | Reveal | A | 0:40 | unchanged |
| 2 | **Split** (proof clip → three columns → evidence beat) | A → B → C → B | 2:40 (scenes 2–5) | ≈ 1:40 |
| 3 | Benchmarks | C | 0:40 | ≈ 0:15 |
| 4 | Close | all | 0:25 | unchanged |
| 5 | Star gag | — | 0:06 | unchanged |
| | **Total** | | 4:54 | **≈ 3:30** |

## The split scene, beat by beat

**Beat 1, proof clip (≈ 6 s, under A's opening line; see call 1).** One real terminal recording in which
`/engineer`, `/team-lead` and `/manager` are asked in turn and Claude calls the MCP tools for each. Played at
about 3× through typing and tool calls; it slows to normal speed for a moment on each answer. Purpose: it
really runs, and the same agent picks different tools per role.

**Beat 2, lift-off (≈ 2 s).** The three answers lift out of the terminal and fly into three columns. Header:
"One log. Three questions." with the scope line under it (BGL + OpenStack, whole corpus). The terminal
dissolves behind.

**Beats 3–5, the columns in turn.** Three columns, **same rows, aligned**: Question / Evidence / Next step.
Only the active column is lit; the others are dimmed. The active presenter's facecam sits in a round frame on
their column. Each row builds on that presenter's spoken cue.

| column | presenter | Question | Evidence (what animates) | Next step |
|---|---|---|---|---|
| Engineer | A | What failed, and what came just before? | node R30-M0-N9-C:J16-U01 · 152,229 of 855,501 FATAL (17.8 %) · "data TLB error interrupt" 17:17–23:39 · one L2 cache read error in the same second before | Hypothesis (labelled): failing L2 cache. Check: processor diagnostics |
| Team lead | B | What keeps coming back? | fatal entries by team (Node OS 626,756 · HPC Applications 228,536) · "Link has been severed" on 22 of 31 December days, not falling | Investigate first: HPC Applications |
| Manager | C | What do we act on first? | five ranked risks with owners; #1 failing job launches +91 % | Owner + one action each; "logs don't measure downtime or cost" |

The existing shot components carry the evidence motion where they fit, scaled into a column: the node line,
the 17.8 % ring, the flood (engineer); the team bars and the 22-of-31 days grid (team lead); the risk cards and
the limit line (manager).

**Hand-offs carry one investigation**, not three chapters: A ends on the node ("…one node. Is it a pattern?"),
B picks it up and widens to the teams, B ends on "what do we act on first?", C answers with the ranking. As the
active column changes, the previous one stays readable but dimmed, so the table fills up left to right.

**Beat 6, all lit.** All three columns lit, header turns to "One log. Three answers." Hold long enough to read
across the rows.

**Beat 7, evidence (B, ≈ 15 s).** Every Evidence cell carries its query handle (e.g. Q46). The camera pushes
into one handle in the engineer column; it opens into the `show_evidence` view: the call, the SQL excerpt and
the ground-truth match **152,734 = 152,734** (full-text count vs. BGL's own KERNDTLB labels). Then it pulls back
to the full table. This replaces the separate evidence scene.

## Benchmarks (≈ 15 s, C)

One beat before the close: three designs, the same sealed questions, graded blind; ours scored highest and was
the cheapest per answer. Numbers still come only from `public/assets/benchmarks.json` (pending, as today).

## Presenters and facecam takes

| take | presenter | content | target | was |
|---|---|---|---|---|
| `s1-reveal.mp4` | A | unchanged | ≤ 40 s | same |
| `s2-engineer.mp4` | A | proof clip intro + engineer column | ≤ 32 s | ≤ 45 s |
| `s3-team-lead.mp4` | B | team lead column | ≤ 25 s | ≤ 40 s |
| `s4-manager.mp4` | C | manager column | ≤ 25 s | ≤ 40 s |
| `s5-evidence.mp4` | B | evidence beat | ≤ 15 s | ≤ 35 s |
| `s6-benchmarks.mp4` | C | benchmarks beat | ≤ 15 s | ≤ 40 s |
| close | all | unchanged | ≤ 25 s | same |

The scene's column timing follows the take lengths (as the role scenes do today), and the row builds follow
the subtitle cues.

**Draft wording (presenters may adjust; the numbers may not change):**

- A: "Same agent, same logs, three people asking. Watch it pick different tools for each. The engineer asks: what failed? One node,
  R30-M0-N9-C:J16-U01: 152,229 of 855,501 fatal entries, 17.8 percent. Full-text search names it: data TLB
  error interrupt, non-stop from 17:17 to 23:39. Just before, in the same second: an L2 cache read error. Our
  hypothesis, labelled as one: a failing L2 cache. Next check: processor diagnostics. That's one node. But is
  it a pattern?"
- B: "That needs counts, not examples: every entry in both datasets, grouped by team. The winner isn't the
  biggest number, it's the most persistent: 'Link has been severed', on 22 of 31 days in December, and not
  falling. Investigate first: HPC Applications. So what do we act on first?"
- C: "The manager gets no node names: five ranked risks, each with an owner and one action. First: failing job
  launches, up 91 percent month over month. And one honest line: these logs don't measure downtime or cost, so
  the answer doesn't invent them."
- B (evidence): "And every number here is a query. Open one: the exact SQL, its time, its rows. The full-text
  count of 'data TLB error interrupt' is 152,734. BGL's own labels: exactly 152,734."
- C (benchmarks): "We didn't guess which design works. Three designs, the same sealed questions, graded blind.
  Ours scored highest, and it was the cheapest per answer."

## Recording

The three role recordings (`engineer.mp4`, `team-lead.mp4`, `manager.mp4`) are replaced by **one** recording,
`roles.mp4`: the three prompts from handoff 2, asked in turn in one session or cut together from three, raw
length free (it is sped up in the edit). Until it exists, the usual labelled placeholder shows (≈ 6 s on
screen).

## Files that change

- `presentation/src/timeline.ts`: scenes `engineer`, `teamLead`, `manager`, `evidence` → one `split` scene;
  `SLIDE_SECONDS` goes.
- `presentation/src/assets.ts`: `engineerRec` / `teamLeadRec` / `managerRec` → `rolesRec` (`roles.mp4`); new
  target lengths for s2–s6.
- `presentation/src/scenes.tsx`, `src/Talk.tsx`: the split scene; role scenes and evidence scene removed;
  benchmarks scene shortened.
- `presentation/src/content.ts`: split header lines, column rows, new cues from the draft wording;
  `sectionPresenter` unchanged (A s2, B s3+s5, C s4+s6).
- New shots for the split (columns, lift-off, evidence push-in) in a new file next to `shots2.tsx`.
- `presentation/src/slides/index.tsx`: slides 2–5 become one split page (final frame of beat 6) plus the
  evidence page.
- `docs/presentation/script.md`, `handoffs/02-role-recordings.md`, `handoffs/03-facecam.md`: the new beats,
  the one recording, the new take lengths.
- Sound: reuse `public/assets/sfx/` (whoosh on lift-off, a soft click per row landing, chime on "all lit");
  extend `scripts/sfx.mjs` if a new sound is needed.

## Calls made after review (Claude's, not the user's; check these)

1. **Proof clip vs. A's lines.** The proof clip is **≈ 6 s** on screen (not 10), under A's opening line, which
   grows to two sentences: "Same agent, same logs, three people asking. Watch it pick different tools for each."
   The lift-off (beat 2) lands on "The engineer asks: what failed?", and the engineer rows build from there on
   A's cues. `s2` target becomes **≤ 32 s**.
2. **Query handles.** Only the engineer's full-text line ("data TLB error interrupt") carries a handle: `Q46`
   (stand-in, replaced by the live handle in handoff 5 as today). It is attached to that message line, **not**
   to the 152,229 node figure, so the push-in opening on 152,734 (whole-BGL count of that message) reads
   correctly. The other Evidence cells carry a small unnumbered "query" mark, no invented handle numbers.
3. **Beat 6 timing.** "All lit" starts on C's last line and runs into the start of B's `s5` take: B's first
   line ("And every number here is a query.") plays over the full table, then the push-in starts. Plus at most
   a **1 s** silent hold between `s4` and `s5` (a constant in `timeline.ts`), where the chime lands. No longer
   silent hold.

## Left to the builder

- Exact layout, type sizes, colours (within the existing theme and film look), motion curves.
- How the existing shots are scaled or simplified to fit a column.
- Speed ramp of the proof clip.
- Which sounds land where, and their levels (under the voices, never over them).
- Whether the facecam frame sits on the column or in a fixed corner, as long as it is clear who speaks.
