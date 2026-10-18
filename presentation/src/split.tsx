// Scene 2: the three roles as one split, in one take by presenter B. Three minimal cards (icon, role, a short question)
// spring in side by side; each role then takes centre stage in turn and lands up to three short facts while the other
// two wait, small and dimmed, at the sides; at the end all three come back lit with a one-line answer, and
// 152,734 = 152,734 lands under them. Texts: `split` in content.ts.
// `SplitBoard` with DONE_TIMES draws the final state for the slides PDF.
import React from 'react';
import {AbsoluteFill, Audio, interpolate, random, Sequence, spring, staticFile, useCurrentFrame, useVideoConfig} from 'remotion';
import {type ResolvedAssets} from './assets';
import {split, type SplitFact, type SplitRole} from './content';
import {BlackFades, ease, easeOut, FilmFacecam, Grain, NameTag, ramp, Vignette} from './film';
import {DaysRing} from './shots2';
import {color, font} from './theme';
import {cueFrames} from './timeline';

const INK = '#030405';
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
/** The equals sign pops this many frames after the evidence line arrives (once both sides have counted up). */
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

/** Card i at `frame`: the row, then each centre-stage move, then the lit row, each eased in by a soft spring with a little overshoot. */
const poseAt = (i: number, frame: number, fps: number, T: SplitTimes): Pose => {
	const moves: [number, Pose][] = [
		[T.spot[0], focusPose(i, 0)],
		[T.spot[1], focusPose(i, 1)],
		[T.spot[2], focusPose(i, 2)],
		[T.allLit, rowPose(i, LIT_H)],
	];
	return moves.reduce(
		(pose, [at, target]) => mix(pose, target, spring({frame: frame - at, fps, config: {damping: 15, stiffness: 110, mass: 0.9}})),
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

/** A few small gold sparks flying out of a point; `t` = frames since the beat. */
const Sparks: React.FC<{t: number; seed: string; n?: number; reach?: number}> = ({t, seed, n = 10, reach = 56}) => {
	if (t < 0 || t > 28) return null;
	return (
		<div style={{position: 'absolute', left: '50%', top: '50%', width: 0, height: 0, pointerEvents: 'none'}}>
			{Array.from({length: n}, (_, i) => {
				const life = 16 + random(`${seed}l${i}`) * 12;
				if (t > life) return null;
				const a = (i / n) * Math.PI * 2 + (random(`${seed}a${i}`) - 0.5) * 0.7;
				const d = reach * (0.6 + 0.4 * random(`${seed}d${i}`)) * easeOut(t / life);
				const k = 1 - t / life;
				const sz = (3 + 4 * random(`${seed}s${i}`)) * (0.4 + 0.6 * k);
				const c = i % 2 ? '#fff6d8' : '#ffd76a';
				return (
					<div
						key={i}
						style={{
							position: 'absolute',
							left: Math.cos(a) * d - sz / 2,
							top: Math.sin(a) * d - sz / 2,
							width: sz,
							height: sz,
							borderRadius: '50%',
							background: c,
							opacity: Math.min(1, k * 1.6),
							boxShadow: `0 0 ${sz * 2}px ${c}`,
						}}
					/>
				);
			})}
		</div>
	);
};

/** A fact's text with its `count` part counting up in the accent colour; sparks fly off it as the count settles. */
const Counted: React.FC<{fact: SplitFact; p: number; t: number; seed: string}> = ({fact, p, t, seed}) => {
	const i = fact.count ? fact.text.indexOf(fact.count) : -1;
	if (!fact.count || i < 0) return <>{fact.text}</>;
	return (
		<>
			{fact.text.slice(0, i)}
			<span style={{position: 'relative', display: 'inline-block', color: color.accent, fontWeight: 800, fontVariantNumeric: 'tabular-nums'}}>
				{countUp(fact.count, p)}
				<Sparks t={t} seed={seed} />
			</span>
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
const Icon: React.FC<{name: SplitRole['icon']; draw: number; glow: number}> = ({name, draw, glow}) => {
	const paths = ICONS[name];
	return (
		<svg width={76} height={76} viewBox="0 0 48 48" style={{filter: glow > 0.01 ? `drop-shadow(0 0 ${10 * glow}px rgba(245,165,36,0.8))` : undefined}}>
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
						strokeWidth={3.6}
						strokeLinecap="round"
						strokeLinejoin="round"
						opacity={p > 0 ? 1 : 0}
					/>
				);
			})}
		</svg>
	);
};

