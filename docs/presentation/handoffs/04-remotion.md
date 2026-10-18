# Handoff 4: Remotion project

**Goal:** a Remotion project in `presentation/` (repository root) that renders

- `out/video.mp4`: the full talk, 1920×1080, 30 fps, at most 4:59, and
- `out/slides.pdf`: the 7 slides, one page each, 1920×1080, from the same slide components,

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
| 1a | Cold open | dark screen; caption "Lawrence Livermore National Laboratory · Blue Gene/L · Saturday, 11 June 2005, 17:17"; subtitles of the 5 dialog lines; corner label "Dramatization: real log data, AI-generated voices" | `dialog.mp3` | the audio |
| 1b | Reveal | facecam full screen, then "152,229 fatal entries · one node · one evening", then the flow line (question → agent picks tool → SereneDB searches / counts → evidence → answer) | `s1-reveal.mp4` | the take |
| 2 | Engineer | slide 2, then `engineer.mp4`; facecam in a corner | `s2-engineer.mp4` | the take |
| 3 | Team lead | slide 3, then `team-lead.mp4`; facecam corner | `s3-team-lead.mp4` | the take |
| 4 | Manager | slide 4, then `manager.mp4`; facecam corner | `s4-manager.mp4` | the take |
| 5 | Evidence | slide 5: an evidence footer with `[Q46]` and its SQL; "152,734 = 152,734" | `s5-evidence.mp4` | the take |
| 6 | Benchmarks | slide 6: "Same questions, graded blind", one bar per design, ours highlighted, score and cost on each bar, footnote | `s6-benchmarks.mp4` | the take |
| 7 | Close | facecam full screen; end card with the repository URL `github.com/ugnmura/serenedb-extractor` | `s7-close.mp4` | the take |

Within a scene where a slide is followed by a recording, show the slide for the first quote and the recording
for the rest; make the split a single constant per scene so handoff 5 can tune it.

## Data, not hard-coded numbers

- All slide numbers and texts come from one file, `src/content.ts`, filled from the script. Each number has a
  comment naming its source (`worked-investigation.md` step, or `benchmarks.json`).
- Slide 6 reads `public/assets/benchmarks.json`:
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
  length from the asset contract when the file is missing.
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
