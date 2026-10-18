// Shots for the intro card, scenes 3–7 and the star gag. Same rules as shots.tsx: one idea per shot, local
// frames, `done` draws the final built state for the slides PDF.
import React from 'react';
import {AbsoluteFill, Img, interpolate, spring, staticFile, useCurrentFrame, useVideoConfig} from 'remotion';
import {isComplete, type Benchmarks} from './benchmarks';
import {benchmarks as benchContent, close, evidence, intro, manager, REPO_URL, star, teamLead} from './content';
import {ease, easeOut, ramp} from './film';
import {RED} from './shots';
import {color, font} from './theme';

const num = (s: string) => Number(s.replace(/[^0-9.]/g, ''));
const fmtInt = (n: number) => Math.round(n).toLocaleString('en-US');
const useSpring = (delay: number, done?: boolean, config: Parameters<typeof spring>[0]['config'] = {damping: 200}) => {
	const frame = useCurrentFrame();
	const {fps} = useVideoConfig();
	return done ? 1 : spring({frame: frame - delay, fps, config, durationInFrames: config?.damping === 200 ? 24 : undefined});
};

// ------------------------------------------------------------------ logos

/** SchubKI wordmark, rendered as text like their site: bold sans, "Schub" white, "KI" gold. */
export const SchubKI: React.FC<{size: number}> = ({size}) => (
	<span style={{fontFamily: font.sans, fontWeight: 800, fontSize: size, letterSpacing: -0.02 * size, color: '#fff', lineHeight: 1}}>
		{intro.schubki.first}
		<span style={{color: intro.schubki.gold}}>{intro.schubki.accent}</span>
	</span>
);

/**
 * The SereneDB logo as published (123×32); only scaled, never recoloured. The file's wordmark is filled black
 * (despite SOURCES.md calling it the dark-theme version), so it sits on a light plate to stay visible.
 */
export const SereneLogo: React.FC<{height: number}> = ({height}) => (
	<div style={{background: '#f4f5f7', borderRadius: height * 0.28, padding: `${height * 0.22}px ${height * 0.34}px`}}>
		<Img src={staticFile(intro.sereneLogo)} style={{height, width: (height * 123) / 32, display: 'block'}} />
	</div>
);

export const LogoPair: React.FC<{height: number; gap?: number}> = ({height, gap = height * 0.7}) => (
	<div style={{display: 'flex', alignItems: 'center', gap}}>
		<SchubKI size={height * 0.9} />
		<span style={{fontFamily: font.sans, fontSize: height * 0.6, color: color.muted, fontWeight: 300}}>×</span>
		<SereneLogo height={height} />
	</div>
);

export const IntroShot: React.FC = () => {
	const frame = useCurrentFrame();
	const a = ramp(frame, 4, 18);
	const b = useSpring(22);
	return (
		<AbsoluteFill style={{justifyContent: 'center', alignItems: 'center', fontFamily: font.sans, gap: 44}}>
			<div style={{fontSize: 30, letterSpacing: '0.3em', color: color.muted, opacity: a, fontWeight: 600}}>
				{intro.event.toUpperCase()}
			</div>
			<div style={{opacity: b, transform: `translateY(${(1 - b) * 14}px)`}}>
				<LogoPair height={84} />
			</div>
		</AbsoluteFill>
	);
};

// ------------------------------------------------------------------ 3 team lead

const SmallCaps: React.FC<{children: React.ReactNode; style?: React.CSSProperties}> = ({children, style}) => (
	<div style={{fontFamily: font.sans, fontSize: 28, letterSpacing: '0.24em', color: color.muted, textTransform: 'uppercase', ...style}}>
		{children}
	</div>
);

