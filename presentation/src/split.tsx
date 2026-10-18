// Scene 2: the three roles as one split. A short sped-up proof clip of the real session, then the answers lift
// into three columns (Question / Evidence / Next step) that build in turn on each presenter's cues, all three
// lit at the end, and a push into the Q46 citation for the evidence. Texts: `split` and the role blocks in
// content.ts. `SplitBoard` with DONE_TIMES draws the final state for the slides PDF.
import React from 'react';
import {AbsoluteFill, Audio, Freeze, OffthreadVideo, Sequence, spring, staticFile, useCurrentFrame, useVideoConfig, interpolate} from 'remotion';
import {ASSETS, type AssetKey, type ResolvedAssets} from './assets';
import {engineer, evidence, manager, split, teamLead} from './content';
import {BlackFades, ease, easeOut, FilmFacecam, Grain, NameTag, ramp, SoftPlaceholder, Typewriter, Vignette} from './film';
import {Ring} from './shots';
import {CitationShot, DaysRing, SnapShot} from './shots2';
import {color, font} from './theme';
import {cueFrames, FPS, PROOF_RATE, splitStarts, type ScenePart} from './timeline';

const INK = '#030405';
const RED = '#ff6b6b';
const COL_W = 560;
const COL_GAP = 40;
const COL_LEFT = (1920 - 3 * COL_W - 2 * COL_GAP) / 2;
const COL_TOP = 210;
const COL_H = 600;
const PAD = 28;
const colX = (i: number) => COL_LEFT + i * (COL_W + COL_GAP);
/** Centre of the Q46 chip on the engineer's message line, in frame coordinates (the evidence push-in aims here). */
const CHIP = {x: colX(0) + COL_W - PAD - 38, y: COL_TOP + 390 + 16};
const LIFT_FRAMES = 36;
const PUSH_FRAMES = 26;
const PULL_FRAMES = 34;
const NAME_TAG_FRAMES = 90;

const num = (s: string) => Number(s.replace(/[^0-9.]/g, ''));
const fmtInt = (n: number) => Math.round(n).toLocaleString('en-US');

/** Scene-relative frames on which each part of the board appears. */
export type SplitTimes = {
	liftoff: number;
	eng: {start: number; end: number; node: number; share: number; message: number; before: number; hypothesis: number; check: number};
	tl: {start: number; end: number; question: number; bars: number; persistent: number; first: number};
	mg: {start: number; question: number; risks: number; top: number; limit: number};
	allLit: number;
};

/** Everything already built and all three columns lit: the slides PDF page. */
export const DONE_TIMES: SplitTimes = {
	liftoff: -1000,
	eng: {start: -1000, end: -999, node: -1000, share: -1000, message: -1000, before: -1000, hypothesis: -1000, check: -1000},
	tl: {start: -999, end: -998, question: -1000, bars: -1000, persistent: -1000, first: -1000},
	mg: {start: -998, question: -1000, risks: -1000, top: -1000, limit: -1000},
	allLit: -1000,
};

// ---------------------------------------------------------------- pieces

/** A row element that lands with a small overshoot when its cue arrives. */
const Land: React.FC<{at: number; style?: React.CSSProperties; children: React.ReactNode}> = ({at, style, children}) => {
	const frame = useCurrentFrame();
	const {fps} = useVideoConfig();
	const s = spring({frame: frame - at, fps, config: {damping: 13, stiffness: 170, mass: 0.6}});
	return (
		<div style={{position: 'absolute', left: PAD, right: PAD, opacity: Math.min(1, s * 1.5), transform: `translateY(${(1 - s) * 22}px)`, ...style}}>
			{children}
		</div>
	);
};

const Label: React.FC<{children: React.ReactNode}> = ({children}) => (
	<div style={{fontSize: 17, letterSpacing: '0.2em', textTransform: 'uppercase', color: color.muted, fontWeight: 600}}>{children}</div>
);

