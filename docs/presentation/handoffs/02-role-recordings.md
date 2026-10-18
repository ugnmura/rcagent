# Handoff 2: Role recordings

**Goal:** one screen recording of Claude Code answering one question per role with the serenedb-extractor
MCP server, on the loaded base corpus: `roles.mp4` in `presentation/public/assets/`. The video speeds it up to fit
a 3–4 s proof clip at the start of the three-way split, presented by B in one take (design:
`docs/superpowers/specs/2026-10-19-three-way-split-design.md`).

**Wait:** start only after the benchmark runs on this machine have finished. The running `night-*` SereneDB
containers belong to those runs; do not use, stop or reset them. Use a fresh container as in the README quick
start.

## Setup

Follow the README "Quick start (from a clean checkout)" on the commit chosen for the presentation (handoff 5
records which one): SereneDB container, `scripts/load_base_corpus.py`, `claude mcp add serenedb-extractor …`.
Check with `/mcp` that the server lists 15 tools and 3 prompts.

Terminal for recording: dark theme, font size 18 or larger, window 1920×1080, nothing private visible
(no other tabs, no notifications, no paths with personal names if avoidable).

## The take

Ask the three prompts in turn, in one session or in three fresh sessions cut together into one file, in this
order. The whole recording is squeezed into 3–4 s on screen, so the tool calls of each role matter more than the
full answers: the point is that the same agent picks different tools per role. The split's columns then show
each role's question, tool calls and one-line answer as animation, not from this footage.

| part | prompt | must be visible | pause frames (for the script cues) |
|---|---|---|---|
| 1 engineer | `/engineer What failed on BGL on 11 June 2005, and what happened just before?` | node R30-M0-N9-C:J16-U01; 152,229 of 855,501 FATAL; "data TLB error interrupt"; the L2 machine-check line before the run; hypothesis labelled; next check | the `search_logs` result; the `get_context` timeline |
| 2 team lead | `/team-lead Which problems keep recurring across BGL and OpenStack, and what should we look at first?` | counts by team and level over both log tables; "Link has been severed" on 22 of 31 December days; investigate first: HPC Applications | the `count_logs` table; the `trend` result |
| 3 manager | `/manager What should we prioritise from these logs?` | 5 ranked risks with owners and actions; +91% "permission denied"; the closing line on what the logs do not measure | the ranked list |

## Check before keeping a take

Compare every number in the answer with `docs/presentation/script.md` and `docs/worked-investigation.md`.

- Same number: keep.
- Different number: keep the take only if the answer cites a query for it; then note the live number in
  `presentation/public/assets/NUMBERS.md` (script number, live number, evidence handle). Handoff 5 updates the
  script and the slides from that file. Do not edit the script yourself.
- Missing role behaviour (no hypothesis label, no next step, invented impact): redo the take.

## Editing

- Cut long waiting; the video speeds the clip up itself to fit the 3–4 s proof slot, so a shorter cut plays
  at a more readable speed.
- Raw length is free. Export 1920×1080 H.264. Audio is not used.

## Done when

`roles.mp4` exists, `NUMBERS.md` exists (it may say "all numbers match"), and the
commit SHA used is written at the top of `NUMBERS.md`.
