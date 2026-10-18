// Scene 3 benchmarks, calm enough to talk over: long shots with plain fades and no sound effects. Simple style: flat
// bars on the dark background, gold only for ours, per shot one short label plus the numbers. First the score of each
// step; then its cost; then the RCAEval root-cause result. Numbers come only from public/assets/benchmarks.json.
import React from 'react';
import {AbsoluteFill, useCurrentFrame} from 'remotion';
import type {Benchmarks, Design} from './benchmarks';
import {benchmarks as benchContent} from './content';
import {ease, ramp} from './film';
import {color, font} from './theme';

/** Bottom of the score axis (percent). Both ends are labelled, so the zoom stays honest. */
const AXIS_MIN = 80;
const BAR_GREY = '#3b4450';

const COL_W = 500;
const COL_GAP = 70;
const COL_LEFT = (1920 - 3 * COL_W - 2 * COL_GAP) / 2;
/** Bars stand on BASE; the tallest possible bar (100 %, or the top cost) reaches BASE - BAR_MAX. */
const BASE = 790;
const BAR_MAX = 360;
const BAR_W = 200;
const colX = (k: number) => COL_LEFT + k * (COL_W + COL_GAP);
/** Frames for a fade, and for a bar to rise. */
const FADE = 15;
const GROW = 24;

/**
 * Deni's take s6-benchmarks.mp4 (43.0 s), timed from its transcript. Shot lengths in seconds, usable directly as
 * ShotRun weights: steps 0 to 26.0 s (through "Then we added Drain3"), cost 26.0 to 33.4 s ("about 4 times cheaper"),
 * RCAEval from 33.4 s ("And it's not only logs") to the end.
 */
export const BENCH_TAKE_SECONDS = 43.035;
export const BENCH_SHOT_SECONDS = {steps: 26.0, cost: 7.4, rca: BENCH_TAKE_SECONDS - 33.4};
/** When each step's column comes in, seconds into the steps shot: 7 tools, 18 tools, Drain3. */
const STEP_AT_SECONDS = [5.0, 12.8, 20.4];

const pct = (v: number) => `${v.toFixed(1)}%`;
const usd = (v: number) => `$${v.toFixed(2)}`;

/** Pink corner tag while benchmarks.json is not final, so placeholder numbers never pass for real ones. */
export const PlaceholderTag: React.FC = () => (
	<div
		style={{
			position: 'absolute',
			top: 44,
			left: 48,
			fontFamily: font.sans,
			fontSize: 24,
			fontWeight: 800,
			letterSpacing: '0.12em',
			color: color.placeholder,
			border: `2px solid ${color.placeholder}`,
			borderRadius: 8,
			padding: '8px 14px',
			background: 'rgba(3,4,5,0.85)',
		}}
	>
		{benchContent.placeholder}
	</div>
);

/** Design name; gold for ours. */
export const DesignLabel: React.FC<{d: Design; width: number; size?: number}> = ({d, width, size = 44}) => (
	<div style={{width, textAlign: 'right', whiteSpace: 'nowrap', fontSize: size, fontWeight: d.ours ? 800 : 600, color: d.ours ? color.accent : color.text}}>{d.name}</div>
);

/** A flat bar on the shared baseline with its value above and the design name below; fades in, then the bar rises. */
const Column: React.FC<{d: Design; k: number; h: number; value: string; t: number; label?: string}> = ({d, k, h, value, t, label = d.name}) => {
	const grow = ramp(t, FADE, FADE + GROW, ease);
	return (
		<div style={{position: 'absolute', left: colX(k), top: 0, width: COL_W, height: 1080, opacity: ramp(t, 0, FADE)}}>
			<div
				style={{
					position: 'absolute',
					left: (COL_W - BAR_W) / 2,
					width: BAR_W,
					top: BASE - h * grow,
					height: h * grow,
					borderRadius: '10px 10px 0 0',
					background: d.ours ? color.accent : BAR_GREY,
				}}
			/>
			<div
				style={{
					position: 'absolute',
					width: '100%',
					top: BASE - h - 92,
					textAlign: 'center',
					fontSize: 72,
					fontWeight: 800,
					fontVariantNumeric: 'tabular-nums',
					color: d.ours ? color.accent : color.text,
					opacity: ramp(t, FADE + GROW - 6, FADE + GROW + 6),
				}}
			>
				{value}
			</div>
			<div style={{position: 'absolute', top: BASE + 20, width: '100%', textAlign: 'center', fontSize: 36, fontWeight: d.ours ? 800 : 600, color: d.ours ? color.accent : color.muted}}>
				{label}
			</div>
		</div>
	);
};

const Baseline: React.FC = () => (
	<div style={{position: 'absolute', left: COL_LEFT - 20, width: 3 * COL_W + 2 * COL_GAP + 40, top: BASE, borderTop: `2px solid ${color.line}`}} />
);

