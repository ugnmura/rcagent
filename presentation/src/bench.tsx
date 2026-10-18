// Scene 3 benchmarks, calm enough to talk over: long shots with plain fades and no sound effects. Simple style: flat
// bars on the dark background, gold only for ours, per shot one short label plus the numbers. First the score of each
// step; then its cost and the cost multiple; then the RCAEval root-cause result. Numbers come only from public/assets/benchmarks.json.
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

const pct = (v: number) => `${v.toFixed(1)}%`;
const usd = (v: number) => `$${v.toFixed(2)}`;
const ours = (b: Benchmarks) => b.designs.find((d) => d.ours) ?? b.designs[0];

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
const Column: React.FC<{d: Design; k: number; h: number; value: string; t: number}> = ({d, k, h, value, t}) => {
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
				{d.name}
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

/** Columns come in one at a time, spaced for the narration; each stays on screen to the end of the shot. */
export const BenchStepsShot: React.FC<{frames: number; benchmarks: Benchmarks}> = ({frames, benchmarks: b}) => {
	const frame = useCurrentFrame();
	const ds = b.designs.slice(0, 3);
	const at = (v: number) => Math.max(0, Math.min(1, (v - AXIS_MIN) / (100 - AXIS_MIN)));
	const step = Math.round(frames * 0.3);
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
				const t = frame - (10 + k * step);
				if (t < 0) return null;
				const v = d.score_pct ?? 0;
				return <Column key={d.name} d={d} k={k} h={at(v) * BAR_MAX} value={pct(v)} t={t} />;
			})}
			<Footer opacity={ramp(frame, 0, FADE)}>{setup}</Footer>
		</AbsoluteFill>
	);
};

// ------------------------------------------------------------------ shot 2: cost per answer, then the multiple

/** Cost bars start at zero, so their heights compare honestly; then one caption with the multiple. */
export const BenchCostShot: React.FC<{frames: number; benchmarks: Benchmarks}> = ({frames, benchmarks: b}) => {
	const frame = useCurrentFrame();
	const ds = b.designs.slice(0, 3);
	const d = ours(b);
	const top = Math.max(...ds.map((x) => x.usd_per_answer ?? 0), 1e-9);
	const priciest = ds.reduce<Design>((a, x) => ((x.usd_per_answer ?? 0) > (a.usd_per_answer ?? 0) ? x : a), d);
	const times = (priciest.usd_per_answer ?? 0) / Math.max(1e-9, d.usd_per_answer ?? 1);
	const captionAt = Math.round(frames * 0.4);
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
				return <Column key={x.name} d={x} k={k} h={(c / top) * BAR_MAX} value={usd(c)} t={t} />;
			})}
			<Footer opacity={ramp(frame, captionAt, captionAt + FADE)} size={48}>
				<span style={{color: color.accent, fontWeight: 800}}>{Number(times.toFixed(1))}×</span>{' '}
				<span style={{color: color.text}}>
					{benchContent.cheaper} {priciest.short ?? priciest.name}
				</span>
			</Footer>
		</AbsoluteFill>
	);
};

// ------------------------------------------------------------------ shot 3: root cause on microservices (RCAEval)

/** One big number (right root cause, first guess), the top-three share under it, and the source in small type. */
export const BenchRcaShot: React.FC<{frames: number; benchmarks: Benchmarks}> = ({frames, benchmarks: b}) => {
	const frame = useCurrentFrame();
	const r = b.rca;
	if (!r) return null;
	const second = Math.round(frames * 0.12);
	return (
		<AbsoluteFill style={{fontFamily: font.sans}}>
			{r.final ? null : <PlaceholderTag />}
			<Title opacity={ramp(frame, 0, FADE)}>{r.title.toUpperCase()}</Title>
			<div style={{position: 'absolute', top: 280, width: '100%', textAlign: 'center', opacity: ramp(frame, 6, 6 + FADE)}}>
				<div style={{fontSize: 200, fontWeight: 800, lineHeight: 1, letterSpacing: -5, fontVariantNumeric: 'tabular-nums', color: color.accent}}>{pct(r.ac1_pct)}</div>
				<div style={{fontSize: 44, color: color.text, marginTop: 24}}>{benchContent.rca.ac1}</div>
			</div>
			<div style={{position: 'absolute', top: 600, width: '100%', textAlign: 'center', fontSize: 38, color: color.muted, fontVariantNumeric: 'tabular-nums', opacity: ramp(frame, second, second + FADE)}}>
				<span style={{color: color.text, fontWeight: 800}}>{pct(r.ac3_pct)}</span> {benchContent.rca.ac3}
			</div>
			<Footer opacity={ramp(frame, 0, FADE)} size={28}>
				{r.source}
			</Footer>
		</AbsoluteFill>
	);
};
