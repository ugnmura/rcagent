# Presentation handoffs

Deliverables for the *Making Sense of Logs* submission:

1. **A video of at most 5:00** (target 4:45 or less), rendered with Remotion.
2. **A PDF of the slides**, rendered from the same slide components.

The script is the single source of truth: [../script.md](../script.md). Its quotes are the narration, its
italic cues are what is on screen, and its timestamps are targets. A live copy for comments is the Claude Doc
"Demo script: Making Sense of Logs" (https://claude.ai/code/artifact/f595c6a2-778f-4cff-adb4-36dfbbdb218a). If
the two differ, ask which one wins before building on either.

## Format decided

- **Hybrid.** Only the cold-open phone call is AI-generated (ElevenLabs voices, labelled as a dramatization).
  Everything after the reveal is a real presenter: facecam plus voice, over slides and screen recordings.
- **Remotion** assembles everything. The project lives in `presentation/` at the repository root.

## Handoffs

| # | Handoff | Who | Needs | Produces |
|---|---|---|---|---|
| 1 | [Dialog audio](01-dialog-audio.md) | a person (ElevenLabs account) | script table | `dialog.mp3` |
| 2 | [Role recordings](02-role-recordings.md) | a person, or Claude driving a terminal | loaded SereneDB, MCP server; **after the benchmark runs finish** | `engineer.mp4`, `team-lead.mp4`, `manager.mp4` |
| 3 | [Facecam takes](03-facecam.md) | the presenter | script | `s1-reveal.mp4` … `s7-close.mp4` |
| 4 | [Remotion project](04-remotion.md) | Claude | script | the project, with placeholders for every asset |
| 5 | [Combine and check](05-combine.md) | Claude + a person | 1–4 done, benchmark numbers final | `out/video.mp4`, `out/slides.pdf` |

1–4 run in parallel. 5 waits for all of them.

## Asset contract (shared by every handoff)

All assets go into `presentation/public/assets/`. Remotion reads them by these exact names. Until an asset
exists, the project shows a labelled placeholder of the target length.

| file | content | format | length |
|---|---|---|---|
| `dialog.mp3` | the five dialog lines, with pauses and a phone ring at the start | MP3, 44.1 kHz | 18–24 s |
| `engineer.mp4` | screen recording of the `/engineer` answer | 1920×1080, H.264, no audio needed | ≤ 40 s after speed-up |
| `team-lead.mp4` | screen recording of the `/team-lead` answer | same | ≤ 35 s |
| `manager.mp4` | screen recording of the `/manager` answer | same | ≤ 35 s |
| `s1-reveal.mp4` … `s7-close.mp4` | facecam with voice, one file per script section (names in handoff 3) | 1080p or 720p, H.264 + AAC | as spoken |
| `benchmarks.json` | final benchmark numbers (handoff 5) | JSON, shape in handoff 4 | – |

Scene lengths come from the asset lengths, so a longer take moves everything after it. The render fails if the
total is over 4:59.

## Rules for every handoff

- Every number on screen or in narration must match the script; the script's numbers come from
  `docs/worked-investigation.md` and the benchmark report. Never invent or round a number differently.
- Keep the "Dramatization: real log data, AI-generated voices" label on the cold open.
- Commit nothing to `main`; work on branch `feat/presentation`. Do not push without asking.
