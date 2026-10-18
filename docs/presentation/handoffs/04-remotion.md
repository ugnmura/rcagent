# Handoff 4: Remotion project

**Goal:** a Remotion project in `presentation/` (repository root) that renders

- `out/video.mp4`: the full talk, 1920×1080, 30 fps, at most 4:59, and
- `out/slides.pdf`: the 5 slides, one page each, 1920×1080, from the same slide components,

and that works **before any asset exists**: every missing asset shows a labelled placeholder of its target
length (see the asset contract in [README.md](README.md)).

## Build on

- The script `docs/presentation/script.md`: sections, quotes (narration and subtitles), italic cues (what is on
  screen) and the slide list.
- Remotion docs at https://www.remotion.dev/docs (licence: free for individuals and companies up to 3 people).
- Node 26 and ffmpeg are installed. Use npm.

## Scenes (in order)

| # | scene | visuals | audio | length from |
|---|---|---|---|---|
| 0 | Intro card | title card before the cold open | none | fixed, `INTRO_SECONDS` (3 s) |
| 1a | Cold open | dark screen; caption "Lawrence Livermore National Laboratory · Blue Gene/L · Saturday, 11 June 2005, 17:17"; subtitles of the 5 dialog lines; corner label "Dramatization: real log data, AI-generated voices" | `dialog.mp3` | the audio |
| 1b | Reveal | facecam full screen, then "152,229 fatal entries · one node · one evening", then the flow line (question → agent picks tool → SereneDB searches / counts → evidence → answer) | `s1-reveal.mp4` | the take |
| 2 | Three roles (split) | proof clip: `roles.mp4` sped up in a terminal frame; the answers lift into three columns (Question / Evidence / Next step: engineer, team lead, manager) that build on each presenter's cues, then all lit ("One log. Three answers."); then a push into the `Q46` handle: the `show_evidence` view with its SQL and "152,734 = 152,734", and back to the table. Facecam in a corner | `s2-engineer.mp4`, `s3-team-lead.mp4`, `s4-manager.mp4`, a short silent hold, `s5-evidence.mp4`, back to back | the four takes plus the hold |
| 3 | Benchmarks | slide 4: "Same questions, graded blind", one bar per design, ours highlighted, score and cost on each bar, footnote | `s6-benchmarks.mp4` | the take |
| 4 | Close | facecam full screen; end card with the repository URL `github.com/ugnmura/serenedb-extractor` for the last `END_CARD_SECONDS` | `s7-close.mp4` (while it is missing: `s7-close-a/b/c.mp4` back to back) | the take(s) |
| 5 | Star gag | star button with a click, gold burst and sound effects | sound effects | fixed, `STAR_SECONDS` (6 s) |

The split is one scene (`SPLIT_PARTS` in `src/timeline.ts`: s2, s3, s4, s5); its column timing follows the take
lengths and the row builds follow the subtitle cues. Two constants in `src/timeline.ts` let handoff 5 tune it:
`SPLIT_HOLD_SECONDS` (the silent hold between s4 and s5 where "all lit" lands, at most 1 s) and `PROOF_RATE`
(playback speed of `roles.mp4` in the proof clip, about 3×). Design: `docs/superpowers/specs/2026-10-19-three-way-split-design.md`.

Slides (`src/slides/index.tsx`): 1 title (the reveal's final frame), 2 the split's final frame (all three columns
lit), 3 evidence (`Q46` citation and "152,734 = 152,734"), 4 benchmarks, 5 close. Each page is the fully built
final state of its video shots.

## Data, not hard-coded numbers

- All slide numbers and texts come from one file, `src/content.ts`, filled from the script. Each number has a
  comment naming its source (`worked-investigation.md` step, or `benchmarks.json`).
- Slide 4 (and the benchmarks scene) reads `public/assets/benchmarks.json`:
  ```json
  {
    "final": false,
    "footnote": "TODO: model, questions, runs per question, blind grader",
    "designs": [
      {"name": "Ours: template catalog + evidence", "score_pct": null, "usd_per_answer": null, "ours": true},
      {"name": "Lean server, no index", "score_pct": null, "usd_per_answer": null, "ours": false},
      {"name": "Broad toolbox", "score_pct": null, "usd_per_answer": null, "ours": false}
    ]
  }
  ```
  While `final` is false or a value is null, the slide shows a visible "TODO" stamp instead of numbers.
  Commit this file with nulls; never put guessed numbers in it.

## Timing

- Use `calculateMetadata` to read each asset's real duration (audio/video), falling back to the placeholder
  length from the asset contract when the file is missing (take targets: s2 ≤ 32 s, s3 ≤ 25 s, s4 ≤ 25 s,
  s5 ≤ 15 s, s6 ≤ 15 s; `roles.mp4` any length, it is sped up).
- Fail the render with a clear message if the total exceeds 4:59 (and print the per-scene lengths).

## Look

- Dark theme, one accent colour for "ours" and for highlighted numbers, one sans-serif font (bundled or Google
  Fonts via `@remotion/google-fonts`), large type: slide body ≥ 40 px.
- Subtitles for every narration line (from the script quotes), bottom centre, readable on a phone.
- No logos of SereneDB, RWTH or LLNL unless a later handoff provides them with permission.

## Scripts (package.json)

- `npm run studio`: Remotion Studio.
- `npm run render`: `out/video.mp4`.
- `npm run slides`: render each slide composition as a PNG still and combine them into `out/slides.pdf`
  (any small Node library such as `pdf-lib` is fine; ImageMagick is not installed).
- `npm run check`: type-check and print the scene lengths and the total.

## Done when

- `npm run render` and `npm run slides` succeed from a clean `npm ci`, with no assets present (all
  placeholders), and the video is under 4:59.
- `presentation/README.md` says how to add assets, preview, render and export the PDF.
- `out/`, `node_modules/` are git-ignored. The work is committed on branch `feat/presentation` (not pushed).