/** Whole-corpus FATAL counts by team, as bars that grow. */
export const BarsShot: React.FC<{done?: boolean; scale?: number}> = ({done, scale = 1}) => {
	const frame = useCurrentFrame();
	const bars = teamLead.fatalBars;
	const max = Math.max(...bars.map((b) => num(b.value)));
	const W = 1000 * scale;
	return (
		<AbsoluteFill style={{justifyContent: 'center', alignItems: 'center', fontFamily: font.sans}}>
			<div style={{display: 'flex', flexDirection: 'column', gap: 40 * scale}}>
				<SmallCaps style={{opacity: done ? 1 : ramp(frame, 0, 12), fontSize: 28 * scale}}>{teamLead.fatalBarsLabel}</SmallCaps>
				{bars.map((b, i) => {
					const p = done ? 1 : ramp(frame, 10 + i * 10, 52 + i * 10, easeOut);
					const v = num(b.value);
					return (
						<div key={b.team} style={{display: 'flex', alignItems: 'center', gap: 32 * scale}}>
							<div style={{width: 400 * scale, textAlign: 'right', fontSize: 44 * scale, fontWeight: 600, color: color.text}}>{b.team}</div>
							<div style={{width: W, display: 'flex', alignItems: 'center', gap: 24 * scale}}>
								<div
									style={{
										width: Math.max(6 * scale, (W - 260 * scale) * (v / max) * p),
										height: 72 * scale,
										borderRadius: 10 * scale,
										background: i === 0 ? '#5b6573' : '#3b4450',
									}}
								/>
								<div style={{fontSize: 44 * scale, fontWeight: 800, color: color.text, fontVariantNumeric: 'tabular-nums', opacity: Math.min(1, p * 2)}}>
									{fmtInt(v * p)}
								</div>
							</div>
						</div>
					);
				})}
			</div>
		</AbsoluteFill>
	);
};

/** 31 ring segments, 22 lit: a share of days, deliberately not a calendar. */
export const DaysRing: React.FC<{lit: number; r: number; stroke: number}> = ({lit, r, stroke}) => {
	const {days, of} = teamLead.persistent;
	const size = 2 * r + 2 * stroke;
	const gapDeg = 3.2;
	const seg = 360 / of;
	const arc = (i: number) => {
		const a0 = ((i * seg + gapDeg / 2 - 90) * Math.PI) / 180;
		const a1 = (((i + 1) * seg - gapDeg / 2 - 90) * Math.PI) / 180;
		const c = size / 2;
		return `M ${c + r * Math.cos(a0)} ${c + r * Math.sin(a0)} A ${r} ${r} 0 0 1 ${c + r * Math.cos(a1)} ${c + r * Math.sin(a1)}`;
	};
	return (
		<svg width={size} height={size}>
			{Array.from({length: of}, (_, i) => {
				const on = Math.max(0, Math.min(1, lit - i)) * (i < days ? 1 : 0);
				return <path key={i} d={arc(i)} fill="none" strokeWidth={stroke} stroke={on > 0 ? color.accent : '#222a33'} opacity={on > 0 ? 0.35 + 0.65 * on : 1} />;
			})}
		</svg>
	);
};

export const DaysShot: React.FC<{done?: boolean}> = ({done}) => {
	const frame = useCurrentFrame();
	const {days, of, message} = teamLead.persistent;
	const lit = done ? days : interpolate(frame, [18, 70], [0, days], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: ease});
	const head = done ? 1 : ramp(frame, 0, 12);
	return (
		<AbsoluteFill style={{alignItems: 'center', fontFamily: font.sans}}>
			<div style={{position: 'absolute', top: 120, fontFamily: font.mono, fontSize: 52, color: RED, opacity: head}}>“{message}”</div>
			<div style={{position: 'absolute', top: 250}}>
				<DaysRing lit={lit} r={250} stroke={34} />
				<div
					style={{
						position: 'absolute',
						inset: 0,
						display: 'flex',
						flexDirection: 'column',
						alignItems: 'center',
						justifyContent: 'center',
					}}
				>
					<div style={{fontSize: 150, fontWeight: 800, color: color.text, lineHeight: 1, fontVariantNumeric: 'tabular-nums'}}>
						{Math.floor(lit)}
					</div>
					<div style={{fontSize: 40, color: color.muted}}>of {of} days</div>
				</div>
			</div>
		</AbsoluteFill>
	);
};

