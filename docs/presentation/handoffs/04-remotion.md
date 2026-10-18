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
| 2 | Three roles (split) | proof clip (3–4 s): `roles.mp4` sped up to fit, in a terminal frame; then three columns (Engineer / Team lead / Manager) build **at the same time**, each question → the role's tool calls → a one-line answer + next step; then all three lit ("One log. Three answers.") with a quick evidence beat: `Q46` → "152,734 = 152,734". No step-by-step examples, no separate evidence scene. B's facecam in a corner | `s2-roles.mp4` (B, one take) | the take (about 30 s) |
| 3 | Benchmarks | slide 4: "Same questions, graded blind", one bar per design, ours highlighted, score and cost on each bar, footnote | `s6-benchmarks.mp4` | the take |
| 4 | Close | facecam full screen; end card with the repository URL `github.com/ugnmura/serenedb-extractor` for the last `END_CARD_SECONDS` | `s7-close.mp4` (while it is missing: `s7-close-a/b/c.mp4` back to back) | the take(s) |
| 5 | Star gag | star button with a click, gold burst and sound effects | sound effects | fixed, `STAR_SECONDS` (6 s) |

The split is one scene on one take, `s2-roles.mp4` (presenter B); its length is that take's length. The three
columns build in parallel, and the moments where each role's answer, "all lit" and the evidence beat land
follow B's subtitle cues. The proof clip plays `roles.mp4` at whatever speed fits it into 3–4 s (tunable in
`src/timeline.ts`). Takes `s3-team-lead.mp4`, `s4-manager.mp4` and `s5-evidence.mp4` no longer exist. Design:
`docs/superpowers/specs/2026-10-19-three-way-split-design.md` (revision 2026-10-19).

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
    "questions": 30,
    "runs": 5,
    "designs": [
      {"name": "Drain3 + SQL (ours)", "detail": "Drain3 templates per question · 8 core tools + run_sql", "short": "Drain3 + SQL", "score_pct": null, "usd_per_answer": null, "ours": true},
      {"name": "7 fixed tools", "detail": "fixed query tools · no Drain3 templates", "short": "7 fixed tools", "score_pct": null, "usd_per_answer": null, "ours": false},
      {"name": "18 fixed tools", "detail": "fixed query tools · no Drain3 templates", "short": "18 fixed tools", "score_pct": null, "usd_per_answer": null, "ours": false}
    ]
  }
  ```
  While a value is null, the slide shows a visible "TODO" stamp instead of numbers; while `final` is false, filled numbers carry a pink PLACEHOLDER tag. "7 fixed tools" was v2 (the lean toolkit), "18 fixed tools" was v1 (the full toolkit).
  Commit this file with nulls; never put guessed numbers in it.

## Timing

- Use `calculateMetadata` to read each asset's real duration (audio/video), falling back to the placeholder
  length from the asset contract when the file is missing (take targets: s1 ≤ 40 s, s2 ≤ 30 s, s6 ≤ 15 s,
  close ≤ 25 s; `roles.mp4` any length, it is sped up to fit).
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
