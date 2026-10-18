// Scene 2: the three roles as one split, in one take by presenter B. B opens full screen for his first sentence, then
// the webcam shrinks to the corner as three flat cards (icon, role, a short question) come in side by side; each role then takes centre stage in turn and lands up to three short facts while the other
// two wait, small and dimmed, at the sides; at the end all three come back lit with a one-line answer, and
// 152,734 = 152,734 lands under them. Texts: `split` in content.ts.
// `SplitBoard` with DONE_TIMES draws the final state for the slides PDF.
import React from 'react';
import {AbsoluteFill, Audio, interpolate, Sequence, spring, staticFile, useCurrentFrame, useVideoConfig} from 'remotion';
import {type ResolvedAssets} from './assets';
import {split, type SplitFact, type SplitRole} from './content';
import {BlackFades, easeOut, FilmFacecam, Grain, NameTag, ramp, Vignette} from './film';
import {DaysRing} from './shots2';
import {color, font} from './theme';
import {cueFrames} from './timeline';

const INK = '#0b0f14';
/** Flat card surface and borders: neutral, no gradients, no gold. */
const CARD_BG = '#11161d';
const BORDER_LIT = '#4a525c';
/** Calm springs: little or no overshoot. */
const MOVE = {damping: 26, stiffness: 90, mass: 1};
const LAND = {damping: 22, stiffness: 120, mass: 0.8};
const NAME_TAG_FRAMES = 90;
/** Row: three cards side by side. Focus: one big card centre stage, the other two small and dimmed at the sides. */
const ROW_W = 520;
const ROW_GAP = 50;
const ROW_TOP = 214;
/** Card height with icon, role and question; with the one-line answer below (the lit row). */
const ASK_H = 290;
const LIT_H = 390;
const FOCUS = {cx: 960, top: 196, w: 860, h: 540};
const SIDE = {cx: [250, 1670], cy: 440, s: 0.6, dim: 0.42};
/** Rows inside a card, from its top. */
const Y = {icon: 34, role: 122, line: 192, question: 212, answer: 298, fact: 300, factStep: 78};
const ENTER_STAGGER = 7;
const COUNT_FRAMES = 24;
/** The equals sign fades in this many frames after the evidence line arrives (once both sides have counted up). */
const EQ_DELAY = 28;

/** Scene-relative frames of each beat. */
export type SplitTimes = {
	liftoff: number;
	/** Each role takes centre stage (until the next one does, the last until `allLit`). */
	spot: [number, number, number];
	allLit: number;
	/** 152,734 = 152,734 arrives under the cards. */
	evidence: number;
};

/** Everything landed, all three cards back in the row and lit, no transient effect running: the slides PDF page. */
export const DONE_TIMES: SplitTimes = {liftoff: -1000, spot: [-1000, -1000, -1000], allLit: -1000, evidence: -1000};

/** Frames at which each role's facts land: spread over its time at centre stage, roughly following B's sentence. */
const factTimes = (T: SplitTimes) =>
	T.spot.map((s, k) => {
		const end = k < 2 ? T.spot[k + 1] : T.allLit;
		const gap = Math.max(16, Math.min(64, Math.round((end - s) * 0.27)));
		return [0, 1, 2].map((j) => s + 16 + j * gap);
	});
const answerAt = (T: SplitTimes, i: number) => T.allLit + 14 + i * 6;

// ---------------------------------------------------------------- layout

type Pose = {cx: number; cy: number; w: number; h: number; s: number; dim: number; focus: number};

const rowPose = (i: number, h: number): Pose => ({cx: 960 + (i - 1) * (ROW_W + ROW_GAP), cy: ROW_TOP + h / 2, w: ROW_W, h, s: 1, dim: 1, focus: 0});

/** Card i while role k has centre stage; the other two keep their order, one on each side. */
const focusPose = (i: number, k: number): Pose => {
	if (i === k) return {cx: FOCUS.cx, cy: FOCUS.top + FOCUS.h / 2, w: FOCUS.w, h: FOCUS.h, s: 1, dim: 1, focus: 1};
	const side = [0, 1, 2].filter((j) => j !== k).indexOf(i);
	return {cx: SIDE.cx[side], cy: SIDE.cy, w: ROW_W, h: ASK_H, s: SIDE.s, dim: SIDE.dim, focus: 0};
};

const mix = (a: Pose, b: Pose, p: number): Pose => {
	const l = (x: number, y: number) => x + (y - x) * p;
	return {cx: l(a.cx, b.cx), cy: l(a.cy, b.cy), w: l(a.w, b.w), h: l(a.h, b.h), s: l(a.s, b.s), dim: l(a.dim, b.dim), focus: l(a.focus, b.focus)};
};

