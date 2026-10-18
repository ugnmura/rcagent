# Handoff 3: Facecam takes

**Goal:** the presenter's voice and face for every section after the phone call, one file per section, in
`presentation/public/assets/`. Remotion uses each file's **audio as the narration** and its **video as a
facecam**: full screen for the reveal and the close, a small round frame in a corner over slides and
recordings everywhere else.

## Files

Read the quotes of each section in `docs/presentation/script.md` word for word.

| file | script section | facecam shown as | target length |
|---|---|---|---|
| `s1-reveal.mp4` | 0:00–1:00, the three quotes after the dialog ("The reveal" … "Let's answer that phone call.") | full screen, then corner | ≤ 40 s |
| `s2-engineer.mp4` | 1:00–1:45 Engineer | corner | ≤ 45 s |
| `s3-team-lead.mp4` | 1:45–2:25 Team lead | corner | ≤ 40 s |
| `s4-manager.mp4` | 2:25–3:05 Manager | corner | ≤ 40 s |
| `s5-evidence.mp4` | 3:05–3:40 Why you can trust the numbers | corner | ≤ 35 s |
| `s6-benchmarks.mp4` | 3:40–4:20 Benchmarks | corner | ≤ 40 s |
| `s7-close.mp4` | 4:20–4:45 Close | full screen | ≤ 25 s |

Record `s6-benchmarks.mp4` last: its numbers are TODO until the benchmark runs finish (handoff 5).

## How to record

- Camera at eye level, face and shoulders, plain background, light from the front.
- Use a headset or clip-on microphone if you have one; the room should be quiet. Audio matters more than video.
- Leave about 1 s of silence before and after each take; Remotion trims nothing, so cut the takes yourself
  to start and end on that silence.
- Speak calmly, about 140 words per minute. Look into the camera for the reveal and the close.
- Several takes are fine; keep only the best one under the file name above.

## Done when

All seven files exist (or six plus a placeholder for `s6`), each within its target length, and the sum of
their lengths plus `dialog.mp3` is under 4:45.