/** One fact on the centre-stage card: lands with overshoot and a short blur, its number counts up (and the days ring fills). */
const Fact: React.FC<{fact: SplitFact; at: number; top: number; vis: number; seed: string}> = ({fact, at, top, vis, seed}) => {
	const frame = useCurrentFrame();
	const {fps} = useVideoConfig();
	const s = spring({frame: frame - at, fps, config: {damping: 11, stiffness: 170, mass: 0.6}});
	const p = ramp(frame, at + 2, at + 2 + COUNT_FRAMES, easeOut);
	const tone: React.CSSProperties =
		fact.tone === 'accent'
			? {color: color.accent, fontWeight: 800}
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
				opacity: Math.min(1, s * 1.5) * vis,
				transform: `translateY(${(1 - s) * 24}px) scale(${0.94 + 0.06 * s})`,
				filter: s < 0.98 ? `blur(${6 * Math.max(0, 1 - s)}px)` : undefined,
				...tone,
			}}
		>
			{fact.ring ? <DaysRing lit={Number(fact.count ?? 0) * p} r={20} stroke={7} /> : null}
			<span>
				<Counted fact={fact} p={p} t={frame - at - 2 - COUNT_FRAMES} seed={seed} />
			</span>
		</div>
	);
};

const Card: React.FC<{i: number; role: SplitRole; pose: Pose; T: SplitTimes; facts: number[]}> = ({i, role, pose, T, facts}) => {
	const frame = useCurrentFrame();
	const {fps} = useVideoConfig();
	const at = T.liftoff + i * ENTER_STAGGER;
	const enter = spring({frame: frame - at, fps, config: {damping: 11, stiffness: 130, mass: 0.7}});
	const draw = ramp(frame, at + 4, at + 30, easeOut);
	const line = ramp(frame, at + 12, at + 34, easeOut);
	const ask = ramp(frame, at + 16, at + 32, easeOut);
	const lit = ramp(frame, T.allLit, T.allLit + 14);
	// A flash as the sweep passes this card on the all-lit beat.
	const pulse = Math.sin(Math.PI * ramp(frame, T.allLit + 4 + i * 6, T.allLit + 26 + i * 6));
	const focus = clamp01(pose.focus);
	const glow = Math.min(1, Math.max(focus, 0.6 * lit, pulse));
	const vis = clamp01((focus - 0.4) / 0.4);
	const ans = spring({frame: frame - answerAt(T, i), fps, config: {damping: 11, stiffness: 170, mass: 0.6}});
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
				background: 'linear-gradient(180deg, #121821 0%, #0c1016 100%)',
				border: `2px solid ${glow > 0.01 ? `rgba(245,165,36,${0.2 + 0.6 * glow})` : color.line}`,
				boxShadow: `0 30px 80px rgba(0,0,0,0.55)${glow > 0.01 ? `, 0 0 ${90 * glow}px rgba(245,165,36,${0.22 * glow})` : ''}`,
				opacity: Math.min(1, enter * 1.6) * clamp01(pose.dim),
				transform: `translateY(${(1 - enter) * 80}px) scale(${pose.s * (0.85 + 0.15 * enter)})`,
				overflow: 'hidden',
			}}
		>
			<div style={{position: 'absolute', left: 0, right: 0, top: 0, height: 4, background: color.accent, opacity: glow, transform: `scaleX(${glow})`}} />
			<div style={{...row, top: Y.icon, display: 'flex', justifyContent: 'center'}}>
				<Icon name={role.icon} draw={draw} glow={glow} />
			</div>
			<div style={{...row, top: Y.role, fontSize: 46, fontWeight: 800, color: color.text, letterSpacing: -0.5}}>{role.role}</div>
			<div style={{...row, top: Y.line, display: 'flex', justifyContent: 'center'}}>
				<div
					style={{
						width: (140 + 220 * focus) * line,
						height: 3,
						borderRadius: 2,
						background: color.accent,
						boxShadow: `0 0 ${12 + 14 * glow}px rgba(245,165,36,${0.6 + 0.4 * glow})`,
					}}
				/>
			</div>
			<div style={{...row, top: Y.question, fontSize: 36, fontWeight: 600, color: color.muted, opacity: ask, transform: `translateY(${(1 - ask) * 14}px)`}}>
				{role.question}
			</div>
			{role.facts.map((f, j) => (
				<Fact key={f.text} fact={f} at={facts[j]} top={Y.fact + j * Y.factStep} vis={vis} seed={`f${i}${j}`} />
			))}
			<div
				style={{
					...row,
					top: Y.answer,
					fontSize: 40,
					fontWeight: 800,
					color: color.text,
					opacity: Math.min(1, ans * 1.5) * (1 - focus),
					transform: `translateY(${(1 - ans) * 20}px) scale(${0.92 + 0.08 * ans})`,
				}}
			>
				<Counted fact={role.answer} p={ansP} t={frame - answerAt(T, i) - 2 - COUNT_FRAMES} seed={`a${i}`} />
			</div>
		</div>
	);
};