/** Card i at `frame`: the row, then each centre-stage move, then the lit row, each eased in by a calm spring. */
const poseAt = (i: number, frame: number, fps: number, T: SplitTimes): Pose => {
	const moves: [number, Pose][] = [
		[T.spot[0], focusPose(i, 0)],
		[T.spot[1], focusPose(i, 1)],
		[T.spot[2], focusPose(i, 2)],
		[T.allLit, rowPose(i, LIT_H)],
	];
	return moves.reduce(
		(pose, [at, target]) => mix(pose, target, spring({frame: frame - at, fps, config: MOVE})),
		rowPose(i, ASK_H),
	);
};

const clamp01 = (v: number) => Math.max(0, Math.min(1, v));

// ---------------------------------------------------------------- pieces

/** `token` ("17.8%", "+91%", "152,734") at `p` of its value, keeping its prefix, suffix, decimals and commas. */
const countUp = (token: string, p: number) => {
	const m = token.match(/^(\D*)([\d,]*\.?\d+)(.*)$/);
	if (!m) return token;
	const digits = m[2].replace(/,/g, '');
	const dec = (digits.split('.')[1] ?? '').length;
	return m[1] + (Number(digits) * p).toLocaleString('en-US', {minimumFractionDigits: dec, maximumFractionDigits: dec}) + m[3];
};

/** A fact's text with its `count` part counting up in the accent colour (the only gold text in the scene). */
const Counted: React.FC<{fact: SplitFact; p: number}> = ({fact, p}) => {
	const i = fact.count ? fact.text.indexOf(fact.count) : -1;
	if (!fact.count || i < 0) return <>{fact.text}</>;
	return (
		<>
			{fact.text.slice(0, i)}
			<span style={{color: color.accent, fontWeight: 800, fontVariantNumeric: 'tabular-nums'}}>{countUp(fact.count, p)}</span>
			{fact.text.slice(i + fact.count.length)}
		</>
	);
};

/** Stroke paths on a 48×48 grid: a magnifier (engineer), a loop (team lead), ranked bars (manager). */
const ICONS: Record<SplitRole['icon'], string[]> = {
	probe: ['M 20 8 a 12 12 0 1 1 -0.01 0', 'M 29 29 L 41 41'],
	loop: ['M 38 24 A 14 14 0 1 1 33.9 14.1', 'M 25.9 13.4 L 33.9 14.1 L 33.2 6.1'],
	bars: ['M 8 12 H 40', 'M 8 24 H 31', 'M 8 36 H 21'],
};

/** The role's icon, drawn stroke by stroke as `draw` goes 0→1. */
const Icon: React.FC<{name: SplitRole['icon']; draw: number}> = ({name, draw}) => {
	const paths = ICONS[name];
	return (
		<svg width={76} height={76} viewBox="0 0 48 48">
			{paths.map((d, j) => {
				const p = clamp01(draw * paths.length - j);
				return (
					<path
						key={j}
						d={d}
						pathLength={1}
						strokeDasharray={1}
						strokeDashoffset={1 - p}
						fill="none"
						stroke={color.accent}
						strokeWidth={3}
						strokeLinecap="round"
						strokeLinejoin="round"
						opacity={p > 0 ? 1 : 0}
					/>
				);
			})}
		</svg>
	);
};

/** One fact on the centre-stage card: slides up softly, its number counts up (and the days ring fills). */
const Fact: React.FC<{fact: SplitFact; at: number; top: number; vis: number}> = ({fact, at, top, vis}) => {
	const frame = useCurrentFrame();
	const {fps} = useVideoConfig();
	const s = spring({frame: frame - at, fps, config: LAND});
	const p = ramp(frame, at + 2, at + 2 + COUNT_FRAMES, easeOut);
	const tone: React.CSSProperties =
		fact.tone === 'accent'
			? {color: color.text, fontWeight: 700}
			: fact.tone === 'muted'
				? {color: color.muted, fontStyle: 'italic'}
				: {color: color.text};
	return (
		<div
			style={{
				position: 'absolute',
				left: 0,
				right: 0,
				top,
				height: 60,
				display: 'flex',
				alignItems: 'center',
				justifyContent: 'center',
				gap: 18,
				fontSize: 38,
				fontWeight: 600,
				whiteSpace: 'nowrap',
				opacity: Math.min(1, s * 1.3) * vis,
				transform: `translateY(${(1 - s) * 16}px)`,
				...tone,
			}}
		>
			{fact.ring ? <DaysRing lit={Number(fact.count ?? 0) * p} r={20} stroke={7} /> : null}
			<span>
				<Counted fact={fact} p={p} />
			</span>
		</div>
	);
};

