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
| A | reveal (s1), engineer column of the split (s2) |
| B | team lead column (s3), evidence (s5) |
| C | manager column (s4), benchmarks (s6) |
| all three | close (s7) |

## Files

Read the quotes of each section in `docs/presentation/script.md` word for word.

| file | who | script section | facecam shown as | target length |
|---|---|---|---|---|
| `s1-reveal.mp4` | A | 0:00–1:00, the three quotes after the dialog ("The reveal" … "Let's answer that phone call.") | full screen, then corner | ≤ 40 s |
| `s2-engineer.mp4` | A | Three roles: "A, engineer column" | corner | ≤ 32 s |
| `s3-team-lead.mp4` | B | Three roles: "B, team lead column" | corner | ≤ 25 s |
| `s4-manager.mp4` | C | Three roles: "C, manager column" | corner | ≤ 25 s |
| `s5-evidence.mp4` | B | Three roles: "B, evidence" | corner | ≤ 15 s |
| `s6-benchmarks.mp4` | C | Benchmarks | corner | ≤ 15 s |
| close, see below | all | Close | full screen | ≤ 25 s in total |

s2–s5 play back to back as one scene; each column builds on its presenter's sentences, so read them in
order and keep a short pause between sentences.

**The close**, either way:

- **Together** in one frame: `s7-close.mp4`, the whole close as one take. If this file exists, it is used.
- **Apart**, three clips with hard cuts between them:

  | file | who | line |
  |---|---|---|
  | `s7-close-a.mp4` | A | "So, back to that phone call. The engineer gets a cause to check, not a scroll bar." |
  | `s7-close-b.mp4` | B | "The team lead gets the pattern. And every number is traceable to a query." |
  | `s7-close-c.mp4` | C | "The manager gets the priority. Thank you." |

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

All six section files and the close (one joint file or three clips) exist, each within its target length,
`s6` possibly still a placeholder, and the sum of their lengths plus `dialog.mp3` is about 3:30 (limit 4:45). The three
names are set in `content.ts`.
