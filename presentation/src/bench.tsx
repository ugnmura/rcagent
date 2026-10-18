// Scene 3 benchmarks, calm enough to talk over: long shots with plain fades and no sound effects. First one column
// per step (start small, more tools, add Drain3) with its pipeline and score; then the cost of each step and the cost
// multiple as a caption; then the RCAEval root-cause result for the metric and trace tools. Numbers come only from public/assets/benchmarks.json.
import React from 'react';
import {AbsoluteFill, useCurrentFrame} from 'remotion';
import type {Benchmarks, Design} from './benchmarks';
import {benchmarks as benchContent} from './content';
import {ease, ramp} from './film';
import {color, font} from './theme';

/** Bottom of the score axis (percent). Both ends are labelled, so the zoom stays honest. */
const AXIS_MIN = 80;
const BAR_GREY = '#3b4450';
const GREEN = '#3fb950';
const RED_SOFT = '#ff6b6b';

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

/** Design name, and under it one muted line on how it answers a question. */
export const DesignLabel: React.FC<{d: Design; width: number; size?: number}> = ({d, width, size = 44}) => (
	<div style={{width, textAlign: 'right', whiteSpace: 'nowrap'}}>
		<div style={{fontSize: size, fontWeight: d.ours ? 800 : 600, color: d.ours ? color.accent : color.text}}>{d.name}</div>
		{d.detail ? <div style={{fontSize: size * 0.6, color: color.muted, marginTop: 6}}>{d.detail}</div> : null}
	</div>
);

/** Small pill with a signed change, green when it is good news. */
const Delta: React.FC<{text: string; good: boolean; style?: React.CSSProperties}> = ({text, good, style}) => (
	<div
		style={{
			position: 'absolute',
			padding: '6px 16px',
			borderRadius: 999,
			fontSize: 30,
			fontWeight: 800,
			fontVariantNumeric: 'tabular-nums',
			color: good ? GREEN : RED_SOFT,
			border: `2px solid ${good ? GREEN : RED_SOFT}`,
			background: '#030405',
			whiteSpace: 'nowrap',
			...style,
		}}
	>
		{text}
	</div>
);