const Card: React.FC<{i: number; role: SplitRole; pose: Pose; T: SplitTimes; facts: number[]}> = ({i, role, pose, T, facts}) => {
	const frame = useCurrentFrame();
	const {fps} = useVideoConfig();
	const at = T.liftoff + i * ENTER_STAGGER;
	const enter = spring({frame: frame - at, fps, config: LAND});
	const draw = ramp(frame, at + 4, at + 30, easeOut);
	const line = ramp(frame, at + 12, at + 34, easeOut);
	const ask = ramp(frame, at + 16, at + 32, easeOut);
	const focus = clamp01(pose.focus);
	const vis = clamp01((focus - 0.4) / 0.4);
	const ans = spring({frame: frame - answerAt(T, i), fps, config: LAND});
	const ansP = ramp(frame, answerAt(T, i) + 2, answerAt(T, i) + 2 + COUNT_FRAMES, easeOut);
	const row: React.CSSProperties = {position: 'absolute', left: 0, right: 0, textAlign: 'center'};
	return (
		<div
			style={{
				position: 'absolute',
				left: pose.cx - pose.w / 2,
				top: pose.cy - pose.h / 2,
				width: pose.w,
				height: pose.h,
				boxSizing: 'border-box',
				borderRadius: 24,
				background: CARD_BG,
				border: `2px solid ${focus > 0.5 ? BORDER_LIT : color.line}`,
				boxShadow: `0 ${8 + 12 * focus}px ${24 + 24 * focus}px rgba(0,0,0,${0.3 + 0.15 * focus})`,
				opacity: Math.min(1, enter * 1.4) * clamp01(pose.dim),
				transform: `translateY(${(1 - enter) * 40}px) scale(${pose.s})`,
				overflow: 'hidden',
			}}
		>
			<div style={{...row, top: Y.icon, display: 'flex', justifyContent: 'center'}}>
				<Icon name={role.icon} draw={draw} />
			</div>
			<div style={{...row, top: Y.role, fontSize: 46, fontWeight: 800, color: color.text, letterSpacing: -0.5}}>{role.role}</div>
			<div style={{...row, top: Y.line, display: 'flex', justifyContent: 'center'}}>
				<div
					style={{
						width: (120 + 160 * focus) * line,
						height: 1,
						background: color.line,
					}}
				/>
			</div>
			<div style={{...row, top: Y.question, fontSize: 36, fontWeight: 600, color: color.muted, opacity: ask, transform: `translateY(${(1 - ask) * 14}px)`}}>
				{role.question}
			</div>
			{role.facts.map((f, j) => (
				<Fact key={f.text} fact={f} at={facts[j]} top={Y.fact + j * Y.factStep} vis={vis} />
			))}
			<div
				style={{
					...row,
					top: Y.answer,
					fontSize: 40,
					fontWeight: 800,
					color: color.text,
					opacity: Math.min(1, ans * 1.3) * (1 - focus),
					transform: `translateY(${(1 - ans) * 14}px)`,
				}}
			>
				<Counted fact={role.answer} p={ansP} />
			</div>
		</div>
	);
};

/** "152,734 = 152,734" under the cards: both sides count up, the equals sign fades in, then the caption. */
const EvidenceLine: React.FC<{at: number}> = ({at}) => {
	const frame = useCurrentFrame();
	const {fps} = useVideoConfig();
	const inS = spring({frame: frame - at, fps, config: LAND});
	const count = ramp(frame, at + 2, at + EQ_DELAY, easeOut);
	const eq = ramp(frame, at + EQ_DELAY, at + EQ_DELAY + 10, easeOut);
	const cap = ramp(frame, at + EQ_DELAY + 4, at + EQ_DELAY + 22, easeOut);
	const ev = split.evidence;
	const big: React.CSSProperties = {fontSize: 72, fontWeight: 800, color: color.text, fontVariantNumeric: 'tabular-nums', letterSpacing: -1};
	return (
		<div
			style={{
				position: 'absolute',
				left: 0,
				right: 0,
				top: ROW_TOP + LIT_H + 44,
				textAlign: 'center',
				opacity: Math.min(1, inS * 1.3),
				transform: `translateY(${(1 - inS) * 16}px)`,
			}}
		>
			<div style={{display: 'flex', justifyContent: 'center', alignItems: 'center', gap: 30}}>
				<span style={{...big, minWidth: 280, textAlign: 'right', color: color.accent}}>{countUp(ev.left, count)}</span>
				<span style={{...big, color: color.muted, fontWeight: 600, opacity: eq}}>=</span>
				<span style={{...big, minWidth: 280, textAlign: 'left', color: color.accent}}>{countUp(ev.right, count)}</span>
			</div>
			<div style={{fontSize: 28, color: color.muted, marginTop: 6, opacity: cap, transform: `translateY(${(1 - cap) * 10}px)`}}>{ev.caption}</div>
		</div>
	);
};