/** One short line across the bottom: the setup, or the closing caption. */
const Footer: React.FC<{opacity: number; size?: number; children: React.ReactNode}> = ({opacity, size = 36, children}) => (
	<div style={{position: 'absolute', top: 900, width: '100%', textAlign: 'center', fontSize: size, color: color.muted, opacity}}>{children}</div>
);

/** Small muted caps line at the top of a shot. */
const Title: React.FC<{opacity: number; children: React.ReactNode}> = ({opacity, children}) => (
	<div style={{position: 'absolute', top: 130, width: '100%', textAlign: 'center', fontSize: 34, fontWeight: 600, letterSpacing: '0.3em', color: color.muted, opacity}}>
		{children}
	</div>
);

// ------------------------------------------------------------------ shot 1: the steps, one column each

/** Columns come in one at a time as Deni names each step (STEP_AT_SECONDS); each stays on screen to the end of the shot. */
export const BenchStepsShot: React.FC<{frames: number; benchmarks: Benchmarks}> = ({frames, benchmarks: b}) => {
	const frame = useCurrentFrame();
	const ds = b.designs.slice(0, 3);
	const at = (v: number) => Math.max(0, Math.min(1, (v - AXIS_MIN) / (100 - AXIS_MIN)));
	const stepAt = (k: number) => Math.round((STEP_AT_SECONDS[k] / BENCH_SHOT_SECONDS.steps) * frames);
	const setup = [b.questions ? `${b.questions} ${benchContent.setup.questions}` : null, benchContent.setup.blind].filter(Boolean).join(' · ');
	return (
		<AbsoluteFill style={{fontFamily: font.sans}}>
			{b.final ? null : <PlaceholderTag />}
			<Title opacity={ramp(frame, 0, FADE)}>{benchContent.scoreTitle.toUpperCase()}</Title>
			<div style={{opacity: ramp(frame, 0, FADE)}}>
				<Baseline />
				<div style={{position: 'absolute', left: COL_LEFT - 20, width: 3 * COL_W + 2 * COL_GAP + 40, top: BASE - BAR_MAX, borderTop: `2px dashed ${color.line}`}} />
				<div style={{position: 'absolute', left: COL_LEFT - 110, top: BASE - 18, width: 80, textAlign: 'right', fontSize: 26, color: color.muted}}>{AXIS_MIN}%</div>
				<div style={{position: 'absolute', left: COL_LEFT - 110, top: BASE - BAR_MAX - 18, width: 80, textAlign: 'right', fontSize: 26, color: color.muted}}>100%</div>
			</div>
			{ds.map((d, k) => {
				const t = frame - stepAt(k);
				if (t < 0) return null;
				const v = d.score_pct ?? 0;
				return <Column key={d.name} d={d} k={k} h={at(v) * BAR_MAX} value={pct(v)} t={t} />;
			})}
			<Footer opacity={ramp(frame, 0, FADE)}>{setup}</Footer>
		</AbsoluteFill>
	);
};

// ------------------------------------------------------------------ shot 2: cost per answer

/** Cost bars start at zero, so their heights compare honestly; names go without the "(ours)" tag here. */
export const BenchCostShot: React.FC<{frames: number; benchmarks: Benchmarks}> = ({benchmarks: b}) => {
	const frame = useCurrentFrame();
	const ds = b.designs.slice(0, 3);
	const top = Math.max(...ds.map((x) => x.usd_per_answer ?? 0), 1e-9);
	return (
		<AbsoluteFill style={{fontFamily: font.sans}}>
			{b.final ? null : <PlaceholderTag />}
			<Title opacity={ramp(frame, 0, FADE)}>{benchContent.costTitle.toUpperCase()}</Title>
			<div style={{opacity: ramp(frame, 0, FADE)}}>
				<Baseline />
			</div>
			{ds.map((x, k) => {
				const t = frame - (6 + k * 12);
				const c = x.usd_per_answer ?? 0;
				return <Column key={x.name} d={x} k={k} h={(c / top) * BAR_MAX} value={usd(c)} t={t} label={x.short ?? x.name} />;
			})}
		</AbsoluteFill>
	);
};

// ------------------------------------------------------------------ shot 3: root cause on microservices (RCAEval)

/** Caps line with wide tracking: the shot's subtitle and the comparison's header. */
const Kicker: React.FC<{style?: React.CSSProperties; children: React.ReactNode}> = ({style, children}) => (
	<div style={{fontSize: 30, fontWeight: 700, letterSpacing: '0.3em', color: color.muted, textTransform: 'uppercase', whiteSpace: 'nowrap', ...style}}>{children}</div>
);

const RCA_X = 980;
const TRACK_W = 520;

