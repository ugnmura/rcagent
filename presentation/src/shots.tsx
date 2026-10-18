// One idea per shot. Every shot reads its local frame; `done` draws the final, fully built state (used by the
// slides PDF, which renders each page from that final frame).
import React from 'react';
import {AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig} from 'remotion';
import {coldOpen, engineer, reveal} from './content';
import {ease, easeOut, ramp, Typewriter} from './film';
import {color, font} from './theme';

const num = (s: string) => Number(s.replace(/[^0-9.]/g, ''));
const fmtInt = (n: number) => Math.round(n).toLocaleString('en-US');
export const RED = '#ff4b4b';

// ------------------------------------------------------------------ cold open

const mixHex = (a: string, b: string, t: number) => {
	const p = (h: string) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
	const [x, y] = [p(a), p(b)];
	return `rgb(${x.map((v, i) => Math.round(v + (y[i] - v) * t)).join(',')})`;
};

const logLine = (i: number) => {
	const {node, level, component, quoted, runMessage} = coldOpen.log;
	const q = quoted[i];
	const ts = q ? q.ts : ' '.repeat(quoted[0].ts.length);
	return `${ts}  ${node}  ${level}  ${component}  ${q ? q.message : runMessage}`;
};

/** Real BGL lines scrolling upward, faster and faster, blurred and dim; they turn red as the storm builds. */
export const LogStorm: React.FC<{frames: number}> = ({frames}) => {
	const frame = useCurrentFrame();
	const {fps} = useVideoConfig();
	const T = frames / fps;
	const t = frame / fps;
	// Speed grows exponentially from 1.5 to 60 lines per second over the scene.
	const k = Math.log(40) / T;
	const c = 1.5 / k;
	const scrolled = c * (Math.exp(k * t) - 1);
	const speed = c * k * Math.exp(k * t);
	const LINE = 38;
	const startY = 760;
	const first = Math.max(0, Math.floor(scrolled - startY / LINE) - 1);
	const last = Math.floor(scrolled + (1080 - startY) / LINE) + 1;
	const red = ramp(frame, frames * 0.22, frames * 0.7);
	const rows: React.ReactNode[] = [];
	for (let i = first; i <= last; i++) {
		const y = startY + (i - scrolled) * LINE;
		if (y < -LINE || y > 1080) {
			continue;
		}
		const cause = i === 0;
		rows.push(
			<div
				key={i}
				style={{
					position: 'absolute',
					left: 300,
					top: y,
					whiteSpace: 'pre',
					color: cause ? color.accent : mixHex('#8b949e', RED, red),
				}}
			>
				{logLine(i)}
			</div>,
		);
	}
	return (
		<AbsoluteFill
			style={{
				fontFamily: font.mono,
				fontSize: 24,
				opacity: interpolate(red, [0, 1], [0.34, 0.8]),
				filter: `blur(${(1.2 + Math.min(2.4, speed / 25)).toFixed(2)}px)`,
			}}
		>
			{rows}
		</AbsoluteFill>
	);
};

/** The three caption lines, each typed on. */
export const TitleCaption: React.FC<{done?: boolean; starts?: [number, number, number]; scale?: number}> = ({
	done,
	starts = [15, 72, 112],
	scale = 1,
}) => {
	const [l1, l2, l3] = coldOpen.captionLines;
	return (
		<div style={{fontFamily: font.sans, color: color.text, display: 'flex', flexDirection: 'column', gap: 18 * scale}}>
			<Typewriter
				text={l1.toUpperCase()}
				start={starts[0]}
				cps={30}
				done={done}
				style={{fontSize: 30 * scale, letterSpacing: '0.24em', color: '#c9d1d9', fontWeight: 600}}
			/>
			<Typewriter text={l2} start={starts[1]} cps={12} done={done} style={{fontSize: 136 * scale, fontWeight: 800, letterSpacing: -2, lineHeight: 1}} />
			<Typewriter
				text={l3}
				start={starts[2]}
				cps={22}
				done={done}
				style={{fontSize: 44 * scale, fontFamily: font.mono, color: color.accent}}
			/>
		</div>
	);
};

