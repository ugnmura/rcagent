// Shots for the intro card, scenes 3–7 and the star gag. Same rules as shots.tsx: one idea per shot, local
// frames, `done` draws the final built state for the slides PDF.
import React from 'react';
import {AbsoluteFill, Audio, Img, interpolate, interpolateColors, random, Sequence, spring, staticFile, useCurrentFrame, useVideoConfig} from 'remotion';
import {DesignLabel} from './bench';
import {hasNumbers, type Benchmarks} from './benchmarks';
import {benchmarks as benchContent, close, evidence, intro, manager, PROJECT_NAME, star, teamLead} from './content';
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

/** The SereneDB logo as published for dark backgrounds (123×32); only scaled, never recoloured. */
export const SereneLogo: React.FC<{height: number}> = ({height}) => (
	<Img src={staticFile(intro.sereneLogo)} style={{height, width: (height * 123) / 32, display: 'block'}} />
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
	const complete = benchmarks !== null && hasNumbers(benchmarks);
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
							<DesignLabel d={d} width={680} size={42} />
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
										background: complete ? (d.ours ? color.accent : '#3b4450') : 'transparent',
										border: complete ? 'none' : `3px dashed ${d.ours ? color.accent : color.line}`,
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
				<div style={{position: 'absolute', bottom: 80, fontSize: 30, color: benchmarks.final ? color.muted : color.placeholder}}>{benchmarks.footnote}</div>
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
			<div style={{fontFamily: font.mono, fontSize: 64, fontWeight: 600, color: color.accent, marginTop: 40, opacity: b}}>{PROJECT_NAME}</div>
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

const GOLD = '#e3b341';
const STAR_PATH = 'M8 .25a.75.75 0 0 1 .673.418l1.882 3.815 4.21.612a.75.75 0 0 1 .416 1.279l-3.046 2.97.719 4.192a.751.751 0 0 1-1.088.791L8 12.347l-3.766 1.98a.75.75 0 0 1-1.088-.79l.72-4.194L.818 6.374a.75.75 0 0 1 .416-1.28l4.21-.611L7.327.668A.75.75 0 0 1 8 .25Z';

const StarIcon: React.FC<{size: number; filled: boolean}> = ({size, filled}) => (
	<svg width={size} height={size} viewBox="0 0 16 16" style={{display: 'block', overflow: 'visible'}}>
		<path d={STAR_PATH} fill={filled ? GOLD : 'none'} stroke={filled ? GOLD : '#9198a1'} strokeWidth={filled ? 0 : 1.4} strokeLinejoin="round" />
	</svg>
);

/** Four-point twinkle. */
const Sparkle: React.FC<{size: number; color: string}> = ({size, color: c}) => (
	<svg width={size} height={size} viewBox="-10 -10 20 20" style={{display: 'block'}}>
		<path d="M0 -10 C1 -2 2 -1 10 0 C2 1 1 2 0 10 C-1 2 -2 1 -10 0 C-2 -1 -1 -2 0 -10 Z" fill={c} />
	</svg>
);

/** Particles, shockwave rings and flash, drawn around the star's centre (0,0); `t` = frames since the click. */
const Burst: React.FC<{t: number}> = ({t}) => {
	if (t < 0) return null;
	const N = 34;
	const parts = Array.from({length: N}, (_, i) => {
		const a = (i / N) * Math.PI * 2 + (random(`a${i}`) - 0.5) * 0.5;
		const v = 13 + random(`v${i}`) * 20;
		const life = 20 + random(`l${i}`) * 26;
		if (t > life) return null;
		const drag = 0.88;
		const d = (v * (1 - Math.pow(drag, t))) / (1 - drag);
		const x = Math.cos(a) * d;
		const y = Math.sin(a) * d + 0.12 * t * t;
		const k = 1 - t / life;
		const size = (5 + random(`s${i}`) * 11) * (0.4 + 0.6 * k);
		const c = i % 3 === 0 ? '#fff6d8' : i % 3 === 1 ? '#ffd76a' : GOLD;
		const glyph = i % 5 === 0;
		return (
			<div
				key={i}
				style={{
					position: 'absolute',
					left: x,
					top: y,
					transform: `translate(-50%,-50%) rotate(${t * 14 * (random(`r${i}`) - 0.5)}deg)`,
					opacity: Math.min(1, k * 1.6),
					filter: `drop-shadow(0 0 ${size * 0.8}px ${c})`,
				}}
			>
				{glyph ? (
					<svg width={size * 2.2} height={size * 2.2} viewBox="0 0 16 16" style={{display: 'block'}}>
						<path d={STAR_PATH} fill={c} />
					</svg>
				) : (
					<div style={{width: size, height: size, borderRadius: '50%', background: c}} />
				)}
			</div>
		);
	});
	const ring = (delay: number, max: number, w: number) => {
		const p = ramp(t, delay, delay + 22, easeOut);
		if (p <= 0 || p >= 1) return null;
		const r = max * p;
		return (
			<div
				style={{
					position: 'absolute',
					left: -r,
					top: -r,
					width: 2 * r,
					height: 2 * r,
					borderRadius: '50%',
					border: `${w * (1 - p)}px solid ${GOLD}`,
					opacity: 1 - p,
					boxShadow: `0 0 ${30 * (1 - p)}px ${GOLD}`,
				}}
			/>
		);
	};
	const flash = Math.max(0, 1 - t / 12);
	return (
		<div style={{position: 'absolute', left: '50%', top: '50%', width: 0, height: 0, pointerEvents: 'none'}}>
			<div
				style={{
					position: 'absolute',
					left: -700,
					top: -700,
					width: 1400,
					height: 1400,
					borderRadius: '50%',
					background: 'radial-gradient(circle, rgba(255,215,106,0.55) 0%, rgba(227,179,65,0.18) 25%, rgba(227,179,65,0) 60%)',
					opacity: flash,
				}}
			/>
			{ring(0, 380, 12)}
			{ring(5, 240, 7)}
			{parts}
		</div>
	);
};

/** Sparkles around the pill after the burst: [x, y, delay after the click, size]. */
const SPARKLES = [
	[560, 360, 6, 46],
	[1380, 380, 12, 38],
	[700, 590, 18, 30],
	[1460, 560, 9, 42],
	[1040, 330, 22, 26],
	[1200, 640, 15, 34],
];

/** A generic repo pill; the cursor glides in, hovers, presses Star; the star spins up gold with a burst. No count, no logo. */
export const StarShot: React.FC = () => {
	const frame = useCurrentFrame();
	const {fps} = useVideoConfig();
	const CLICK = 52;
	const t = frame - CLICK;
	const starred = t >= 0;

	const pill = spring({frame: frame - 2, fps, config: {damping: 200}, durationInFrames: 18});

	// Cursor: curved glide that decelerates onto the button, small hover settle, then drifts off after the click.
	const target = {x: 1252, y: 494};
	const glide = ramp(frame, 10, CLICK - 12, easeOut);
	const from = {x: 1720, y: 1010};
	const ctrl = {x: 1640, y: 560};
	const q = (a: number, b: number, c: number) => (1 - glide) * (1 - glide) * a + 2 * (1 - glide) * glide * b + glide * glide * c;
	const settle = Math.sin(ramp(frame, CLICK - 14, CLICK - 4) * Math.PI) * 6;
	const leave = ramp(frame, CLICK + 16, CLICK + 40);
	const cursor = {x: q(from.x, ctrl.x, target.x) + settle + 70 * leave, y: q(from.y, ctrl.y, target.y) + settle * 0.5 + 90 * leave};
	const hover = ramp(frame, CLICK - 12, CLICK - 6);

	// Press: squash down into the click, spring back past rest on release.
	const down = ramp(frame, CLICK - 5, CLICK, easeOut);
	const up = spring({frame: t, fps, config: {damping: 9, stiffness: 320, mass: 0.6}});
	const btnScale = starred ? 0.86 + 0.14 * up : 1 - 0.14 * down;
	const cursorScale = starred ? 0.78 + 0.22 * up : 1 - 0.22 * down;

	// Star: spins in from small, overshoots big, keeps a soft glow.
	const s = spring({frame: t, fps, config: {damping: 7, stiffness: 170, mass: 0.7}});
	const kick = starred ? Math.exp(-t / 7) : 0;
	const starScale = starred ? 0.3 + 0.7 * s + 0.9 * kick : 1;
	const starRot = starred ? (1 - s) * -288 : 0;
	const glow = starred ? 0.35 + 0.65 * Math.exp(-t / 14) : 0;

	// Camera: a short punch-in and shake on the click.
	const punch = 1 + 0.045 * kick;
	const shake = t >= 0 && t < 8 ? kick * 9 : 0;
	const sx = (random(`sx${frame}`) - 0.5) * shake;
	const sy = (random(`sy${frame}`) - 0.5) * shake;

	// Sparkles that twinkle around the pill after the burst.
	const sparkles = SPARKLES.map(([x, y, d, sz], i) => {
		const p = ramp(t, d, d + 22, (v) => v);
		if (!starred || p <= 0 || p >= 1) return null;
		const tw = Math.sin(p * Math.PI);
		return (
			<div key={i} style={{position: 'absolute', left: x, top: y, transform: `translate(-50%,-50%) scale(${tw}) rotate(${p * 90}deg)`, opacity: tw, filter: `drop-shadow(0 0 10px ${GOLD})`}}>
				<Sparkle size={sz} color={i % 2 ? '#fff6d8' : '#ffd76a'} />
			</div>
		);
	});

	// Sound: whoosh on the glide, click on the press, impact and chime on the star, a ping per sparkle.
	const sfx = (name: string, from: number, volume: number) => (
		<Sequence key={`${name}${from}`} from={from} layout="none">
			<Audio src={staticFile(`assets/sfx/${name}.wav`)} volume={volume} />
		</Sequence>
	);
	const sound = [
		sfx('whoosh', 8, 0.35),
		sfx('click', CLICK - 3, 0.8),
		sfx('impact', CLICK, 0.7),
		sfx('chime', CLICK, 0.6),
		...SPARKLES.map(([, , d], i) => sfx('twinkle', CLICK + d + 6, 0.18 + 0.06 * (i % 2))),
	];

	// Caption comes in late, once the burst has settled.
	const cap = ramp(frame, CLICK + 52, CLICK + 76, easeOut);

	return (
		<AbsoluteFill style={{fontFamily: font.sans, background: '#030405'}}>
			{sound}
			<AbsoluteFill style={{transform: `translate(${sx}px, ${sy}px) scale(${punch})`, transformOrigin: `${target.x}px ${target.y}px`}}>
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
						border: `2px solid ${starred ? `rgba(227,179,65,${0.25 + 0.5 * glow})` : '#30363d'}`,
						boxShadow: starred ? `0 0 ${80 * glow}px rgba(227,179,65,${0.35 * glow})` : 'none',
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
							border: `2px solid ${starred ? 'rgba(227,179,65,0.55)' : interpolateColors(hover, [0, 1], ['#3d444d', '#8b949e'])}`,
							background: down > 0.5 && !starred ? '#30363d' : starred ? '#2a2414' : interpolateColors(hover, [0, 1], ['#21262d', '#292e36']),
							fontSize: 38,
							fontWeight: 600,
							color: '#f0f6fc',
							transform: `scale(${btnScale})`,
						}}
					>
						<div style={{position: 'relative', width: 38, height: 38}}>
							<div
								style={{
									position: 'absolute',
									inset: 0,
									transform: `scale(${starScale}) rotate(${starRot}deg)`,
									filter: starred ? `drop-shadow(0 0 ${6 + 22 * glow}px rgba(255,215,106,${0.5 + 0.5 * glow}))` : 'none',
								}}
							>
								<StarIcon size={38} filled={starred} />
							</div>
							<Burst t={t} />
						</div>
						{starred ? 'Starred' : 'Star'}
					</div>
				</div>
				{sparkles}
			</AbsoluteFill>
			<div
				style={{
					position: 'absolute',
					left: cursor.x,
					top: cursor.y,
					transform: `scale(${cursorScale})`,
					transformOrigin: '0 0',
					opacity: 1 - leave,
					filter: 'drop-shadow(0 6px 10px rgba(0,0,0,0.6))',
				}}
			>
				<Cursor />
			</div>
			<div
				style={{
					position: 'absolute',
					left: 0,
					right: 0,
					top: 640,
					textAlign: 'center',
					fontSize: 48,
					color: color.text,
					opacity: cap,
					transform: `translateY(${18 * (1 - cap)}px)`,
					filter: `blur(${6 * (1 - cap)}px)`,
				}}
			>
				{star.caption}
			</div>
		</AbsoluteFill>
	);
};