/** "152,734 = 152,734" under the cards: both sides count up, the equals sign pops with sparks, then the caption. */
const EvidenceLine: React.FC<{at: number}> = ({at}) => {
	const frame = useCurrentFrame();
	const {fps} = useVideoConfig();
	const inS = spring({frame: frame - at, fps, config: {damping: 13, stiffness: 160, mass: 0.6}});
	const count = ramp(frame, at + 2, at + EQ_DELAY, easeOut);
	const eq = spring({frame: frame - at - EQ_DELAY, fps, config: {damping: 8, stiffness: 240, mass: 0.5}});
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
				opacity: Math.min(1, inS * 1.5),
				transform: `translateY(${(1 - inS) * 26}px)`,
			}}
		>
			<div style={{display: 'flex', justifyContent: 'center', alignItems: 'center', gap: 30}}>
				<span style={{...big, minWidth: 280, textAlign: 'right'}}>{countUp(ev.left, count)}</span>
				<span style={{...big, position: 'relative', display: 'inline-block', color: color.accent, transform: `scale(${eq})`}}>
					=
					<Sparks t={frame - at - EQ_DELAY} seed="eq" n={14} reach={90} />
				</span>
				<span style={{...big, minWidth: 280, textAlign: 'left'}}>{countUp(ev.right, count)}</span>
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
	const sweep = ramp(frame, T.allLit, T.allLit + 34, ease);
	const poses = [0, 1, 2].map((i) => poseAt(i, frame, fps, T));
	const stage = clamp01(Math.max(...poses.map((p) => p.focus)));
	const facts = factTimes(T);
	return (
		<AbsoluteFill style={{fontFamily: font.sans, background: 'radial-gradient(ellipse at 50% 40%, #10161e 0%, #030405 75%)'}}>
			<AbsoluteFill style={{opacity: stage, background: 'radial-gradient(ellipse 42% 46% at 50% 44%, rgba(245,165,36,0.07) 0%, rgba(245,165,36,0) 100%)'}} />
			<div style={{position: 'absolute', left: 0, right: 0, top: 58, textAlign: 'center', opacity: head, transform: `translateY(${(1 - head) * -20}px)`}}>
				<div style={{position: 'relative', height: 64, fontSize: 56, fontWeight: 800, color: color.text, letterSpacing: -1}}>
					<div style={{position: 'absolute', left: 0, right: 0, opacity: 1 - answer}}>{split.header.ask}</div>
					<div style={{position: 'absolute', left: 0, right: 0, opacity: answer, transform: `scale(${1 + 0.05 * Math.sin(Math.PI * answer)})`}}>
						{split.header.answer.split('Three answers.')[0]}
						<span style={{color: color.accent}}>Three answers.</span>
					</div>
				</div>
			</div>
			{/* The centre-stage card is drawn last so it passes over the others while they swap places. */}
			{[0, 1, 2]
				.sort((a, b) => poses[a].focus - poses[b].focus)
				.map((i) => (
					<Card key={i} i={i} role={split.roles[i]} pose={poses[i]} T={T} facts={facts[i]} />
				))}
			{sweep > 0 && sweep < 1 ? (
				<div
					style={{
						position: 'absolute',
						top: ROW_TOP - 40,
						height: LIT_H + 80,
						left: -400 + 2400 * sweep,
						width: 260,
						background: 'linear-gradient(90deg, rgba(255,215,106,0) 0%, rgba(255,215,106,0.12) 50%, rgba(255,215,106,0) 100%)',
						transform: 'skewX(-18deg)',
						pointerEvents: 'none',
					}}
				/>
			) : null}
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

/** Beat frames for a scene of `frames` frames (the s2 take), from the cue timing of B's take. */
export const splitTimes = (frames: number): SplitTimes => {
	const c = cueFrames(split.cues, frames).map(([a]) => a);
	const at = split.at;
	return {
		liftoff: c[at.liftoff],
		spot: [c[at.engineer], c[at.teamLead], c[at.manager]],
		allLit: c[at.allLit],
		evidence: c[at.allLit] + 30,
	};
};

export const SplitScene: React.FC<{assets: ResolvedAssets; frames: number}> = ({assets, frames}) => {
	const frame = useCurrentFrame();
	const T = splitTimes(frames);
	const drift = interpolate(frame, [T.liftoff, frames], [1, 1.02], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
	return (
		<AbsoluteFill style={{backgroundColor: INK}}>
			{frame >= T.liftoff ? (
				<AbsoluteFill style={{transform: `scale(${drift})`}}>
					<SplitBoard times={T} />
				</AbsoluteFill>
			) : null}
			<FilmFacecam assetKey="s2" assets={assets} corner={1} />
			<Sequence from={12} durationInFrames={NAME_TAG_FRAMES} name="name tag s2">
				<NameTag assetKey="s2" frames={NAME_TAG_FRAMES} small />
			</Sequence>
			<Sfx name="whoosh" from={T.liftoff - 4} volume={0.3} />
			{T.spot.map((f, k) => (
				<Sfx key={`w${k}`} name="whoosh" from={f - 4} volume={0.12} />
			))}
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