// ------------------------------------------------------------------ reveal

/** 0 → 152,229, eased; then the words fade in under it. */
export const CounterShot: React.FC<{done?: boolean}> = ({done}) => {
	const frame = useCurrentFrame();
	const target = num(reveal.counter.value);
	const p = done ? 1 : ramp(frame, 6, 84, easeOut);
	const words = done ? 1 : ramp(frame, 88, 112);
	return (
		<AbsoluteFill style={{justifyContent: 'center', alignItems: 'center', fontFamily: font.sans}}>
			<div
				style={{
					fontSize: 240,
					fontWeight: 800,
					color: color.accent,
					letterSpacing: -6,
					fontVariantNumeric: 'tabular-nums',
					lineHeight: 1,
				}}
			>
				{fmtInt(target * p)}
			</div>
			<div
				style={{
					fontSize: 52,
					color: color.text,
					marginTop: 34,
					opacity: words,
					transform: `translateY(${(1 - words) * 16}px)`,
					letterSpacing: '0.02em',
				}}
			>
				{reveal.counter.label}
			</div>
		</AbsoluteFill>
	);
};

/** One big number: 4.7 million log lines. */
export const FactShot: React.FC<{done?: boolean}> = ({done}) => {
	const frame = useCurrentFrame();
	const {fps} = useVideoConfig();
	const s = done ? 1 : spring({frame, fps, config: {damping: 200}, durationInFrames: 24});
	const words = done ? 1 : ramp(frame, 18, 36);
	return (
		<AbsoluteFill style={{justifyContent: 'center', alignItems: 'center', fontFamily: font.sans}}>
			<div style={{fontSize: 220, fontWeight: 800, color: color.text, letterSpacing: -5, lineHeight: 1, opacity: s, transform: `scale(${0.94 + 0.06 * s})`}}>
				{reveal.fact.value}
			</div>
			<div style={{fontSize: 52, color: color.muted, marginTop: 34, opacity: words}}>{reveal.fact.label}</div>
		</AbsoluteFill>
	);
};

const FLOW_W = 300;
const FLOW_GAP = 44;
const FLOW_H = 150;

/** Question → … → Answer, drawn left to right, one node at a time. */
export const FlowShot: React.FC<{done?: boolean; y?: number; scale?: number}> = ({done, y = 540, scale = 1}) => {
	const frame = useCurrentFrame();
	const {fps} = useVideoConfig();
	const steps = reveal.flow;
	const total = steps.length * FLOW_W + (steps.length - 1) * FLOW_GAP;
	const x0 = (1920 - total * scale) / 2;
	const cx = (i: number) => x0 + (FLOW_W / 2 + i * (FLOW_W + FLOW_GAP)) * scale;
	const arrive = (i: number) => 12 + i * 32;
	// The line runs from node 0's centre and reaches node i's centre at arrive(i).
	let lineTo = cx(0);
	for (let i = 1; i < steps.length; i++) {
		const p = done ? 1 : ramp(frame, arrive(i) - 20, arrive(i), ease);
		lineTo = p > 0 ? cx(i - 1) + (cx(i) - cx(i - 1)) * p : lineTo;
	}
	return (
		<AbsoluteFill style={{fontFamily: font.sans}}>
			<svg width={1920} height={1080} style={{position: 'absolute', inset: 0}}>
				<line x1={cx(0)} y1={y} x2={lineTo} y2={y} stroke={color.line} strokeWidth={4 * scale} />
			</svg>
			{steps.map((step, i) => {
				const s = done ? 1 : spring({frame: frame - (arrive(i) - 6), fps, config: {damping: 14, stiffness: 160, mass: 0.6}});
				const ours = i === 2;
				return (
					<div
						key={step}
						style={{
							position: 'absolute',
							left: cx(i) - (FLOW_W * scale) / 2,
							top: y - (FLOW_H * scale) / 2,
							width: FLOW_W * scale,
							height: FLOW_H * scale,
							boxSizing: 'border-box',
							display: 'flex',
							alignItems: 'center',
							justifyContent: 'center',
							textAlign: 'center',
							padding: `0 ${18 * scale}px`,
							borderRadius: 20 * scale,
							border: `${3 * scale}px solid ${ours ? color.accent : color.line}`,
							background: ours ? '#2a2215' : color.panel,
							color: color.text,
							fontSize: 32 * scale,
							fontWeight: 600,
							lineHeight: 1.2,
							opacity: Math.min(1, s * 1.5),
							transform: `scale(${0.7 + 0.3 * s})`,
							boxShadow: ours ? `0 0 ${40 * s}px rgba(245,165,36,0.25)` : undefined,
						}}
					>
						{step}
					</div>
				);
			})}
		</AbsoluteFill>
	);
};

