# Handoff 5: Combine and check

**Goal:** the final `presentation/out/video.mp4` (≤ 4:59, target ≤ 4:45) and `presentation/out/slides.pdf`,
with every number checked.

**Starts when:** handoffs 1–4 are done and the benchmark runs have finished.

## Steps

1. **Pick the commit we present.** Use the commit the role recordings ran on (top of
   `presentation/public/assets/NUMBERS.md`). Benchmark numbers must be for that commit; if the final benchmark
   ran on another commit, say so in the slide footnote ("benchmarked version: <sha>").
2. **Fill the benchmark numbers.** From the final benchmark report, write score and cost per answer for each
   design into `presentation/public/assets/benchmarks.json`, set the footnote (model, number of questions,
   runs per question, blind grader) and `"final": true`. Copy numbers exactly; add the report path and commit
   as a `"source"` field. Then fill the two `[TODO]` markers in the script's benchmark section with the same
   numbers, and tick the TODO checklist there.
3. **Apply live numbers.** For every row in `NUMBERS.md` where the live number differs, update
   `docs/presentation/script.md`, the Claude Doc, and `presentation/src/content.ts` together. Re-record the
   affected facecam take if the spoken number changed.
   The evidence handle is a live value too: the script and slide 3 say `[Q46]`, but each session numbers its
   own queries. Use the handle the engineer recording shows (in `content.ts` `handle`, the script and the doc).
4. **Drop in the assets** and run `npm run check`. Tune `SPLIT_HOLD_SECONDS` / `PROOF_RATE` in `presentation/src/timeline.ts`
   per scene so each recording gets its full length; `npm run check` warns when a recording is cut.
5. **Render** `npm run render` and `npm run slides`.

## Check (all must pass before calling it done)

- Length: `ffprobe -show_entries format=duration out/video.mp4` prints at most 299 s.
- Every number on screen and in the subtitles appears in the script, and every number in the script appears
  in `worked-investigation.md`, the benchmark report or `NUMBERS.md`.
- The cold open shows the dramatization label for its whole length.
- Subtitles match the spoken words.
- Watch the full video once at normal speed with sound, and once muted (subtitles only).
- The PDF has 5 pages, readable at 100 % zoom, and no TODO stamps.

## Deliver

Tell the user the paths of the two files, their length and page count, and anything that still differs from
the script. Do not upload or submit them; the user submits.