/** The header, the three cards and the evidence line. */
export const SplitBoard: React.FC<{times: SplitTimes}> = ({times: T}) => {
	const frame = useCurrentFrame();
	const {fps} = useVideoConfig();
	const head = spring({frame: frame - T.liftoff, fps, config: {damping: 200}, durationInFrames: 24});
	const answer = ramp(frame, T.allLit, T.allLit + 18);
	const poses = [0, 1, 2].map((i) => poseAt(i, frame, fps, T));
	const facts = factTimes(T);
	return (
		<AbsoluteFill style={{fontFamily: font.sans, background: INK}}>
			<div style={{position: 'absolute', left: 0, right: 0, top: 58, textAlign: 'center', opacity: head, transform: `translateY(${(1 - head) * -20}px)`}}>
				<div style={{position: 'relative', height: 64, fontSize: 52, fontWeight: 600, color: color.text, letterSpacing: -0.5}}>
					<div style={{position: 'absolute', left: 0, right: 0, opacity: 1 - answer}}>{split.header.ask}</div>
					<div style={{position: 'absolute', left: 0, right: 0, opacity: answer}}>{split.header.answer}</div>
				</div>
			</div>
			{/* The centre-stage card is drawn last so it passes over the others while they swap places. */}
			{[0, 1, 2]
				.sort((a, b) => poses[a].focus - poses[b].focus)
				.map((i) => (
					<Card key={i} i={i} role={split.roles[i]} pose={poses[i]} T={T} facts={facts[i]} />
				))}
			<EvidenceLine at={T.evidence} />
		</AbsoluteFill>
	);
};

// ---------------------------------------------------------------- scene

const Sfx: React.FC<{name: string; from: number; volume: number}> = ({name, from, volume}) =>
	from >= 0 ? (
		<Sequence from={from} layout="none">
			<Audio src={staticFile(`assets/sfx/${name}.wav`)} volume={volume} />
		</Sequence>
	) : null;

/** Beat frames for a scene of `frames` frames (the s2 take), from the cue timing of B's take. B opens full screen for his
 * first sentence (cue `at.liftoff`); the cards come in as it ends, while the webcam shrinks to the corner, and the
 * engineer takes centre stage just after the next cue starts so the row is seen for a moment first. */
export const splitTimes = (frames: number): SplitTimes => {
const cues = cueFrames(split.cues, frames);
const c = cues.map(([a]) => a);
const at = split.at;
const intro = cues[at.liftoff];
return {
liftoff: Math.max(intro[0] + 30, intro[1] - 24),
spot: [c[at.engineer] + 14, c[at.teamLead], c[at.manager]],
		allLit: c[at.allLit],
		evidence: c[at.allLit] + 30,
	};
};

export const SplitScene: React.FC<{assets: ResolvedAssets; frames: number}> = ({assets, frames}) => {
	const frame = useCurrentFrame();
	const {fps} = useVideoConfig();
	const T = splitTimes(frames);
	// Full-screen webcam for B's first sentence, then a smooth shrink into the corner as the cards come in.
	const corner = spring({frame: frame - (T.liftoff - 6), fps, config: {damping: 200}, durationInFrames: 24});
	const tagFrames = Math.max(30, Math.min(NAME_TAG_FRAMES, T.liftoff - 6 - 12));
	const drift = interpolate(frame, [T.liftoff, frames], [1, 1.02], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
	return (
		<AbsoluteFill style={{backgroundColor: INK}}>
			{frame >= T.liftoff ? (
				<AbsoluteFill style={{transform: `scale(${drift})`}}>
					<SplitBoard times={T} />
				</AbsoluteFill>
			) : null}
			<FilmFacecam assetKey="s2" assets={assets} corner={corner} />
			<Sequence from={12} durationInFrames={tagFrames} name="name tag s2">
			<NameTag assetKey="s2" frames={tagFrames} />
			</Sequence>
			<Sfx name="whoosh" from={T.liftoff - 4} volume={0.3} />
			{factTimes(T)
				.flat()
				.map((f, j) => (
					<Sfx key={`c${j}`} name="click" from={f} volume={0.15} />
				))}
			<Sfx name="chime" from={T.allLit} volume={0.3} />
			<Sfx name="click" from={T.evidence + EQ_DELAY} volume={0.15} />
			<Vignette />
			<Grain />
			<BlackFades frames={frames} fadeIn={12} fadeOut={18} />
		</AbsoluteFill>
	);
};