export const TrendShot: React.FC<{done?: boolean}> = ({done}) => {
	const s = useSpring(2, done);
	const w = useSpring(14, done);
	return (
		<AbsoluteFill style={{justifyContent: 'center', alignItems: 'center', fontFamily: font.sans}}>
			<div style={{fontSize: 220, fontWeight: 800, color: color.text, lineHeight: 1, opacity: s, transform: `scale(${0.92 + 0.08 * s})`}}>
				{teamLead.persistent.trend}
			</div>
			<div style={{fontSize: 56, color: color.accent, marginTop: 30, opacity: w}}>{teamLead.persistent.trendLabel}</div>
		</AbsoluteFill>
	);
};

export const FirstShot: React.FC<{done?: boolean}> = ({done}) => {
	const frame = useCurrentFrame();
	const a = done ? 1 : ramp(frame, 0, 12);
	const b = useSpring(10, done);
	const line = done ? 1 : ramp(frame, 22, 44, easeOut);
	return (
		<AbsoluteFill style={{justifyContent: 'center', alignItems: 'center', fontFamily: font.sans}}>
			<SmallCaps style={{opacity: a, fontSize: 32}}>{teamLead.first.label}</SmallCaps>
			<div style={{fontSize: 130, fontWeight: 800, color: color.text, marginTop: 24, opacity: b, transform: `translateY(${(1 - b) * 16}px)`}}>
				{teamLead.first.team}
			</div>
			<div style={{width: 640 * line, height: 6, background: color.accent, marginTop: 18, borderRadius: 3}} />
		</AbsoluteFill>
	);
};

// ------------------------------------------------------------------ 4 manager

export const RiskCards: React.FC<{done?: boolean; scale?: number; top?: number}> = ({done, scale = 1, top = 150}) => {
	const frame = useCurrentFrame();
	const {fps} = useVideoConfig();
	const H = 118 * scale;
	const GAP = 22 * scale;
	const W = 1380 * scale;
	return (
		<AbsoluteFill style={{fontFamily: font.sans}}>
			{manager.cards.map((c, i) => {
				const delay = 6 + i * 16;
				const s = done ? 1 : spring({frame: frame - delay, fps, config: {damping: 18, stiffness: 140, mass: 0.7}});
				const first = i === 0;
				const counter = c.counter ?? 0;
				const shown = done ? counter : Math.round(counter * ramp(frame, delay + 10, delay + 50, easeOut));
				return (
					<div
						key={c.label}
						style={{
							position: 'absolute',
							left: (1920 - W) / 2,
							top: top + i * (H + GAP),
							width: W,
							height: H,
							boxSizing: 'border-box',
							display: 'flex',
							alignItems: 'center',
							gap: 34 * scale,
							padding: `0 ${36 * scale}px`,
							borderRadius: 18 * scale,
							background: first ? '#2a2215' : color.panel,
							border: `${3 * scale}px solid ${first ? color.accent : color.line}`,
							opacity: Math.min(1, s * 1.4),
							transform: `translateY(${(1 - s) * 60}px)`,
						}}
					>
						<div style={{fontSize: 52 * scale, fontWeight: 800, width: 50 * scale, color: first ? color.accent : color.muted}}>{i + 1}</div>
						<div style={{flex: 1, fontSize: 44 * scale, fontWeight: first ? 800 : 600, color: color.text}}>{c.label}</div>
						{c.counter ? (
							<div style={{fontSize: 56 * scale, fontWeight: 800, color: color.accent, fontVariantNumeric: 'tabular-nums'}}>+{shown}%</div>
						) : null}
						<div
							style={{
								fontSize: 28 * scale,
								fontWeight: 600,
								color: color.text,
								background: '#2b333d',
								borderRadius: 999,
								padding: `${8 * scale}px ${22 * scale}px`,
								whiteSpace: 'nowrap',
							}}
						>
							{c.owner}
						</div>
					</div>
				);
			})}
		</AbsoluteFill>
	);
};

export const LimitShot: React.FC = () => {
	const s = useSpring(4);
	return (
		<AbsoluteFill style={{justifyContent: 'center', alignItems: 'center', fontFamily: font.sans}}>
			<div style={{fontSize: 84, fontWeight: 300, color: color.text, opacity: s, letterSpacing: `${(1 - s) * 0.1}em`}}>{manager.limit}</div>
		</AbsoluteFill>
	);
};

