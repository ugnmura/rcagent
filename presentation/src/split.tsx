// Scene 2: the three roles as one split, in one take by presenter B. A short sped-up proof clip of the real
// session, then the answers lift into three columns (question, tool calls, answer, next step) that build at the
// same time, a spotlight following B's sentence for each role, and all three lit at the end with the evidence
// beat (the engineer's [Q46] chip and 152,734 = 152,734). Texts: `split` in content.ts.
// `SplitBoard` with DONE_TIMES draws the final state for the slides PDF.
import React from 'react';
import {AbsoluteFill, Audio, Freeze, OffthreadVideo, Sequence, spring, staticFile, useCurrentFrame, useVideoConfig, interpolate} from 'remotion';
import {ASSETS, type ResolvedAssets} from './assets';
import {engineer, evidence, manager, split, teamLead} from './content';
import {BlackFades, ease, easeOut, FilmFacecam, Grain, NameTag, ramp, SoftPlaceholder, Vignette} from './film';
import {DaysRing} from './shots2';
import {color, font} from './theme';
import {cueFrames, FPS, PROOF_RATE} from './timeline';

const INK = '#030405';
const COL_W = 560;
const COL_GAP = 40;
const COL_LEFT = (1920 - 3 * COL_W - 2 * COL_GAP) / 2;
const COL_TOP = 196;
const COL_H = 632;
const PAD = 28;
const colX = (i: number) => COL_LEFT + i * (COL_W + COL_GAP);
const LIFT_FRAMES = 36;
const NAME_TAG_FRAMES = 90;
/** Column i starts building this many frames after the previous one (the columns build together, slightly staggered). */
const STAGGER = 6;
/** Frames between two tool calls in a column's ticker; each call "runs" for TOOL_RUN frames, then gets its tick. */
const TOOL_STEP = 13;
const TOOL_RUN = 10;
/** Build offsets within a column, from its start. */
const AT_TOOLS = 14;
const AT_ANSWER = AT_TOOLS + 3 * TOOL_STEP + 6;
const AT_NEXT = AT_ANSWER + 16;
/** Brightness of a column outside the spotlight (still readable, slightly dimmer). */
const DIM = 0.55;

const num = (s: string) => Number(s.replace(/[^0-9.]/g, ''));
const fmtInt = (n: number) => Math.round(n).toLocaleString('en-US');

/** Scene-relative frames of each beat. */
export type SplitTimes = {
	liftoff: number;
	/** Build start of each column. */
	build: [number, number, number];
	/** Spotlight start for each column (it ends where the next one starts, the last at `allLit`). */
	spot: [number, number, number];
	allLit: number;
	/** The [Q46] chip pulses and 152,734 = 152,734 lands. */
	evidence: number;
};

/** Everything already built and all three columns lit, no transient effect running: the slides PDF page. */
export const DONE_TIMES: SplitTimes = {
	liftoff: -1000,
	build: [-1000, -1000, -1000],
	spot: [-1000, -1000, -1000],
	allLit: -1000,
	evidence: -1000,
};

// ---------------------------------------------------------------- pieces

/** A row element that lands with a small overshoot when its beat arrives. */
const Land: React.FC<{at: number; style?: React.CSSProperties; children: React.ReactNode}> = ({at, style, children}) => {
	const frame = useCurrentFrame();
	const {fps} = useVideoConfig();
	const s = spring({frame: frame - at, fps, config: {damping: 12, stiffness: 180, mass: 0.6}});
	return (
		<div style={{position: 'absolute', left: PAD, right: PAD, opacity: Math.min(1, s * 1.5), transform: `translateY(${(1 - s) * 22}px)`, ...style}}>
			{children}
		</div>
	);
};

const Label: React.FC<{children: React.ReactNode}> = ({children}) => (
	<div style={{fontSize: 18, letterSpacing: '0.2em', textTransform: 'uppercase', color: color.muted, fontWeight: 600}}>{children}</div>
);

/** The query handle on the engineer's answer; `pulse` (0–1) swells it for the evidence beat. */
const QueryChip: React.FC<{pulse: number}> = ({pulse}) => (
	<span
		style={{
			display: 'inline-block',
			fontFamily: font.mono,
			fontSize: 20,
			fontWeight: 700,
			color: pulse > 0.01 ? INK : color.accent,
			background: `rgba(245,165,36,${pulse})`,
			border: `2px solid ${color.accent}`,
			borderRadius: 999,
			padding: '2px 12px',
			whiteSpace: 'nowrap',
			transform: `scale(${1 + 0.28 * pulse})`,
			boxShadow: pulse > 0.01 ? `0 0 ${40 * pulse}px rgba(245,165,36,${0.8 * pulse})` : undefined,
		}}
	>
		[{evidence.handle}]
	</span>
);