/** A bar on the shared baseline with its value above and the design name below; fades in, then the bar rises. */
const Column: React.FC<{d: Design; k: number; h: number; value: string; t: number; children?: React.ReactNode}> = ({d, k, h, value, t, children}) => {
	const grow = ramp(t, FADE, FADE + GROW, ease);
	return (
		<div style={{position: 'absolute', left: colX(k), top: 0, width: COL_W, height: 1080, opacity: ramp(t, 0, FADE)}}>
			{children}
			<div
				style={{
					position: 'absolute',
					left: (COL_W - BAR_W) / 2,
					width: BAR_W,
					top: BASE - h * grow,
					height: h * grow,
					borderRadius: '12px 12px 0 0',
					background: d.ours ? `linear-gradient(0deg, #b8741a, ${color.accent})` : `linear-gradient(0deg, #2a313a, ${BAR_GREY})`,
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
			<div style={{position: 'absolute', top: BASE + 18, width: '100%', textAlign: 'center', fontSize: 30, color: color.muted}}>{d.name}</div>
		</div>
	);
};

const Baseline: React.FC = () => (
	<div style={{position: 'absolute', left: COL_LEFT - 20, width: 3 * COL_W + 2 * COL_GAP + 40, top: BASE, borderTop: `2px solid ${color.line}`}} />
);

/** One muted line across the bottom: the setup, or the closing caption. */
const Footer: React.FC<{opacity: number; children: React.ReactNode}> = ({opacity, children}) => (
	<div style={{position: 'absolute', top: 900, width: '100%', textAlign: 'center', fontSize: 36, color: color.muted, opacity}}>{children}</div>
);

// ------------------------------------------------------------------ shot 1: the steps, one column each

/** The stages a question goes through, stacked top to bottom; the stage that is new in this step is gold. */
const Pipeline: React.FC<{d: Design}> = ({d}) => (
	<div style={{display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4}}>
		{(d.pipeline ?? [d.name]).map((s, i) => {
			const isNew = s === d.added;
			return (
				<React.Fragment key={s}>
					{i > 0 ? <div style={{fontSize: 26, lineHeight: 1, color: color.muted}}>↓</div> : null}
					<div
						style={{
							padding: '8px 18px',
							borderRadius: 10,
							fontSize: 28,
							fontWeight: isNew ? 800 : 600,
							whiteSpace: 'nowrap',
							color: isNew ? color.accent : color.text,
							border: `2px solid ${isNew ? color.accent : color.line}`,
							background: isNew ? 'rgba(245,165,36,0.12)' : 'transparent',
						}}
					>
						{s}
					</div>
				</React.Fragment>
			);
		})}
	</div>
);

/** Columns come in one at a time, spaced for the narration; each stays on screen to the end of the shot. */
export const BenchStepsShot: React.FC<{frames: number; benchmarks: Benchmarks}> = ({frames, benchmarks: b}) => {
	const frame = useCurrentFrame();
	const ds = b.designs.slice(0, 3);
	const at = (v: number) => Math.max(0, Math.min(1, (v - AXIS_MIN) / (100 - AXIS_MIN)));
	const step = Math.round(frames * 0.3);
	const setup = [
		b.questions ? `${b.questions} ${benchContent.setup.questions}` : null,
		b.runs ? `${b.runs} ${benchContent.setup.runs}` : null,
		benchContent.setup.blind,
	]
		.filter(Boolean)
		.join(' · ');
	return (
		<AbsoluteFill style={{fontFamily: font.sans}}>
			{b.final ? null : <PlaceholderTag />}
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
				const prev = k > 0 ? ds[k - 1].score_pct ?? 0 : null;
				return (
					<Column key={d.name} d={d} k={k} h={at(v) * BAR_MAX} value={pct(v)} t={t}>
						<div style={{position: 'absolute', top: 120, width: '100%', textAlign: 'center'}}>
							<div style={{fontSize: 24, fontWeight: 800, letterSpacing: '0.3em', color: color.muted}}>STEP {k + 1}</div>
							<div style={{fontSize: 54, fontWeight: 800, color: d.ours ? color.accent : color.text, marginTop: 6}}>{d.step ?? d.name}</div>
						</div>
						<div style={{position: 'absolute', top: 236, width: '100%'}}>
							<Pipeline d={d} />
						</div>
						{prev !== null ? (
							<Delta
								text={`${v >= prev ? '+' : '−'}${Math.abs(v - prev).toFixed(1)} pts`}
								good={v >= prev}
								style={{left: -COL_GAP / 2 - 70, top: BASE - at(v) * BAR_MAX - 30, opacity: ramp(t, FADE + GROW, FADE + GROW + FADE)}}
							/>
						) : null}
					</Column>
				);
			})}
			<Footer opacity={ramp(frame, 0, FADE)}>{setup}</Footer>
		</AbsoluteFill>
	);
};

// ------------------------------------------------------------------ shot 2: cost per answer, then the multiple

