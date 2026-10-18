# Presentation: Making Sense of Logs

Remotion project that renders the demo video (`out/video.mp4`, 1920×1080, 30 fps, ≤ 4:59) and the slides PDF
(`out/slides.pdf`, 7 pages) from the same slide components. Spec: `docs/presentation/handoffs/04-remotion.md`;
words and numbers: `docs/presentation/script.md`.

## Setup

```sh
cd presentation
npm ci
```

Needs Node ≥ 20 and npm. The first render downloads Chrome Headless Shell and the Google Fonts (Inter,
JetBrains Mono), so it needs network once.

## Add assets

Drop files into `public/assets/` under the exact names of the asset contract
(`docs/presentation/handoffs/README.md`):

| file | used as | length sets |
|---|---|---|
| `dialog.mp3` | cold-open audio | scene 1a |
| `s1-reveal.mp4` … `s7-close.mp4` | facecam + narration audio | scenes 1b–7 |
| `engineer.mp4`, `team-lead.mp4`, `manager.mp4` | screen recordings (muted) | nothing; they fill the slot after the slide |
| `benchmarks.json` | slide 6 numbers | – |

A missing file shows a pink, labelled **PLACEHOLDER** of its target length, so everything renders with no assets.
A file that exists but cannot be read fails the check and the render.

## Preview, check, render

```sh
npm run studio   # Remotion Studio: compositions Talk and Slide1..Slide7
npm run check    # type-check, then print each scene's length and the total (fails over 4:59)
npm run render   # out/video.mp4
npm run slides   # out/slides/SlideN.png and out/slides.pdf
```

## Tune (handoff 5)

All in `src/timeline.ts`:

- `SLIDE_SECONDS`: per role scene, how long the slide shows before the recording (the first quote).
  `npm run check` warns when a recording is longer than its slot (it would be cut).
- `END_CARD_SECONDS`: how long the end card shows at the end of the close.
- Subtitle cues (in `src/content.ts`) share each scene in proportion to their length, after 1 s of silence
  (2 s ring for the dialog). Split or join cues there if one lands early or late.

## Numbers

Every slide text and number is in `src/content.ts`, each with a comment naming its source
(`docs/worked-investigation.md` section and transcript step). Slide 6 reads only `public/assets/benchmarks.json`;
while `"final"` is false or any value is null it shows a TODO stamp instead of numbers. Never put guessed
numbers there.