/** Query mark on an evidence line: the numbered handle where one exists, otherwise an unnumbered mark. */
const QueryChip: React.FC<{handle?: string}> = ({handle}) => (
	<span
		style={{
			fontFamily: font.mono,
			fontSize: 16,
			fontWeight: 600,
			color: color.accent,
			border: `2px solid ${handle ? color.accent : 'rgba(245,165,36,0.45)'}`,
			borderRadius: 999,
			padding: '2px 10px',
			whiteSpace: 'nowrap',
		}}
	>
		{handle ? `[${handle}]` : split.labels.query}
	</span>
);

const Column: React.FC<{i: number; role: string; level: number; glow: number; children: React.ReactNode}> = ({i, role, level, glow, children}) => (
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
			boxShadow: `0 30px 80px rgba(0,0,0,0.55)${glow > 0.01 ? `, 0 0 ${70 * glow}px rgba(245,165,36,${0.22 * glow})` : ''}`,
			opacity: level,
			filter: `saturate(${0.4 + 0.6 * level})`,
			fontFamily: font.sans,
			overflow: 'hidden',
		}}
	>
		<div style={{position: 'absolute', left: PAD, top: 22, fontSize: 40, fontWeight: 800, color: color.text}}>{role}</div>
		<div style={{position: 'absolute', left: 0, right: 0, top: 0, height: 4, background: color.accent, opacity: glow, transform: `scaleX(${glow})`}} />
		{children}
	</div>
);

const EngineerColumn: React.FC<{t: SplitTimes['eng']}> = ({t}) => {
	const frame = useCurrentFrame();
	const fill = ramp(frame, t.share, t.share + 40, ease);
	const pct = num(engineer.share.pct);
	const ghost = ramp(frame, t.message + 6, t.message + 50, easeOut);
	const flash = Math.max(0, 1 - Math.max(0, frame - t.before) / 24) * (frame >= t.before ? 1 : 0);
	return (
		<>
			<Land at={t.start} style={{top: 84}}>
				<Label>{split.labels.question}</Label>
				<div style={{fontSize: 30, fontWeight: 600, color: color.text, marginTop: 8, lineHeight: 1.2}}>{split.engineer.question}</div>
			</Land>
			<Land at={t.node} style={{top: 196}}>
				<Label>{split.labels.evidence}</Label>
			</Land>
			<div style={{position: 'absolute', left: PAD, top: 224, fontFamily: font.mono, fontSize: 26, fontWeight: 600, color: color.text}}>
				<Typewriter text={engineer.node} start={t.node} cps={24} />
			</div>
			<Land at={t.share} style={{top: 262, display: 'flex', alignItems: 'center', gap: 18}}>
				<Ring fraction={(pct / 100) * fill} r={32} stroke={9} label={`${(pct * fill).toFixed(1)}%`} labelSize={17} />
				<div style={{fontSize: 26, fontWeight: 800, color: color.text, fontVariantNumeric: 'tabular-nums'}}>
					{fmtInt(num(engineer.share.part) * fill)}
					<span style={{color: color.muted, fontWeight: 400}}> / {engineer.share.whole} FATAL</span>
				</div>
			</Land>
			<Land at={t.before} style={{top: 356, fontFamily: font.mono, fontSize: 21}}>
				<span style={{color: color.accent, textShadow: `0 0 ${18 * flash}px rgba(245,165,36,${flash})`}}>
					{engineer.beforeLine.time} {engineer.beforeLine.text}
				</span>
			</Land>
			<Land at={t.message} style={{top: 390, display: 'flex', alignItems: 'center', justifyContent: 'space-between', fontFamily: font.mono, fontSize: 21}}>
				<span style={{color: RED, fontWeight: 600}}>{engineer.message}</span>
				<QueryChip handle={evidence.handle} />
			</Land>
			{[1, 2, 3].map((k) => (
				<div
					key={k}
					style={{position: 'absolute', left: PAD, top: 390 + 10 * k * ghost, fontFamily: font.mono, fontSize: 21, color: RED, opacity: (0.22 / k) * ghost}}
				>
					{engineer.message}
				</div>
			))}
			<Land at={t.message + 8} style={{top: 428, fontSize: 21, color: color.muted}}>
				non-stop {engineer.window}
			</Land>
			<Land at={t.hypothesis} style={{top: 470}}>
				<Label>{split.labels.next}</Label>
				<div style={{fontSize: 23, color: color.muted, marginTop: 10, fontStyle: 'italic'}}>{split.engineer.hypothesis}</div>
			</Land>
			<Land at={t.check} style={{top: 536, fontSize: 28, fontWeight: 800, color: color.accent}}>
				→ {split.engineer.check}
			</Land>
		</>
	);
};