// ------------------------------------------------------------------ 5 evidence

/** A [Q46] citation chip that opens into the SQL that proved it. */
export const CitationShot: React.FC<{done?: boolean; scale?: number}> = ({done, scale = 1}) => {
	const frame = useCurrentFrame();
	const chip = useSpring(4, done);
	const open = done ? 1 : ramp(frame, 34, 60, ease);
	const lines = evidence.sqlExcerpt;
	return (
		<AbsoluteFill style={{justifyContent: 'center', alignItems: 'center', fontFamily: font.mono}}>
			<div
				style={{
					background: color.panel,
					border: `${3 * scale}px solid ${color.accent}`,
					borderRadius: interpolate(open, [0, 1], [999, 22]) * scale,
					padding: `${interpolate(open, [0, 1], [18, 40]) * scale}px ${40 * scale}px`,
					opacity: chip,
					transform: `scale(${0.85 + 0.15 * chip})`,
					overflow: 'hidden',
				}}
			>
				<div style={{fontSize: 48 * scale, whiteSpace: 'pre'}}>
					<span style={{color: color.accent, fontWeight: 600}}>[{evidence.handle}]</span>
					<span style={{color: color.text}}> {evidence.tool}</span>
				</div>
				<div style={{height: interpolate(open, [0, 1], [0, (lines.length * 52 + 30) * scale]), overflow: 'hidden'}}>
					<div style={{paddingTop: 30 * scale}}>
						{lines.map((l, i) => (
							<div
								key={l}
								style={{
									fontSize: 36 * scale,
									lineHeight: 1.44,
									whiteSpace: 'pre',
									color: i === 2 ? color.text : color.muted,
									opacity: done ? 1 : ramp(frame, 50 + i * 8, 62 + i * 8),
								}}
							>
								{l}
							</div>
						))}
					</div>
				</div>
			</div>
		</AbsoluteFill>
	);
};

/** Two 152,734s slide together and snap into one equation. */
export const SnapShot: React.FC<{done?: boolean; scale?: number}> = ({done, scale = 1}) => {
	const frame = useCurrentFrame();
	const {fps} = useVideoConfig();
	const slide = done ? 1 : ramp(frame, 6, 40, ease);
	const snap = done ? 1 : spring({frame: frame - 40, fps, config: {damping: 9, stiffness: 220, mass: 0.5}});
	const eq = done ? 1 : ramp(frame, 38, 46);
	const cap = done ? 1 : ramp(frame, 56, 74);
	const off = (1 - slide) * 420 * scale;
	const big: React.CSSProperties = {fontSize: 136 * scale, fontWeight: 800, color: color.accent, fontVariantNumeric: 'tabular-nums', lineHeight: 1};
	return (
		<AbsoluteFill style={{justifyContent: 'center', alignItems: 'center', fontFamily: font.sans}}>
			<div style={{display: 'flex', alignItems: 'center', gap: 44 * scale, transform: `scale(${1 + 0.04 * Math.sin(Math.min(1, snap) * Math.PI)})`}}>
				<div style={{...big, transform: `translateX(${-off}px)`}}>{evidence.left.value}</div>
				<div style={{fontSize: 130 * scale, fontWeight: 300, color: color.text, opacity: eq}}>=</div>
				<div style={{...big, transform: `translateX(${off}px)`}}>{evidence.right.value}</div>
			</div>
			<div style={{fontSize: 46 * scale, color: color.text, marginTop: 44 * scale, opacity: cap}}>{evidence.snapCaption}</div>
		</AbsoluteFill>
	);
};

// ------------------------------------------------------------------ 6 benchmarks

export const TodoStamp: React.FC<{scale?: number; style?: React.CSSProperties}> = ({scale = 1, style}) => (
	<div
		style={{
			transform: 'rotate(-7deg)',
			border: `${7 * scale}px solid ${color.placeholder}`,
			color: color.placeholder,
			fontFamily: font.sans,
			fontWeight: 800,
			padding: `${8 * scale}px ${30 * scale}px`,
			borderRadius: 12 * scale,
			background: 'rgba(3,4,5,0.9)',
			textAlign: 'center',
			...style,
		}}
	>
		<div style={{fontSize: 72 * scale, letterSpacing: 6 * scale}}>TODO</div>
		<div style={{fontSize: 24 * scale, fontWeight: 600}}>{benchContent.todo}</div>
	</div>
);

