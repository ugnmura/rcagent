# Handoff 1: Dialog audio (ElevenLabs)

**Goal:** `presentation/public/assets/dialog.mp3`, 18–24 seconds: a phone rings, then five lines between three
voices. It opens the video under the caption "Lawrence Livermore National Laboratory · Blue Gene/L · Saturday,
11 June 2005, 17:17".

**Who:** a person with an ElevenLabs account. The free plan (about 10,000 credits a month, roughly one credit
per character) covers this dialog (about 300 characters) many times over. Check the plan's terms on commercial
use and attribution; if attribution is required, tell handoff 4 to add "Voices: ElevenLabs" to the slide label.

## Lines

| # | Voice | Tone | Line |
|---|---|---|---|
| 1 | Engineer on call | tired, quiet, slightly hoarse | "Yes, I'm looking at it. One node on Blue Gene/L, R30-M0-N9. Data TLB errors, fatal. Twenty-four thousand an hour." |
| 2 | Team lead | worried, quick | "Has this happened before?" |
| 3 | Engineer | unsure | "I don't know. The log is millions of lines." |
| 4 | Manager | calm, firm | "How bad is it? Do we act tonight?" |
| 5 | Engineer | resigned | "Give me a few hours." |

Say "R30-M0-N9" as "R thirty, M zero, N nine". If the voice stumbles, spell it that way in the input text.

## Steps

1. Pick three clearly different voices (for example two different ages or accents). The engineer must be
   recognisable across lines 1, 3 and 5.
2. Generate with the dialogue mode if your plan has it; otherwise generate one clip per line with the same
   settings.
3. Add a phone ring (about 1.5 s) before line 1 and, if you like, a sigh plus keyboard sounds after line 5.
   Royalty-free sound effects only; note their source.
4. Stitch with about 0.4 s of silence between lines, e.g. with ffmpeg:
   `ffmpeg -f concat -safe 0 -i list.txt -c:a libmp3lame -ar 44100 dialog.mp3`
5. Listen once at full volume and once on laptop speakers. Every word must be understandable.

## Done when

- `dialog.mp3` is in `presentation/public/assets/`, 18–24 s long (`ffprobe -show_entries format=duration`).
- A short `presentation/public/assets/CREDITS.md` names the ElevenLabs voices and any sound-effect sources.
- The transcript of the file matches the five lines above word for word (the subtitles in the video use the
  table above).
