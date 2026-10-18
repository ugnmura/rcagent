# Three-way Split Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the engineer, team lead, manager and evidence scenes with one split scene (proof clip → three columns → evidence push-in) and shorten benchmarks, per the spec.

**Architecture:** One new scene `split` whose length is the sum of the takes s2 + s3 + s4 + a hold + s5 (like the close's `parts`). A new file `src/split.tsx` holds the scene and its shots; it reads every text from `content.ts` (new `split` block) and reuses `Ring`, `DaysRing`, `CitationShot`, `SnapShot` and the existing sfx. Row builds are keyed to `cueFrames` of each take's cues.

**Tech Stack:** Remotion 4.0.536, React, TypeScript.

**Spec:** `docs/superpowers/specs/2026-10-19-three-way-split-design.md`

## Global Constraints

- Never render (no `remotion render`, `scripts/stills.mjs`, `scripts/check.mjs`, `npm run render|check|slides`). Verify with `npx tsc --noEmit` only. The user previews in Remotion Studio.
- No new numbers: every number on screen already exists in `content.ts`.
- Another session is editing `scenes.tsx`, `content.ts` and `docs/presentation/script.md` (cold open). Touch those only with exact-match edits away from the cold open, and commit only this plan's files and hunks.
- Take targets: s2 ≤ 32 s, s3 ≤ 25 s, s4 ≤ 25 s, s5 ≤ 15 s, s6 ≤ 15 s. Proof clip ≈ 6 s. Hold between s4 and s5 ≤ 1 s.
- One recording `roles.mp4` replaces `engineer.mp4`, `team-lead.mp4`, `manager.mp4`; played ≈ 3×.

## Review Focus

- All takes missing (today's state): the split must still run on placeholders with sensible lengths and readable columns.
- A real take much shorter or longer than its target: cues scale with the take, so rows still build in order and never before the lift-off.
- `roles.mp4` shorter than the proof slot at 3×: hold its last frame, no black.
- The final frame of beat 6 has to be readable at 1080p: minimum 26 px body text in columns.
- Facecam corner (bottom right, 200 px) must not cover column content.

---

### Task 1: Timeline, assets and content model

**Files:**
- Modify: `presentation/src/timeline.ts` (scene list, `split` parts, drop `SLIDE_SECONDS` and recording slots)
- Modify: `presentation/src/assets.ts` (`rolesRec`, new take targets)
- Modify: `presentation/src/content.ts` (append a `split` block)

**Interfaces:**
- Produces: `SceneId` gains `'split'`, loses `'engineer' | 'teamLead' | 'manager' | 'evidence'`; `SPLIT_PARTS: AssetKey[] = ['s2','s3','s4','s5']`; `SPLIT_HOLD_SECONDS = 0.8`; the split `SceneTiming.parts` lists the four takes with frames; `PROOF_RATE = 3`.
- Produces: `split` content: `header: {ask, answer, scope}`, `columns: [{key, role, presenter take, question, cues, at: {...cue indices}, next, ...}]`, `evidence.cues`, `proof.cues`.

- [ ] Step 1: edit the three files; `assets.rolesRec = {file: 'roles.mp4', kind: 'recording', placeholderSeconds: 18, target: 'any length (played ~3×)'}`; s2 32, s3 25, s4 25, s5 15, s6 15 placeholder seconds and targets.
- [ ] Step 2: `npx tsc --noEmit` — expected failures only in `Talk.tsx` / `scenes.tsx` references (fixed in Task 2).

### Task 2: Split scene

**Files:**
- Create: `presentation/src/split.tsx` (`SplitScene: React.FC<{assets; frames; parts}>`)
- Modify: `presentation/src/Talk.tsx` (render `split`), `presentation/src/scenes.tsx` (remove `EngineerScene`, `TeamLeadScene`, `ManagerScene`, `EvidenceScene`, `RoleScene`, `ScreenInFilm`, `ChapterCard` use; keep `ActScene` for benchmarks)

- [ ] Step 1: proof clip (rolesRec at `PROOF_RATE`, or a placeholder) until A's third cue; lift-off of three column panels from the terminal rect, staggered, with whoosh.
- [ ] Step 2: columns with Question / Evidence / Next rows; active column lit, others dimmed; rows land on cues with springs, count-ups and a soft click.
- [ ] Step 3: all-lit on C's last cue through the hold into s5's first cue; header crossfades to the answer line; chime.
- [ ] Step 4: evidence: push into the Q46 chip, `CitationShot` then `SnapShot`, pull back to the table at the end.
- [ ] Step 5: facecams per part in the corner; name tags for B (s3) and C (s4) at their first appearance.
- [ ] Step 6: `npx tsc --noEmit` passes; commit.

### Task 3: Slides and docs

**Files:**
- Modify: `presentation/src/slides/index.tsx` (Slides 2–4 → one split page from the beat-6 frame; evidence page stays), `presentation/scripts/slides.mjs` (`SLIDE_COUNT`)
- Modify: `docs/presentation/handoffs/02-role-recordings.md`, `03-facecam.md`, `docs/presentation/script.md` (split section)

- [ ] Step 1: edit; `npx tsc --noEmit` passes; commit.