export const BenchShot: React.FC<{done?: boolean; benchmarks: Benchmarks | null; footnote?: boolean}> = ({done, benchmarks, footnote}) => {
	const frame = useCurrentFrame();
	const designs = benchmarks?.designs ?? [];
	const complete = benchmarks !== null && isComplete(benchmarks);
	const max = complete ? Math.max(...designs.map((d) => d.score_pct ?? 0), 1) : 1;
	const W = 940;
	const title = done ? 1 : ramp(frame, 0, 14);
	const stamp = useSpring(70, done, {damping: 12, stiffness: 200, mass: 0.6});
	return (
		<AbsoluteFill style={{fontFamily: font.sans, alignItems: 'center'}}>
			<div style={{position: 'absolute', top: 110, fontSize: 72, fontWeight: 800, color: color.text, opacity: title}}>{benchContent.title}</div>
			<div style={{position: 'absolute', top: 330, display: 'flex', flexDirection: 'column', gap: 50}}>
				{designs.map((d, i) => {
					const p = done ? 1 : ramp(frame, 16 + i * 10, 60 + i * 10, easeOut);
					const share = complete ? (d.score_pct ?? 0) / max : 1;
					return (
						<div key={d.name} style={{display: 'flex', alignItems: 'center', gap: 32}}>
							<div style={{width: 680, textAlign: 'right', fontSize: 40, fontWeight: d.ours ? 800 : 500, color: d.ours ? color.accent : color.text}}>
								{d.name}
							</div>
							<div style={{width: W}}>
								<div
									style={{
										width: W * share * p,
										height: 86,
										borderRadius: 10,
										boxSizing: 'border-box',
										display: 'flex',
										alignItems: 'center',
										padding: '0 26px',
										fontSize: 38,
										fontWeight: 700,
										whiteSpace: 'nowrap',
										overflow: 'hidden',
										color: d.ours ? '#030405' : color.text,
										background: complete
											? d.ours
												? color.accent
												: '#3b4450'
											: `repeating-linear-gradient(135deg, ${d.ours ? 'rgba(245,165,36,0.35)' : 'rgba(110,120,135,0.3)'} 0 14px, transparent 14px 28px)`,
										border: complete ? 'none' : `3px solid ${d.ours ? color.accent : color.line}`,
									}}
								>
									{complete ? `${d.score_pct}% · $${d.usd_per_answer}` : ''}
								</div>
							</div>
						</div>
					);
				})}
			</div>
			{footnote && benchmarks ? (
				<div style={{position: 'absolute', bottom: 80, fontSize: 30, color: complete ? color.muted : color.placeholder}}>{benchmarks.footnote}</div>
			) : null}
			{complete ? null : (
				<div style={{position: 'absolute', right: 260, top: 760, opacity: stamp, transform: `scale(${1.6 - 0.6 * stamp})`}}>
					<TodoStamp />
				</div>
			)}
		</AbsoluteFill>
	);
};

// ------------------------------------------------------------------ 7 end card

export const EndCard: React.FC<{done?: boolean}> = ({done}) => {
	const frame = useCurrentFrame();
	const a = done ? 1 : ramp(frame, 0, 16);
	const b = done ? 1 : ramp(frame, 14, 32);
	const c = done ? 1 : ramp(frame, 30, 48);
	return (
		<AbsoluteFill style={{justifyContent: 'center', alignItems: 'center', fontFamily: font.sans}}>
			<div style={{fontSize: 56, fontWeight: 300, color: color.text, opacity: a}}>{close.cardLine}</div>
			<div style={{fontFamily: font.mono, fontSize: 64, fontWeight: 600, color: color.accent, marginTop: 40, opacity: b}}>{REPO_URL}</div>
			<div style={{position: 'absolute', bottom: 110, opacity: c}}>
				<LogoPair height={44} />
			</div>
		</AbsoluteFill>
	);
};