/** One tool call in a column's ticker: a pulsing dot while it runs, then a tick. */
const ToolRow: React.FC<{name: string; at: number; top: number}> = ({name, at, top}) => {
	const frame = useCurrentFrame();
	const done = frame >= at + TOOL_RUN;
	const blink = 0.4 + 0.6 * Math.abs(Math.sin((frame - at) / 2.2));
	return (
		<Land at={at} style={{top, display: 'flex', alignItems: 'center', gap: 14, fontFamily: font.mono, fontSize: 24}}>
			<span style={{width: 22, textAlign: 'center', fontWeight: 800, color: done ? color.accent : color.muted, opacity: done ? 1 : blink}}>
				{done ? '✓' : '●'}
			</span>
			<span style={{color: done ? color.text : color.muted}}>{name}</span>
		</Land>
	);
};

const Column: React.FC<{i: number; role: string; question: string; tools: readonly string[]; start: number; level: number; glow: number; children: React.ReactNode}> = ({
	i,
	role,
	question,
	tools,
	start,
	level,
	glow,
	children,
}) => (
	<div
		style={{
			position: 'absolute',
			left: colX(i),
			top: COL_TOP,
			width: COL_W,
			height: COL_H,
			boxSizing: 'border-box',
			borderRadius: 20,
			background: 'linear-gradient(180deg, #121821 0%, #0c1016 100%)',
			border: `2px solid ${glow > 0.01 ? `rgba(245,165,36,${0.25 + 0.6 * glow})` : color.line}`,
			boxShadow: `0 30px 80px rgba(0,0,0,0.55)${glow > 0.01 ? `, 0 0 ${80 * glow}px rgba(245,165,36,${0.24 * glow})` : ''}`,
			opacity: level,
			filter: `saturate(${0.4 + 0.6 * level})`,
			fontFamily: font.sans,
			overflow: 'hidden',
		}}
	>
		<div style={{position: 'absolute', left: PAD, top: 22, fontSize: 40, fontWeight: 800, color: color.text}}>{role}</div>
		<div style={{position: 'absolute', left: 0, right: 0, top: 0, height: 4, background: color.accent, opacity: glow, transform: `scaleX(${glow})`}} />
		<Land at={start} style={{top: 82, fontSize: 28, fontWeight: 600, fontStyle: 'italic', color: color.text, lineHeight: 1.2}}>
			{question}
		</Land>
		<Land at={start + AT_TOOLS - 4} style={{top: 172}}>
			<Label>{split.labels.tools}</Label>
		</Land>
		{tools.map((name, k) => (
			<ToolRow key={name} name={name} at={start + AT_TOOLS + k * TOOL_STEP} top={202 + k * 36} />
		))}
		<Land at={start + AT_ANSWER - 4} style={{top: 328}}>
			<Label>{split.labels.answer}</Label>
		</Land>
		{children}
		<Land at={start + AT_NEXT - 4} style={{top: 488}}>
			<Label>{split.labels.next}</Label>
		</Land>
	</div>
);

/** The headline of an answer: lands with overshoot and swells briefly when its column takes the spotlight. */
const Headline: React.FC<{at: number; focus: number; children: React.ReactNode; style?: React.CSSProperties}> = ({at, focus, children, style}) => {
	const frame = useCurrentFrame();
	const swell = frame >= focus ? Math.sin(Math.PI * Math.min(1, (frame - focus) / 18)) : 0;
	return (
		<Land at={at} style={{top: 354, fontSize: 30, fontWeight: 800, color: color.text, ...style}}>
			<div style={{transform: `scale(${1 + 0.05 * swell})`, transformOrigin: 'left center'}}>{children}</div>
		</Land>
	);
};

