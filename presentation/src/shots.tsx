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

/** "Introducing RCAgent": the product's name, right after the scale of the problem. */
export const IntroducingShot: React.FC<{done?: boolean}> = ({done}) => {
	const frame = useCurrentFrame();
	const {fps} = useVideoConfig();
	const k = done ? 1 : ramp(frame, 2, 14);
	const n = done ? 1 : spring({frame: frame - 10, fps, config: {damping: 200}, durationInFrames: 22});
	return (
		<AbsoluteFill style={{justifyContent: 'center', alignItems: 'center', fontFamily: font.sans}}>
			<div style={{fontSize: 32, letterSpacing: '0.3em', textTransform: 'uppercase', color: color.muted, fontWeight: 600, opacity: k}}>{reveal.introducing.kicker}</div>
			<div style={{fontSize: 140, fontWeight: 800, letterSpacing: -3, lineHeight: 1, color: color.accent, marginTop: 20, opacity: n, transform: `scale(${0.94 + 0.06 * n})`}}>
				{reveal.introducing.name}
			</div>
		</AbsoluteFill>
	);
};

/** Templating: SereneDB regex masks the variable values, Drain3 merges the rest into a handful of templates; shown as one step. */
export const TemplatesShot: React.FC<{done?: boolean}> = ({done}) => {
	const frame = useCurrentFrame();
	const {fps} = useVideoConfig();
	const {raw, cards, title, poweredBy, headline, source} = reveal.templates;
	const mask = done ? 1 : ramp(frame, 26, 44);
	const fold = done ? 1 : ramp(frame, 56, 86, ease);
	const big = done ? 1 : spring({frame: frame - 96, fps, config: {damping: 200}, durationInFrames: 20});
	const LX = 130;
	const RX = 1090;
	const top = 250;
	const cardY = (t: number) => top + 30 + t * 120;
	return (
		<AbsoluteFill style={{fontFamily: font.sans}}>
			<div style={{position: 'absolute', left: LX, top: 110, opacity: done ? 1 : ramp(frame, 0, 12)}}>
				<div style={{fontSize: 56, fontWeight: 800, color: color.text}}>{title}</div>
				<div style={{display: 'flex', alignItems: 'center', gap: 14, marginTop: 16, fontSize: 26, color: color.muted}}>
					powered by
					{poweredBy.map((p) => (
						<span key={p} style={{padding: '6px 16px', borderRadius: 999, border: `2px solid ${color.line}`, color: color.text, fontWeight: 600}}>
							{p}
						</span>
					))}
				</div>
			</div>
			{raw.map((r, i) => {
				const y0 = top + i * 62;
				const y = y0 + (cardY(r.t) + 22 - y0) * fold;
				const x = LX + (RX + 24 - LX) * fold;
				const appear = done ? 1 : ramp(frame, i * 3, i * 3 + 10);
				return (
					<div key={i} style={{position: 'absolute', left: x, top: y, whiteSpace: 'pre', fontFamily: font.mono, fontSize: 30, color: mask > 0.5 && r.line !== r.masked ? color.accent : '#c9d1d9', opacity: appear * (1 - fold)}}>
						{mask > 0.5 ? r.masked : r.line}
					</div>
				);
			})}
			{cards.map((c, t) => {
				const s = done ? 1 : spring({frame: frame - (70 + t * 6), fps, config: {damping: 200}, durationInFrames: 18});
				return (
					<div
						key={c.id}
						style={{
							position: 'absolute',
							left: RX,
							top: cardY(t),
							width: 700,
							height: 96,
							boxSizing: 'border-box',
							padding: '0 26px',
							display: 'flex',
							alignItems: 'center',
							gap: 20,
							borderRadius: 16,
							border: `2px solid ${t === 0 ? color.accent : color.line}`,
							background: t === 0 ? '#2a2215' : color.panel,
							opacity: s,
							transform: `scale(${0.9 + 0.1 * s})`,
						}}
					>
						<div style={{fontFamily: font.mono, fontSize: 24, color: color.muted, width: 60}}>{c.id}</div>
						<div style={{flex: 1, fontFamily: font.mono, fontSize: 26, color: color.text}}>{c.text}</div>
					</div>
				);
			})}
			<div style={{position: 'absolute', left: LX, top: top + 120, opacity: big, transform: `translateY(${(1 - big) * 20}px)`}}>
				<div style={{fontSize: 76, fontWeight: 800, color: color.text, letterSpacing: -1, lineHeight: 1.1, width: 860}}>{headline}</div>
			</div>
			<div style={{position: 'absolute', left: LX, bottom: 120, fontFamily: font.mono, fontSize: 24, color: color.muted, opacity: done ? 1 : ramp(frame, 70, 84)}}>
				{source}
			</div>
		</AbsoluteFill>
	);
};

