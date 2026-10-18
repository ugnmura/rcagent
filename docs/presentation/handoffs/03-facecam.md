# Handoff 3: Facecam takes

**Goal:** the presenters' voices and faces for every section after the phone call, one file per section, in
`presentation/public/assets/`. Remotion uses each file's **audio as the narration** and its **video as a
facecam**: full screen for the reveal and the close, a small round frame in a corner over slides and
recordings everywhere else.

## Three presenters

Each presenter "plays" one role. The video shows a name tag the first time each one appears. The names are
set in `presentation/src/content.ts` (`presenters`).

| presenter | sections |
|---|---|
| A | reveal (s1) |
| B | the three roles, one split (s2); the live demo (sDemo) |
| C | benchmarks (s6) |
| all three | close (s7) |

## Files

Read the quotes of each section word for word: [`docs/presentation/speakers.md`](../speakers.md) has them per presenter, with delivery notes (same words as `script.md`).

| file | who | script section | facecam shown as | target length |
|---|---|---|---|---|
| `s1-reveal.mp4` | A | 0:00–1:00, the reveal after the dialog ("The voices are made up." … "Let's answer that phone call.") | full screen, then corner | ≤ 40 s |
| `s2-roles.mp4` | B | Three roles, one split: "B" | corner | about 30 s (target ≤ 30 s) |
| `s-demo.mp4` | B | Live demo: narrate the `demo.mp4` screen recording (handoff 2) as it plays (no name tag, B already appeared) | corner | ≈ 15–25 s |
| `s6-benchmarks.mp4` | C | Benchmarks | corner | ≈ 40 s (three shots, incl. RCAEval) |
| close, see below | all | Close | full screen | ≤ 25 s in total |

`s2-roles.mp4` is the whole split in one take. The three columns build at the same time on screen, so the
words only need to name each role's answer in turn; keep a short pause between the engineer, team lead and
manager sentences and before the closing "And every number is a query". There are no separate
`s3`/`s4`/`s5` takes any more (s3–s5 numbers are skipped on purpose, so s6 and s7 keep their names).

**The close**, either way:

- **Together** in one frame: `s7-close.mp4`, the whole close as one take. If this file exists, it is used.
- **Apart**, three clips with hard cuts between them:

  | file | who | line |
  |---|---|---|
  | `s7-close-a.mp4` | A | "So, that phone call? The engineer gets a cause, not a scroll bar." |
  | `s7-close-b.mp4` | B | "The team lead gets the pattern. Every number traces to a query." |
  | `s7-close-c.mp4` | C | "The manager gets the priority, not a guess. Thank you!" |

  Each ≤ 8 s. Look into the camera.

Record `s6-benchmarks.mp4` last: its numbers are TODO until the benchmark runs finish (handoff 5).

## How to record

- All three use the same setup as far as possible, so the cuts feel like one film: camera at eye level, face
  and shoulders, plain background, light from the front, same distance to the camera.
- Use a headset or clip-on microphone if you have one; the room should be quiet. Audio matters more than video.
  Record a 5 s test and compare the three voices' loudness before the real takes.
- Leave about 1 s of silence before and after each take; Remotion trims nothing, so cut the takes yourself
  to start and end on that silence.
- Speak calmly, about 140 words per minute. Look into the camera for the reveal and the close.
- Several takes are fine; keep only the best one under the file name above.

## Done when

The three section files (`s1-reveal.mp4`, `s2-roles.mp4`, `s6-benchmarks.mp4`) and the close (one joint file
or three clips) exist, each within its target length, `s6` possibly still a placeholder, and the whole talk
(intro, `dialog.mp3`, takes, star) is about 2:20 (limit 4:45). The three names are set in `content.ts`.