// ------------------------------------------------------------------ 8 star gag

const Cursor: React.FC = () => (
	<svg width={40} height={52} viewBox="0 0 20 26">
		<path d="M1 1 L1 20 L6 15.5 L9.5 23.5 L13 22 L9.6 14.2 L16 14.2 Z" fill="#fff" stroke="#000" strokeWidth={1.4} strokeLinejoin="round" />
	</svg>
);

const RepoIcon: React.FC = () => (
	<svg width={40} height={40} viewBox="0 0 16 16">
		<path d="M3 1.75C3 1.34 3.34 1 3.75 1H13v11H4.5a1.5 1.5 0 0 0 0 3H13" fill="none" stroke={color.muted} strokeWidth={1.3} strokeLinejoin="round" />
		<path d="M3 1.75V13.5" fill="none" stroke={color.muted} strokeWidth={1.3} />
	</svg>
);

/** A generic repo pill; a cursor clicks Star; it flips to Starred with a pop. No count, no logo. */
export const StarShot: React.FC = () => {
	const frame = useCurrentFrame();
	const {fps} = useVideoConfig();
	const pill = spring({frame: frame - 2, fps, config: {damping: 200}, durationInFrames: 18});
	const CLICK = 46;
	const move = ramp(frame, 14, CLICK - 4, ease);
	const pressed = frame >= CLICK - 2 && frame < CLICK + 4;
	const starred = frame >= CLICK;
	const pop = spring({frame: frame - CLICK, fps, config: {damping: 8, stiffness: 260, mass: 0.5}});
	const cap = ramp(frame, CLICK + 14, CLICK + 30);
	// Button centre in frame coordinates (pill centred at 960,480).
	const target = {x: 1252, y: 494};
	const cursor = {x: interpolate(move, [0, 1], [1620, target.x]), y: interpolate(move, [0, 1], [900, target.y])};
	return (
		<AbsoluteFill style={{fontFamily: font.sans, background: '#030405'}}>
			<div
				style={{
					position: 'absolute',
					left: 960 - 440,
					top: 480 - 60,
					width: 880,
					height: 120,
					boxSizing: 'border-box',
					display: 'flex',
					alignItems: 'center',
					gap: 22,
					padding: '0 30px',
					borderRadius: 16,
					background: '#0d1117',
					border: '2px solid #30363d',
					opacity: pill,
					transform: `scale(${0.94 + 0.06 * pill})`,
				}}
			>
				<RepoIcon />
				<div style={{flex: 1, fontSize: 44, color: '#4493f8', fontWeight: 600}}>
					{star.repo.owner} / <span style={{fontWeight: 800}}>{star.repo.name}</span>
				</div>
				<div
					style={{
						display: 'flex',
						alignItems: 'center',
						gap: 14,
						padding: '14px 28px',
						borderRadius: 12,
						border: '2px solid #3d444d',
						background: pressed ? '#30363d' : '#21262d',
						fontSize: 38,
						fontWeight: 600,
						color: '#f0f6fc',
						transform: `scale(${pressed ? 0.95 : 1})`,
					}}
				>
					<span
						style={{
							color: starred ? '#e3b341' : '#9198a1',
							display: 'inline-block',
							transform: `scale(${starred ? 1 + 0.5 * Math.max(0, 1 - pop) * (pop > 0 ? 1 : 0) + 0.0 : 1}) rotate(${starred ? (1 - Math.min(1, pop)) * -40 : 0}deg)`,
						}}
					>
						{starred ? '★' : '☆'}
					</span>
					{starred ? 'Starred' : 'Star'}
				</div>
			</div>
			<div style={{position: 'absolute', left: cursor.x, top: cursor.y, transform: `scale(${pressed ? 0.88 : 1})`, transformOrigin: '0 0'}}>
				<Cursor />
			</div>
			<div style={{position: 'absolute', left: 0, right: 0, top: 640, textAlign: 'center', fontSize: 48, color: color.text, opacity: cap}}>
				{star.caption}
			</div>
		</AbsoluteFill>
	);
};