const TeamLeadColumn: React.FC<{t: SplitTimes['tl']}> = ({t}) => {
	const frame = useCurrentFrame();
	const bars = teamLead.fatalBars;
	const max = Math.max(...bars.map((b) => num(b.value)));
	const {days, of, message} = teamLead.persistent;
	const lit = interpolate(frame, [t.persistent + 4, t.persistent + 46], [0, days], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: ease});
	return (
		<>
			<Land at={t.question} style={{top: 84}}>
				<Label>{split.labels.question}</Label>
				<div style={{fontSize: 30, fontWeight: 600, color: color.text, marginTop: 8, lineHeight: 1.2}}>{split.teamLead.question}</div>
			</Land>
			<Land at={t.bars} style={{top: 196, display: 'flex', justifyContent: 'space-between'}}>
				<Label>{split.labels.evidence}</Label>
				<QueryChip />
			</Land>
			{bars.map((b, i) => {
				const p = ramp(frame, t.bars + 6 + i * 8, t.bars + 40 + i * 8, easeOut);
				const v = num(b.value);
				return (
					<Land key={b.team} at={t.bars + i * 6} style={{top: 230 + i * 56}}>
						<div style={{display: 'flex', justifyContent: 'space-between', fontSize: 20, color: color.text}}>
							<span>{b.team}</span>
							<span style={{fontWeight: 800, fontVariantNumeric: 'tabular-nums'}}>{fmtInt(v * p)}</span>
						</div>
						<div style={{height: 18, marginTop: 6, borderRadius: 6, width: `${Math.max(2, 100 * (v / max) * p)}%`, background: i === 0 ? '#5b6573' : '#3b4450'}} />
					</Land>
				);
			})}
			<Land at={t.persistent} style={{top: 352, display: 'flex', alignItems: 'center', gap: 18}}>
				<DaysRing lit={lit} r={30} stroke={9} />
				<div>
					<div style={{fontSize: 23, fontWeight: 800, color: color.text}}>"{message}"</div>
					<div style={{fontSize: 20, color: color.muted, marginTop: 4, fontVariantNumeric: 'tabular-nums'}}>
						{Math.round(lit)} of {of} days · {teamLead.persistent.trendLabel}
					</div>
				</div>
			</Land>
			<Land at={t.first} style={{top: 470}}>
				<Label>{split.labels.next}</Label>
				<div style={{fontSize: 23, color: color.muted, marginTop: 10}}>{teamLead.first.label}</div>
			</Land>
			<Land at={t.first + 6} style={{top: 536, fontSize: 28, fontWeight: 800, color: color.accent}}>
				→ {teamLead.first.team}
			</Land>
		</>
	);
};