/** One comparison row: name, a track whose fill grows while its percent counts up, and the cost per answer under it. */
const RcaRow: React.FC<{label: string; value: number; usdPer?: number; top: number; t: number; gold?: boolean}> = ({label, value, usdPer, top, t, gold}) => {
	const grow = ramp(t, 8, 8 + GROW, ease);
	return (
		<div style={{position: 'absolute', left: RCA_X, top, width: 900, opacity: ramp(t, 0, FADE)}}>
			<div style={{fontSize: 34, fontWeight: 700, color: gold ? color.accent : color.text}}>{label}</div>
			<div style={{position: 'relative', marginTop: 14, width: TRACK_W, height: 44, borderRadius: 8, background: color.panel}}>
				<div style={{width: (TRACK_W * value * grow) / 100, height: '100%', borderRadius: 8, background: gold ? color.accent : BAR_GREY}} />
				<div style={{position: 'absolute', left: TRACK_W + 24, top: -6, fontSize: 44, fontWeight: 800, fontVariantNumeric: 'tabular-nums', color: gold ? color.accent : color.text}}>
					{Math.round(value * grow)}%
				</div>
			</div>
			{usdPer === undefined ? null : (
				<div style={{marginTop: 12, fontSize: 28, color: color.muted, opacity: ramp(t, 8 + GROW, 8 + GROW + FADE)}}>
					{usd(usdPer)} {benchContent.perAnswer}
				</div>
			)}
		</div>
	);
};

/** The headline number counts up on the left; on the right the 48-case comparison grows row by row, ours last in gold. */
export const BenchRcaShot: React.FC<{frames: number; benchmarks: Benchmarks}> = ({frames, benchmarks: b}) => {
	const frame = useCurrentFrame();
	const r = b.rca;
	if (!r) return null;
	const t = benchContent.rca;
	const count = ramp(frame, 10, 10 + 36, ease);
	const rowsAt = Math.min(Math.round(frames * 0.3), 90);
	const rowGap = Math.min(Math.round(frames * 0.12), 36);
	const rows = [
		...(r.baro_pct === undefined ? [] : [{label: t.baro, value: r.baro_pct}]),
		{label: t.logsOnly, value: r.logs_only_pct, usdPer: r.logs_only_usd},
		{label: t.withMetrics, value: r.with_metrics_pct, usdPer: r.with_metrics_usd, gold: true},
	];
	const rowTop = (i: number) => 410 + (i + 3 - rows.length) * 140 + (i === rows.length - 1 ? 40 : 0);
	return (
		<AbsoluteFill style={{fontFamily: font.sans}}>
			{r.final ? null : <PlaceholderTag />}
			<div style={{position: 'absolute', top: 92, width: '100%', textAlign: 'center', opacity: ramp(frame, 0, FADE)}}>
				<div style={{fontSize: 76, fontWeight: 800, letterSpacing: -1.5, color: color.text}}>{t.title}</div>
				<Kicker style={{marginTop: 22, fontSize: 34}}>{t.subtitle}</Kicker>
			</div>
			<div style={{position: 'absolute', left: 90, width: 800, top: 330, textAlign: 'center'}}>
				<div
					style={{
						fontSize: 210,
						fontWeight: 800,
						lineHeight: 1,
						letterSpacing: -6,
						fontVariantNumeric: 'tabular-nums',
						color: color.accent,
						opacity: ramp(frame, 6, 6 + FADE),
						transform: `scale(${0.92 + 0.08 * count})`,
					}}
				>
					{pct(r.ac1_pct * count)}
				</div>
				<div style={{fontSize: 46, color: color.text, marginTop: 40, opacity: ramp(frame, 30, 30 + FADE)}}>{t.ac1}</div>
				<div style={{fontSize: 40, color: color.muted, marginTop: 24, fontVariantNumeric: 'tabular-nums', opacity: ramp(frame, 46, 46 + FADE)}}>
					<span style={{color: color.text, fontWeight: 800}}>{pct(r.ac3_pct)}</span> {t.ac3}
				</div>
				<div style={{fontSize: 28, color: color.muted, marginTop: 36, opacity: ramp(frame, 58, 58 + FADE)}}>{t.setup}</div>
			</div>
			<Kicker style={{position: 'absolute', left: RCA_X, top: 344, fontSize: 26, letterSpacing: '0.22em', opacity: ramp(frame, rowsAt - 12, rowsAt - 12 + FADE)}}>{t.compareTitle}</Kicker>
			{rows.map((row, i) => (
				<RcaRow key={row.label} {...row} top={rowTop(i)} t={frame - (rowsAt + i * rowGap)} />
			))}
			<div style={{position: 'absolute', left: 96, top: 960, fontSize: 26, color: color.muted, opacity: ramp(frame, rowsAt + rows.length * rowGap, rowsAt + rows.length * rowGap + FADE)}}>
				{t.source}
			</div>
		</AbsoluteFill>
	);
};