// ------------------------------------------------------------------ engineer

/** The node name types in. */
export const NodeShot: React.FC = () => {
	const frame = useCurrentFrame();
	const label = ramp(frame, 0, 14);
	return (
		<AbsoluteFill style={{justifyContent: 'center', alignItems: 'center', fontFamily: font.sans}}>
			<div style={{fontSize: 30, letterSpacing: '0.3em', color: color.muted, opacity: label, marginBottom: 36}}>ONE NODE</div>
			<Typewriter text={engineer.node} start={14} cps={16} style={{fontFamily: font.mono, fontSize: 112, fontWeight: 600, color: color.text}} />
		</AbsoluteFill>
	);
};

/** Arc of `fraction` (0..1) on a ring, starting at 12 o'clock. */
export const Ring: React.FC<{fraction: number; r: number; stroke: number; label: string; labelSize: number}> = ({
	fraction,
	r,
	stroke,
	label,
	labelSize,
}) => {
	const c = 2 * Math.PI * r;
	const size = 2 * r + stroke * 2;
	return (
		<div style={{position: 'relative', width: size, height: size}}>
			<svg width={size} height={size} style={{transform: 'rotate(-90deg)'}}>
				<circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="#222a33" strokeWidth={stroke} />
				<circle
					cx={size / 2}
					cy={size / 2}
					r={r}
					fill="none"
					stroke={color.accent}
					strokeWidth={stroke}
					strokeLinecap="round"
					strokeDasharray={`${c * fraction} ${c}`}
				/>
			</svg>
			<div
				style={{
					position: 'absolute',
					inset: 0,
					display: 'flex',
					alignItems: 'center',
					justifyContent: 'center',
					fontFamily: font.sans,
					fontSize: labelSize,
					fontWeight: 800,
					color: color.text,
					fontVariantNumeric: 'tabular-nums',
				}}
			>
				{label}
			</div>
		</div>
	);
};

/** 152,229 / 855,501 rises, then becomes a ring that fills to 17.8%. */
export const RingShot: React.FC = () => {
	const frame = useCurrentFrame();
	const {fps} = useVideoConfig();
	const intro = ramp(frame, 0, 14);
	const lift = spring({frame: frame - 34, fps, config: {damping: 200}, durationInFrames: 26});
	const ringIn = spring({frame: frame - 40, fps, config: {damping: 200}, durationInFrames: 24});
	const fill = ramp(frame, 46, 100, ease);
	const pct = num(engineer.share.pct);
	const label = ramp(frame, 96, 114);
	return (
		<AbsoluteFill style={{fontFamily: font.sans, alignItems: 'center'}}>
			<div
				style={{
					position: 'absolute',
					top: interpolate(lift, [0, 1], [440, 150]),
					fontSize: interpolate(lift, [0, 1], [120, 56]),
					fontWeight: 800,
					opacity: intro,
					fontVariantNumeric: 'tabular-nums',
					color: color.text,
					whiteSpace: 'pre',
				}}
			>
				{engineer.share.part}
				<span style={{color: color.muted, fontWeight: 400}}> / {engineer.share.whole}</span>
			</div>
			<div style={{position: 'absolute', top: 270, opacity: ringIn, transform: `scale(${0.85 + 0.15 * ringIn})`}}>
				<Ring fraction={(pct / 100) * fill} r={230} stroke={30} label={`${(pct * fill).toFixed(1)}%`} labelSize={120} />
			</div>
			<div style={{position: 'absolute', top: 820, fontSize: 40, color: color.muted, opacity: label}}>of all fatal entries</div>
		</AbsoluteFill>
	);
};