const ManagerColumn: React.FC<{t: SplitTimes['mg']}> = ({t}) => {
	const frame = useCurrentFrame();
	const {fps} = useVideoConfig();
	const pop = spring({frame: frame - t.top, fps, config: {damping: 8, stiffness: 220, mass: 0.5}});
	const counter = manager.cards[0].counter ?? 0;
	const shown = Math.round(counter * ramp(frame, t.top, t.top + 30, easeOut));
	return (
		<>
			<Land at={t.question} style={{top: 84}}>
				<Label>{split.labels.question}</Label>
				<div style={{fontSize: 30, fontWeight: 600, color: color.text, marginTop: 8, lineHeight: 1.2}}>{split.manager.question}</div>
			</Land>
			<Land at={t.risks} style={{top: 196, display: 'flex', justifyContent: 'space-between'}}>
				<Label>{split.labels.evidence}</Label>
				<QueryChip />
			</Land>
			{manager.cards.map((c, i) => {
				const first = i === 0;
				const hot = first ? Math.min(1, Math.max(0, frame - t.top) / 8) : 0;
				return (
					<Land key={c.label} at={t.risks + 6 + i * 6} style={{top: 226 + i * 44}}>
						<div
							style={{
								height: 38,
								boxSizing: 'border-box',
								display: 'flex',
								alignItems: 'center',
								gap: 10,
								padding: '0 10px',
								borderRadius: 8,
								background: hot > 0 ? '#2a2215' : '#161b22',
								border: `2px solid ${hot > 0 ? color.accent : color.line}`,
								fontSize: 18,
							}}
						>
							<span style={{fontWeight: 800, color: first ? color.accent : color.muted, width: 14}}>{i + 1}</span>
							<span style={{flex: 1, color: color.text, fontWeight: first ? 800 : 500, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis'}}>{c.label}</span>
							{first && frame >= t.top ? (
								<span style={{fontWeight: 800, color: color.accent, fontVariantNumeric: 'tabular-nums', display: 'inline-block', transform: `scale(${0.6 + 0.4 * pop})`}}>+{shown}%</span>
							) : null}
							<span style={{fontSize: 14, color: color.muted, whiteSpace: 'nowrap'}}>{c.owner.split(' · ')[0]}</span>
						</div>
					</Land>
				);
			})}
			<Land at={t.limit} style={{top: 470}}>
				<Label>{split.labels.next}</Label>
				<div style={{fontSize: 28, fontWeight: 800, color: color.accent, marginTop: 10}}>→ {split.manager.action}</div>
			</Land>
			<Land at={t.limit + 14} style={{top: 548, fontSize: 20, color: color.muted, fontStyle: 'italic'}}>
				{manager.limit}
			</Land>
		</>
	);
};

/** Brightness of a column: dim before its turn, lit while its presenter speaks, half after, lit again at "all lit". */
const columnLevel = (frame: number, start: number, end: number, allLit: number) => {
	const on = ramp(frame, start, start + 12);
	const off = end < allLit ? ramp(frame, end, end + 12) : 0;
	const all = end < allLit ? ramp(frame, allLit, allLit + 14) : 0;
	return 0.3 + 0.7 * on - 0.5 * off + 0.5 * all;
};

/** The header and the three columns. Columns fly in from the terminal at the lift-off. */
export const SplitBoard: React.FC<{times: SplitTimes}> = ({times: T}) => {
	const frame = useCurrentFrame();
	const {fps} = useVideoConfig();
	const answer = ramp(frame, T.allLit, T.allLit + 18);
	const head = spring({frame: frame - T.liftoff, fps, config: {damping: 200}, durationInFrames: 24});
	const sweep = ramp(frame, T.allLit, T.allLit + 34, ease);
	const levels = [
		columnLevel(frame, T.eng.start, T.eng.end, T.allLit),
		columnLevel(frame, T.tl.start, T.tl.end, T.allLit),
		columnLevel(frame, T.mg.start, Infinity, T.allLit),
	];
	const active = (start: number, end: number) => ramp(frame, start, start + 12) * (1 - ramp(frame, end, end + 12));
	const glows = [active(T.eng.start, T.eng.end), active(T.tl.start, T.tl.end), active(T.mg.start, T.allLit)].map(
		(g) => Math.max(g, Math.sin(Math.PI * Math.min(1, Math.max(0, sweep))) * 0.8),
	);
	const fly = (i: number) => {
		const s = spring({frame: frame - T.liftoff - i * 5, fps, config: {damping: 15, stiffness: 120, mass: 0.8}});
		const dx = 960 - (colX(i) + COL_W / 2);
		const dy = 540 - (COL_TOP + COL_H / 2);
		return {transform: `translate(${dx * (1 - s)}px, ${dy * (1 - s)}px) scale(${0.55 + 0.45 * s})`, opacity: Math.min(1, s * 1.6)};
	};
	const cols = [
		<Column key="e" i={0} role={split.engineer.role} level={levels[0]} glow={glows[0]}>
			<EngineerColumn t={T.eng} />
		</Column>,
		<Column key="t" i={1} role={split.teamLead.role} level={levels[1]} glow={glows[1]}>
			<TeamLeadColumn t={T.tl} />
		</Column>,
		<Column key="m" i={2} role={split.manager.role} level={levels[2]} glow={glows[2]}>
			<ManagerColumn t={T.mg} />
		</Column>,
	];
	return (
		<AbsoluteFill style={{fontFamily: font.sans, background: 'radial-gradient(ellipse at 50% 40%, #10161e 0%, #030405 75%)'}}>
			<div style={{position: 'absolute', left: 0, right: 0, top: 60, textAlign: 'center', opacity: head, transform: `translateY(${(1 - head) * -20}px)`}}>
				<div style={{position: 'relative', height: 64, fontSize: 56, fontWeight: 800, color: color.text, letterSpacing: -1}}>
					<div style={{position: 'absolute', left: 0, right: 0, opacity: 1 - answer}}>{split.header.ask}</div>
					<div style={{position: 'absolute', left: 0, right: 0, opacity: answer, transform: `scale(${1 + 0.04 * Math.sin(Math.PI * answer)})`}}>
						{split.header.answer.split('Three answers.')[0]}
						<span style={{color: color.accent}}>Three answers.</span>
					</div>
				</div>
				<div style={{fontSize: 24, color: color.muted, marginTop: 14}}>{split.header.scope}</div>
			</div>
			{cols.map((c, i) => (
				<AbsoluteFill key={i} style={{...fly(i), transformOrigin: `${colX(i) + COL_W / 2}px ${COL_TOP + COL_H / 2}px`}}>
					{c}
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
		</AbsoluteFill>
	);
};

// ---------------------------------------------------------------- proof clip

/** roles.mp4 at PROOF_RATE in a terminal frame; holds its last frame if it runs out. */
const ProofClip: React.FC<{assets: ResolvedAssets; liftoff: number}> = ({assets, liftoff}) => {
	const frame = useCurrentFrame();
	const {fps} = useVideoConfig();
	const inS = spring({frame, fps, config: {damping: 200}, durationInFrames: 20});
	const out = ramp(frame, liftoff, liftoff + 22, ease);
	const a = assets.rolesRec;
	const recFrames = Math.ceil(a.seconds * FPS);
	const video = <OffthreadVideo src={staticFile(`assets/${ASSETS.rolesRec.file}`)} muted playbackRate={PROOF_RATE} style={{width: '100%', height: '100%', objectFit: 'contain'}} />;
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
					<div style={{fontFamily: font.sans, fontSize: 16, fontWeight: 800, color: color.accent}}>{PROOF_RATE}×</div>
				</div>
				<div style={{flex: 1, position: 'relative'}}>
					{a.present ? (
						frame * PROOF_RATE < recFrames - 2 ? (
							video
						) : (
							<Freeze frame={Math.floor((recFrames - 2) / PROOF_RATE)}>{video}</Freeze>
						)
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

const offset = (timing: [number, number][], at: number) => timing.map(([a]) => a + at);

export const SplitScene: React.FC<{assets: ResolvedAssets; frames: number; parts: ScenePart[]}> = ({assets, frames, parts}) => {
	const frame = useCurrentFrame();
	const starts = splitStarts(parts);
	const [s2, s3, s4, s5] = starts;
	const e = offset(cueFrames(split.engineer.cues, parts[0].frames), s2);
	const tl = offset(cueFrames(split.teamLead.cues, parts[1].frames), s3);
	const mg = offset(cueFrames(split.manager.cues, parts[2].frames), s4);
	const ev = offset(cueFrames(split.evidence.cues, parts[3].frames), s5);
	const ea = split.engineer.at;
	const ta = split.teamLead.at;
	const ma = split.manager.at;
	const liftoff = e[ea.liftoff];
	const T: SplitTimes = {
		liftoff,
		eng: {start: liftoff + 10, end: s3, node: e[ea.node], share: e[ea.share], message: e[ea.message], before: e[ea.before], hypothesis: e[ea.hypothesis], check: e[ea.check]},
		tl: {start: s3, end: s4, question: tl[ta.question], bars: tl[ta.bars], persistent: tl[ta.persistent], first: tl[ta.first]},
		mg: {start: s4, question: mg[ma.question], risks: mg[ma.risks], top: mg[ma.top], limit: mg[ma.limit]},
		allLit: mg[ma.allLit],
	};
	const pushAt = ev[split.evidence.at.open];
	const snapAt = ev[split.evidence.at.snap];
	const pullAt = frames - PULL_FRAMES - 12;
	const push = ramp(frame, pushAt, pushAt + PUSH_FRAMES, ease) * (1 - ramp(frame, pullAt, pullAt + PULL_FRAMES, ease));
	const drift = interpolate(frame, [liftoff, frames], [1, 1.025], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
	const lands = [T.eng.node, T.eng.share, T.eng.before, T.eng.message, T.eng.check, T.tl.bars, T.tl.persistent, T.tl.first, T.mg.risks, T.mg.top, T.mg.limit];
	const facecams: AssetKey[] = ['s2', 's3', 's4', 's5'];
	return (
		<AbsoluteFill style={{backgroundColor: INK}}>
			<Sequence durationInFrames={liftoff + LIFT_FRAMES} name="proof clip">
				<ProofClip assets={assets} liftoff={liftoff} />
			</Sequence>
			{frame >= liftoff ? (
				<AbsoluteFill
					style={{
						transform: `scale(${drift * (1 + 2.2 * push)})`,
						transformOrigin: `${CHIP.x}px ${CHIP.y}px`,
						opacity: 1 - 0.9 * push,
						filter: `blur(${6 * push}px)`,
					}}
				>
					<SplitBoard times={T} />
				</AbsoluteFill>
			) : null}
			<Sequence from={pushAt + 8} durationInFrames={Math.max(1, snapAt - pushAt - 8)} name="citation">
				<AbsoluteFill style={{opacity: push}}>
					<CitationShot />
				</AbsoluteFill>
			</Sequence>
			<Sequence from={snapAt} durationInFrames={Math.max(1, frames - snapAt)} name="152,734 = 152,734">
				<AbsoluteFill style={{opacity: push}}>
					<SnapShot />
				</AbsoluteFill>
			</Sequence>
			{facecams.map((key, i) => (
				<Sequence key={key} from={starts[i]} durationInFrames={parts[i].frames} name={`facecam ${key}`}>
					<FilmFacecam assetKey={key} assets={assets} corner={1} />
				</Sequence>
			))}
			{(['s3', 's4'] as const).map((key) => (
				<Sequence key={key} from={(key === 's3' ? s3 : s4) + 8} durationInFrames={NAME_TAG_FRAMES} name={`name tag ${key}`}>
					<NameTag assetKey={key} frames={NAME_TAG_FRAMES} small />
				</Sequence>
			))}
			<Sfx name="whoosh" from={liftoff - 4} volume={0.35} />
			{lands.map((f, i) => (
				<Sfx key={i} name="click" from={f} volume={0.16} />
			))}
			<Sfx name="chime" from={T.allLit} volume={0.4} />
			<Sfx name="whoosh" from={pushAt - 2} volume={0.25} />
			<Sfx name="impact" from={snapAt + 40} volume={0.3} />
			<Vignette />
			<Grain />
			<BlackFades frames={frames} fadeIn={12} fadeOut={18} />
		</AbsoluteFill>
	);
};