const Next: React.FC<{at: number; children: React.ReactNode}> = ({at, children}) => (
	<Land at={at} style={{top: 514, fontSize: 28, fontWeight: 800, color: color.accent, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis'}}>
		→ {children}
	</Land>
);

const EngineerAnswer: React.FC<{start: number; focus: number; evidenceAt: number}> = ({start, focus, evidenceAt}) => {
	const frame = useCurrentFrame();
	const e = split.engineer;
	// Two quick pulses of the chip as the evidence beat starts.
	const p = frame >= evidenceAt ? Math.abs(Math.sin(Math.PI * 2 * Math.min(1, (frame - evidenceAt) / 36))) : 0;
	const a = start + AT_ANSWER;
	return (
		<>
			<Headline at={a} focus={focus} style={{fontSize: 28}}>
				<div style={{display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12}}>
					<span>{e.answer}</span>
					<QueryChip pulse={p} />
				</div>
			</Headline>
			<Land at={a + 5} style={{top: 396, fontFamily: font.mono, fontSize: 24, color: color.muted}}>
				{e.detail}
			</Land>
			<Land at={a + 9} style={{top: 432, fontSize: 24, color: color.accent}}>
				{e.before}
			</Land>
			<Next at={start + AT_NEXT}>{e.next}</Next>
		</>
	);
};

const TeamLeadAnswer: React.FC<{start: number; focus: number}> = ({start, focus}) => {
	const frame = useCurrentFrame();
	const {days, of, trendLabel} = teamLead.persistent;
	const a = start + AT_ANSWER;
	const lit = interpolate(frame, [a + 4, a + 40], [0, days], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: ease});
	return (
		<>
			<Headline at={a} focus={focus}>
				{split.teamLead.answer}
			</Headline>
			<Land at={a + 5} style={{top: 398, display: 'flex', alignItems: 'center', gap: 16}}>
				<DaysRing lit={lit} r={24} stroke={8} />
				<div style={{fontSize: 24, color: color.text, fontVariantNumeric: 'tabular-nums'}}>
					<span style={{fontWeight: 800}}>{Math.round(lit)}</span> of {of} days
					<span style={{color: color.muted}}> · {trendLabel}</span>
				</div>
			</Land>
			<Next at={start + AT_NEXT}>{split.teamLead.next}</Next>
		</>
	);
};

const ManagerAnswer: React.FC<{start: number; focus: number}> = ({start, focus}) => {
	const frame = useCurrentFrame();
	const {fps} = useVideoConfig();
	const a = start + AT_ANSWER;
	const m = split.manager;
	return (
		<>
			<Headline at={a} focus={focus}>
				{m.answer}
			</Headline>
			<Land at={a + 4} style={{top: 398, display: 'flex', alignItems: 'center', gap: 10}}>
				{manager.cards.map((c, i) => {
					const s = spring({frame: frame - a - 6 - i * 4, fps, config: {damping: 9, stiffness: 220, mass: 0.5}});
					return (
						<div
							key={c.label}
							style={{
								width: 40,
								height: 40,
								borderRadius: 10,
								display: 'flex',
								alignItems: 'center',
								justifyContent: 'center',
								fontSize: 24,
								fontWeight: 800,
								color: i === 0 ? INK : color.text,
								background: i === 0 ? color.accent : '#1d242e',
								border: `2px solid ${i === 0 ? color.accent : color.line}`,
								opacity: Math.min(1, s * 1.5),
								transform: `scale(${s})`,
							}}
						>
							{i + 1}
						</div>
					);
				})}
				<div style={{fontSize: 24, color: color.muted, marginLeft: 6}}>{m.detail}</div>
			</Land>
			<Next at={start + AT_NEXT}>{m.next}</Next>
			<Land at={start + AT_NEXT + 12} style={{top: 572, fontSize: 24, color: color.muted, fontStyle: 'italic'}}>
				{m.limit}
			</Land>
		</>
	);
};

/** "152,734 = 152,734" under the columns: both sides count up, then the equals sign pops. */
const EvidenceLine: React.FC<{at: number}> = ({at}) => {
	const frame = useCurrentFrame();
	const {fps} = useVideoConfig();
	const inS = spring({frame: frame - at, fps, config: {damping: 13, stiffness: 160, mass: 0.6}});
	const count = ramp(frame, at + 4, at + 34, easeOut);
	const eq = spring({frame: frame - at - 34, fps, config: {damping: 8, stiffness: 240, mass: 0.5}});
	const ev = split.evidence;
	const big: React.CSSProperties = {fontSize: 44, fontWeight: 800, color: color.text, fontVariantNumeric: 'tabular-nums', minWidth: 170, textAlign: 'center'};
	return (
		<div
			style={{
				position: 'absolute',
				left: 0,
				right: 0,
				top: COL_TOP + COL_H + 26,
				display: 'flex',
				justifyContent: 'center',
				alignItems: 'center',
				gap: 22,
				fontFamily: font.sans,
				opacity: Math.min(1, inS * 1.5),
				transform: `translateY(${(1 - inS) * 26}px)`,
			}}
		>
			<span style={{fontFamily: font.mono, fontSize: 24, fontWeight: 700, color: color.accent}}>[{evidence.handle}]</span>
			<span style={big}>{fmtInt(num(ev.left) * count)}</span>
			<span style={{...big, color: color.accent, minWidth: 0, display: 'inline-block', transform: `scale(${eq})`}}>=</span>
			<span style={big}>{fmtInt(num(ev.right) * count)}</span>
			<span style={{fontSize: 24, color: color.muted, marginLeft: 8}}>{ev.caption}</span>
		</div>
	);
};

/** The header, the three columns and the evidence line. Columns fly in from the terminal at the lift-off. */
export const SplitBoard: React.FC<{times: SplitTimes}> = ({times: T}) => {
	const frame = useCurrentFrame();
	const {fps} = useVideoConfig();
	const answer = ramp(frame, T.allLit, T.allLit + 18);
	const head = spring({frame: frame - T.liftoff, fps, config: {damping: 200}, durationInFrames: 24});
	const all = ramp(frame, T.allLit, T.allLit + 14);
	const sweep = ramp(frame, T.allLit, T.allLit + 34, ease);
	const ends = [T.spot[1], T.spot[2], T.allLit];
	const glows = T.spot.map((s, i) => {
		const own = ramp(frame, s, s + 10) * (1 - ramp(frame, ends[i], ends[i] + 10));
		return Math.max(own, 0.6 * all, Math.sin(Math.PI * sweep) * 0.9);
	});
	const levels = glows.map((g) => DIM + (1 - DIM) * Math.min(1, Math.max(g, all)));
	const fly = (i: number) => {
		const s = spring({frame: frame - T.liftoff - i * STAGGER, fps, config: {damping: 14, stiffness: 120, mass: 0.8}});
		const dx = 960 - (colX(i) + COL_W / 2);
		const dy = 540 - (COL_TOP + COL_H / 2);
		return {transform: `translate(${dx * (1 - s)}px, ${dy * (1 - s)}px) scale(${0.55 + 0.45 * s})`, opacity: Math.min(1, s * 1.6)};
	};
	const roles = [split.engineer, split.teamLead, split.manager];
	const answers = [
		<EngineerAnswer key="e" start={T.build[0]} focus={T.spot[0]} evidenceAt={T.evidence} />,
		<TeamLeadAnswer key="t" start={T.build[1]} focus={T.spot[1]} />,
		<ManagerAnswer key="m" start={T.build[2]} focus={T.spot[2]} />,
	];
	return (
		<AbsoluteFill style={{fontFamily: font.sans, background: 'radial-gradient(ellipse at 50% 40%, #10161e 0%, #030405 75%)'}}>
			<div style={{position: 'absolute', left: 0, right: 0, top: 54, textAlign: 'center', opacity: head, transform: `translateY(${(1 - head) * -20}px)`}}>
				<div style={{position: 'relative', height: 64, fontSize: 56, fontWeight: 800, color: color.text, letterSpacing: -1}}>
					<div style={{position: 'absolute', left: 0, right: 0, opacity: 1 - answer}}>{split.header.ask}</div>
					<div style={{position: 'absolute', left: 0, right: 0, opacity: answer, transform: `scale(${1 + 0.05 * Math.sin(Math.PI * answer)})`}}>
						{split.header.answer.split('Three answers.')[0]}
						<span style={{color: color.accent}}>Three answers.</span>
					</div>
				</div>
				<div style={{fontSize: 24, color: color.muted, marginTop: 12}}>{split.header.scope}</div>
			</div>
			{roles.map((r, i) => (
				<AbsoluteFill key={r.role} style={{...fly(i), transformOrigin: `${colX(i) + COL_W / 2}px ${COL_TOP + COL_H / 2}px`}}>
					<Column i={i} role={r.role} question={r.question} tools={r.tools} start={T.build[i]} level={levels[i]} glow={glows[i]}>
						{answers[i]}
					</Column>
				</AbsoluteFill>
			))}
			{sweep > 0 && sweep < 1 ? (
				<div
					style={{
						position: 'absolute',
						top: COL_TOP - 40,
						height: COL_H + 80,
						left: -400 + 2400 * sweep,
						width: 260,
						background: 'linear-gradient(90deg, rgba(255,215,106,0) 0%, rgba(255,215,106,0.12) 50%, rgba(255,215,106,0) 100%)',
						transform: 'skewX(-18deg)',
						pointerEvents: 'none',
					}}
				/>
			) : null}
			<EvidenceLine at={T.evidence + 10} />
		</AbsoluteFill>
	);
};

// ---------------------------------------------------------------- proof clip

/**
 * roles.mp4 in a terminal frame, sped up to fit the slot before the lift-off (at least PROOF_RATE); it holds its
 * last frame if it runs out. One Freeze wrapper (switched by `active`) so the video never remounts.
 */
const ProofClip: React.FC<{assets: ResolvedAssets; liftoff: number}> = ({assets, liftoff}) => {
	const frame = useCurrentFrame();
	const {fps} = useVideoConfig();
	const inS = spring({frame, fps, config: {damping: 200}, durationInFrames: 20});
	const out = ramp(frame, liftoff, liftoff + 22, ease);
	const a = assets.rolesRec;
	const recFrames = Math.ceil(a.seconds * FPS);
	const rate = Math.max(PROOF_RATE, recFrames / Math.max(1, liftoff));
	const hold = Math.max(0, Math.floor((recFrames - 2) / rate));
	return (
		<AbsoluteFill style={{opacity: 1 - out, transform: `scale(${(0.92 + 0.08 * inS) * (1 - 0.12 * out)})`, filter: `blur(${8 * out}px)`}}>
			<div
				style={{
					position: 'absolute',
					left: 300,
					top: 150,
					width: 1320,
					height: 760,
					borderRadius: 20,
					overflow: 'hidden',
					background: '#000',
					boxShadow: '0 40px 140px rgba(0,0,0,0.85), 0 0 0 3px #2a313a',
					display: 'flex',
					flexDirection: 'column',
				}}
			>
				<div style={{height: 40, background: '#161b22', display: 'flex', alignItems: 'center', gap: 10, padding: '0 16px'}}>
					{['#ff5f57', '#febc2e', '#28c840'].map((c) => (
						<div key={c} style={{width: 14, height: 14, borderRadius: 7, background: c}} />
					))}
					<div style={{flex: 1, textAlign: 'center', fontFamily: font.mono, fontSize: 16, color: color.muted}}>claude · serenedb-extractor</div>
					<div style={{fontFamily: font.sans, fontSize: 16, fontWeight: 800, color: color.accent}}>{Math.round(rate * 10) / 10}×</div>
				</div>
				<div style={{flex: 1, position: 'relative'}}>
					{a.present ? (
						<Freeze frame={hold} active={frame >= hold}>
							<OffthreadVideo
								src={staticFile(`assets/${ASSETS.rolesRec.file}`)}
								muted
								playbackRate={rate}
								style={{width: '100%', height: '100%', objectFit: 'contain'}}
							/>
						</Freeze>
					) : (
						<SoftPlaceholder
							assetKey="rolesRec"
							note={split.proofNote}
							detail={[engineer.prompt, teamLead.prompt, manager.prompt].join('\n')}
							style={{position: 'absolute', inset: 0, fontSize: 26}}
						/>
					)}
				</div>
			</div>
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
	const liftoff = c[at.liftoff];
	const start = liftoff + 10;
	return {
		liftoff,
		build: [start, start + STAGGER, start + 2 * STAGGER],
		spot: [c[at.engineer], c[at.teamLead], c[at.manager]],
		allLit: c[at.allLit],
		evidence: c[at.allLit] + 12,
	};
};

export const SplitScene: React.FC<{assets: ResolvedAssets; frames: number}> = ({assets, frames}) => {
	const frame = useCurrentFrame();
	const T = splitTimes(frames);
	const drift = interpolate(frame, [T.liftoff, frames], [1, 1.02], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
	const lands = T.build.map((b) => b + AT_ANSWER);
	return (
		<AbsoluteFill style={{backgroundColor: INK}}>
			<Sequence durationInFrames={T.liftoff + LIFT_FRAMES} name="proof clip">
				<ProofClip assets={assets} liftoff={T.liftoff} />
			</Sequence>
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
			{lands.map((f, i) => (
				<Sfx key={i} name="click" from={f} volume={0.15} />
			))}
			<Sfx name="chime" from={T.allLit} volume={0.3} />
			<Sfx name="click" from={T.evidence + 10 + 34} volume={0.15} />
			<Vignette />
			<Grain />
			<BlackFades frames={frames} fadeIn={12} fadeOut={18} />
		</AbsoluteFill>
	);
};