/** One L2 line at 17:17:44, then a wall of data TLB errors floods in. */
export const FloodShot: React.FC<{frames: number}> = ({frames}) => {
	const frame = useCurrentFrame();
	const {fps} = useVideoConfig();
	const head = ramp(frame, 0, 12);
	const floodStart = 40;
	const t = Math.max(0, (frame - floodStart) / fps);
	// Rows arrive faster and faster: 3 per second at first, about 80 per second at the end.
	const T = Math.max(1, (frames - floodStart) / fps);
	const k = Math.log(26) / T;
	const n = frame < floodStart ? 0 : Math.floor((3 / k) * (Math.exp(k * t) - 1)) + 1;
	// A two-column wall that fills row by row, then keeps scrolling up.
	const ROW = 40;
	const COLS = [320, 800];
	const top = 380;
	const visibleRows = Math.floor((1080 - top) / ROW);
	const filledRows = Math.ceil(n / COLS.length);
	const scroll = Math.max(0, filledRows - visibleRows);
	const window = ramp(frame, frames * 0.62, frames * 0.62 + 18);
	const rows: React.ReactNode[] = [];
	for (let i = scroll * COLS.length; i < n; i++) {
		const row = Math.floor(i / COLS.length) - scroll;
		const newest = n - i <= COLS.length;
		rows.push(
			<div
				key={i}
				style={{
					position: 'absolute',
					left: COLS[i % COLS.length],
					top: top + row * ROW,
					whiteSpace: 'pre',
					color: newest ? '#ffd6d6' : RED,
				}}
			>
				{engineer.message}
			</div>,
		);
	}
	return (
		<AbsoluteFill style={{fontFamily: font.sans}}>
			<div style={{position: 'absolute', left: 270, top: 200, bottom: 0, width: 3, background: color.line, opacity: head}} />
			<div style={{position: 'absolute', left: 258, top: 245, width: 27, height: 27, borderRadius: '50%', background: color.accent, opacity: head}} />
			<div style={{position: 'absolute', left: 60, top: 236, width: 180, textAlign: 'right', fontFamily: font.mono, fontSize: 32, color: color.muted, opacity: head}}>
				{engineer.beforeLine.time}
			</div>
			<div style={{position: 'absolute', left: 330, top: 220, fontSize: 68, fontWeight: 800, color: color.accent, opacity: head}}>
				{engineer.beforeLine.text}
			</div>
			<AbsoluteFill
				style={{
					fontFamily: font.mono,
					fontSize: 30,
					opacity: 1 - 0.55 * window,
					maskImage: 'linear-gradient(to bottom, black 70%, transparent 100%)',
					WebkitMaskImage: 'linear-gradient(to bottom, black 70%, transparent 100%)',
				}}
			>
				{rows}
			</AbsoluteFill>
			<div
				style={{
					position: 'absolute',
					right: 70,
					top: 470,
					textAlign: 'right',
					opacity: window,
					transform: `translateY(${(1 - window) * 14}px)`,
					background: 'rgba(3,4,5,0.92)',
					padding: '24px 36px',
					borderRadius: 16,
				}}
			>
				<div style={{fontSize: 30, letterSpacing: '0.24em', color: color.muted}}>NON-STOP</div>
				<div style={{fontSize: 80, fontWeight: 800, color: color.text, fontVariantNumeric: 'tabular-nums'}}>
					{engineer.runTimes.from} – {engineer.runTimes.to}
				</div>
			</div>
		</AbsoluteFill>
	);
};