/** Cost bars start at zero, so their heights compare honestly; each step shows its change against the one before. */
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
			<div style={{position: 'absolute', top: 130, width: '100%', textAlign: 'center', fontSize: 34, fontWeight: 600, letterSpacing: '0.3em', color: color.muted, opacity: ramp(frame, 0, FADE)}}>
				{benchContent.costTitle.toUpperCase()}
			</div>
			<div style={{opacity: ramp(frame, 0, FADE)}}>
				<Baseline />
			</div>
			{ds.map((x, k) => {
				const t = frame - (6 + k * 12);
				const c = x.usd_per_answer ?? 0;
				const prev = k > 0 ? ds[k - 1].usd_per_answer ?? 0 : null;
				const change = prev ? (c - prev) / prev : 0;
				return (
					<Column key={x.name} d={x} k={k} h={(c / top) * BAR_MAX} value={usd(c)} t={t}>
						{prev ? (
							<Delta
								text={`${change >= 0 ? '+' : '−'}${Math.abs(Math.round(change * 100))}%`}
								good={change < 0}
								style={{left: -COL_GAP / 2 - 60, top: BASE - (c / top) * BAR_MAX - 30, opacity: ramp(t, FADE + GROW, FADE + GROW + FADE)}}
							/>
						) : null}
					</Column>
				);
			})}
			<Footer opacity={ramp(frame, captionAt, captionAt + FADE)}>
				<span style={{color: color.text, fontWeight: 800}}>{Number(times.toFixed(1))}×</span> {benchContent.cheaper} {priciest.short ?? priciest.name},{' '}
				{benchContent.andTop} <span style={{color: color.accent, fontWeight: 800}}>{pct(d.score_pct ?? 0)}</span>
			</Footer>
		</AbsoluteFill>
	);
};

// ------------------------------------------------------------------ shot 3: root cause on microservices (RCAEval)

/** Two big numbers, then the logs-only comparison and the source; plain fades, spaced for the narration. */
export const BenchRcaShot: React.FC<{frames: number; benchmarks: Benchmarks}> = ({frames, benchmarks: b}) => {
	const frame = useCurrentFrame();
	const r = b.rca;
	if (!r) return null;
	const second = Math.round(frames * 0.12);
	const compare = Math.round(frames * 0.35);
	const big = (value: number, label: string, gold: boolean, from: number) => (
		<div style={{width: 640, textAlign: 'center', opacity: ramp(frame, from, from + FADE)}}>
			<div style={{fontSize: 170, fontWeight: 800, lineHeight: 1, letterSpacing: -4, fontVariantNumeric: 'tabular-nums', color: gold ? color.accent : color.text}}>
				{pct(value)}
			</div>
			<div style={{fontSize: 40, color: color.text, marginTop: 20}}>{label}</div>
		</div>
	);
	return (
		<AbsoluteFill style={{fontFamily: font.sans}}>
			{r.final ? null : <PlaceholderTag />}
			<div style={{position: 'absolute', top: 130, width: '100%', textAlign: 'center', fontSize: 34, fontWeight: 600, letterSpacing: '0.3em', color: color.muted, opacity: ramp(frame, 0, FADE)}}>
				{r.title.toUpperCase()}
			</div>
			<div style={{position: 'absolute', top: 290, width: '100%', display: 'flex', justifyContent: 'center', gap: 80}}>
				{big(r.ac1_pct, benchContent.rca.ac1, true, 6)}
				{big(r.ac3_pct, benchContent.rca.ac3, false, second)}
			</div>
			<div
				style={{
					position: 'absolute',
					top: 690,
					width: '100%',
					textAlign: 'center',
					fontSize: 38,
					color: color.muted,
					fontVariantNumeric: 'tabular-nums',
					opacity: ramp(frame, compare, compare + FADE),
				}}
			>
				{benchContent.rca.logsOnly} <span style={{color: color.text, fontWeight: 800}}>{r.logs_only_pct}%</span> →{' '}
				{benchContent.rca.withMetrics} <span style={{color: color.accent, fontWeight: 800}}>{r.with_metrics_pct}%</span>
				{' · '}
				<span style={{color: color.text}}>{usd(r.logs_only_usd)}</span> → <span style={{color: color.accent, fontWeight: 800}}>{usd(r.with_metrics_usd)}</span> {benchContent.perAnswer}
				<span style={{fontSize: 28}}> ({r.compare_note})</span>
			</div>
			<Footer opacity={ramp(frame, 0, FADE)}>{r.source}</Footer>
		</AbsoluteFill>
	);
};
