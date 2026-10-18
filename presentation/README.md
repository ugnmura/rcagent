# Presentation: Making Sense of Logs

Remotion project that renders the demo video (`out/video.mp4`, 1920×1080, 30 fps, ≤ 4:59) and the slides PDF
(`out/slides.pdf`, 5 pages) from the same slide components. Spec: `docs/presentation/handoffs/04-remotion.md`;
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
| `s7-close-a.mp4`, `s7-close-b.mp4`, `s7-close-c.mp4` | one close clip per presenter (≤ 8 s each), used only while the joint take `s7-close.mp4` is missing; played back to back with hard cuts | scene 7 (their sum) |
| `roles.mp4` | one screen recording (muted), the three role prompts | nothing; played ~3× as the split's proof clip |
| `benchmarks.json` | slide 6 numbers | – |
| `music.mp3` (optional) | music bed under the whole talk: loops, low, ducked under every voice, fades in and out | nothing |

A missing file shows a pink, labelled **PLACEHOLDER** of its target length, so everything renders with no assets.
The one exception is `music.mp3`: missing means silence, with no placeholder. Its levels (`MUSIC_VOLUME`: open
and ducked) are in `src/music.tsx`.
A file that exists but cannot be read fails the check and the render.

## Presenters

Three presenters share the talk: A takes s1 (reveal) and s2 (engineer), B takes s3 (team lead) and s5 (evidence),
C takes s4 (manager) and s6 (benchmarks); the close is all three. Names live in `presenters` in `src/content.ts`
(placeholders "Presenter A/B/C" until filled; an optional `role` adds a second line), the take → presenter map in
`sectionPresenter`. A lower-third name tag slides in once, at each presenter's first appearance (s1, s3, s4).
In the split close each clip shows its speaker's tag. Placeholders name the presenter
("PLACEHOLDER · Presenter B · s3-team-lead.mp4").

## Preview, check, render

```sh
npm run studio   # Remotion Studio: compositions Talk and Slide1..Slide5
npm run check    # type-check, then print each scene's length and the total (fails over 4:59)
npm run render   # out/video.mp4
npm run slides   # out/slides/SlideN.png and out/slides.pdf
node scripts/stills.mjs name:frame ...   # single frames of the talk as out/name.png
```

## Look (film style)

Every scene is in film style: one idea per shot (one big number or a phrase of at most six words), slow push-in on
every shot, hard cuts on beats, fades to black between acts, film grain and vignette, letterbox bars (2.39:1) in
the cold open, a chapter card before each role. Narration subtitles are off; only the AI dialog of the cold open
keeps subtitles (in the bottom letterbox bar), because those voices have no facecam.

Order: a 3 s intro card (`INTRO_SECONDS`: "National AI Hackathon 2026", SchubKI × SereneDB), scenes 1a–7, then a
4 s star gag (`STAR_SECONDS`). Both are fixed lengths in `src/timeline.ts` and count towards the 4:59 limit; they
are not PDF pages. Logos live in `public/assets/logos/` (sources in `SOURCES.md`): SchubKI is its text wordmark,
the SereneDB SVG is used unchanged on a light plate (its wordmark is black).

Primitives live in `src/film.tsx`, shots in `src/shots.tsx` (1a–2) and `src/shots2.tsx` (intro, 3–7, star), the
scenes in `src/scenes.tsx`. The slides PDF renders each page from the final, fully built state of its shots.

## Tune (handoff 5)

All in `src/timeline.ts`:

- `SPLIT_HOLD_SECONDS`, `PROOF_RATE`: the pause before the evidence take in the split, and the proof clip's speed.
  `npm run check` warns when a recording is longer than its slot (it would be cut).
- `END_CARD_SECONDS`: how long the end card shows at the end of the close.
- Subtitle cues (in `src/content.ts`) share each scene in proportion to their length, after 1 s of silence
  (2 s ring for the dialog). Split or join cues there if one lands early or late.

## Numbers

Every slide text and number is in `src/content.ts`, each with a comment naming its source
(`docs/worked-investigation.md` section and transcript step). Slide 6 reads only `public/assets/benchmarks.json`;
while `"final"` is false or any value is null it shows a TODO stamp instead of numbers. Never put guessed
numbers there.