// The README "How it works" diagram (docs/img/flow.svg on main), redrawn in its dark-mode colours and built step by step.
// Colours from the theme: flat panels with the line border, gold only for the evidence path, on the warm dark fill.
const FD = {fg: color.text, mut: color.muted, ln: color.text, box: color.panel, boxLine: color.line, ev: color.accent, evt: color.accent, evBox: '#2a2215', evBoxLine: color.accent};
const FD_BOXES = [
	{x: 20, name: 'You'},
	{x: 340, name: 'Claude'},
	{x: 660, name: 'MCP tools'},
	{x: 980, name: 'SereneDB'},
];
const FD_REQUEST = [
	{x1: 200, x2: 336, label: 'question'},
	{x1: 520, x2: 656, label: 'tool call'},
	{x1: 840, x2: 976, label: 'SQL'},
];
const FD_ANSWER = [
	{x1: 980, x2: 844, label: '', id: ''},
	{x1: 660, x2: 524, label: '', id: 'Q46'},
	{x1: 340, x2: 204, label: '', id: '[Q46]'},
];

export const FlowDiagramShot: React.FC<{done?: boolean}> = ({done}) => {
	const frame = useCurrentFrame();
	const {fps} = useVideoConfig();
	const pop = (at: number) => (done ? 1 : spring({frame: frame - at, fps, config: {damping: 200}, durationInFrames: 16}));
	const draw = (at: number, len = 14) => (done ? 1 : ramp(frame, at, at + len));
	// request: boxes and arrows left to right, then the answer comes back right to left, then the evidence
	const boxAt = (i: number) => 6 + i * 22;
	const reqAt = (i: number) => boxAt(i) + 12;
	// the Templating box pops above MCP tools once the tool call has arrived there
	const tmplAt = reqAt(2) + 14;
	const ansAt = (i: number) => tmplAt + 30 + i * 18;
	const saveAt = ansAt(2) + 22;
	const checkAt = saveAt + 26;
	const scale = 1760 / 1180;
	const mono = font.mono;
	return (
		<AbsoluteFill style={{justifyContent: 'center', alignItems: 'center'}}>
			<svg viewBox="0 -80 1180 410" width={1180 * scale} height={410 * scale} style={{fontFamily: font.sans, overflow: 'visible', marginTop: -70}}>
				<defs>
					<marker id="fd-ah" viewBox="0 0 10 10" refX="10" refY="5" markerWidth="8" markerHeight="8" orient="auto">
						<path d="M0 1 L10 5 L0 9 z" fill={FD.ln} />
					</marker>
					<marker id="fd-ahe" viewBox="0 0 10 10" refX="10" refY="5" markerWidth="8" markerHeight="8" orient="auto">
						<path d="M0 1 L10 5 L0 9 z" fill={FD.ev} />
					</marker>
				</defs>
				{FD_BOXES.map((b, i) => {
					const s = pop(boxAt(i));
					return (
						<g key={b.name} opacity={s} transform={`translate(${b.x + 90} 88) scale(${0.85 + 0.15 * s}) translate(${-b.x - 90} -88)`}>
							<rect x={b.x} y={40} width={180} height={96} rx={10} fill={FD.box} stroke={FD.boxLine} strokeWidth={1.4} />
							<text x={b.x + 90} y={95} textAnchor="middle" fill={FD.fg} fontSize={22} fontWeight={700}>
								{b.name}
							</text>
						</g>
					);
				})}
				{FD_REQUEST.map((r, i) => {
					const d = draw(reqAt(i));
					return (
						<g key={r.label} opacity={d > 0 ? 1 : 0}>
							<line x1={r.x1} y1={70} x2={r.x1 + (r.x2 - r.x1) * d} y2={70} stroke={FD.ln} strokeWidth={1.8} markerEnd={d > 0.95 ? 'url(#fd-ah)' : undefined} />
							<text x={(r.x1 + r.x2) / 2} y={58} textAnchor="middle" fill={FD.fg} fontSize={16} opacity={d}>
								{r.label}
							</text>
						</g>
					);
				})}
				{FD_ANSWER.map((r, i) => {
					const d = draw(ansAt(i));
					return (
						<g key={r.label} opacity={d > 0 ? 1 : 0}>
							<line x1={r.x1} y1={110} x2={r.x1 + (r.x2 - r.x1) * d} y2={110} stroke={FD.ev} strokeWidth={2.2} markerEnd={d > 0.95 ? 'url(#fd-ahe)' : undefined} />
							<text x={(r.x1 + r.x2) / 2} y={132} textAnchor="middle" fill={FD.evt} fontSize={16} fontWeight={700} opacity={d}>
								{r.label}
								{r.id ? (
									<tspan fontFamily={mono} fontWeight={700}>
										{r.id}
									</tspan>
								) : null}
							</text>
						</g>
					);
				})}
				{/* templating (Drain3 + SereneDB regex) sits with the MCP tools */}
				<g opacity={pop(tmplAt)}>
					<line x1={750} y1={40} x2={750} y2={-14} stroke={FD.boxLine} strokeWidth={1.8} strokeDasharray="5 4" />
					<rect x={660} y={-66} width={180} height={52} rx={8} fill={FD.box} stroke={FD.boxLine} strokeWidth={1.4} />
					<text x={750} y={-33} textAnchor="middle" fill={FD.fg} fontSize={20} fontWeight={700}>
						Templating
					</text>
				</g>
				{/* every query is saved as evidence */}
				<g opacity={draw(saveAt) > 0 ? 1 : 0}>
					<line x1={750} y1={136} x2={750} y2={136 + 80 * draw(saveAt)} stroke={FD.ev} strokeWidth={1.8} strokeDasharray="5 4" markerEnd={draw(saveAt) > 0.95 ? 'url(#fd-ahe)' : undefined} />

				</g>
				<g opacity={pop(saveAt + 10)}>
					<rect x={560} y={220} width={380} height={76} rx={10} fill={FD.evBox} stroke={FD.evBoxLine} strokeWidth={1.4} />
					<text x={750} y={265} textAnchor="middle" fill={FD.fg} fontSize={20} fontWeight={700}>
						Evidence <tspan fontFamily={mono}>Q46</tspan>
					</text>
				</g>
				{/* and you can check any number */}
				<g opacity={draw(checkAt, 20) > 0 ? 1 : 0}>
					<path
						d="M110 136 V258 H556"
						fill="none"
						stroke={FD.ev}
						strokeWidth={1.8}
						strokeDasharray="5 4"
						pathLength={1}
						style={{clipPath: `inset(0 ${(1 - draw(checkAt, 20)) * 100}% 0 0)`}}
						markerEnd={draw(checkAt, 20) > 0.95 ? 'url(#fd-ahe)' : undefined}
					/>
					<text x={128} y={248} fill={FD.evt} fontSize={16} opacity={draw(checkAt + 10)}>
						<tspan fontFamily={mono}>show_evidence</tspan>
					</text>
				</g>
			</svg>
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
