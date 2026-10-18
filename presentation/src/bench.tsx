// Scene 3 benchmarks in film style, told as how we got here: the setup in three slams, then one column per step
// (start small, more tools, add Drain3) with its pipeline and a climbing score, the cost of each step, the cost multiple. Numbers come only from public/assets/benchmarks.json.
import React from 'react';
import {AbsoluteFill, Audio, random, Sequence, spring, staticFile, useCurrentFrame, useVideoConfig} from 'remotion';
import type {Benchmarks, Design} from './benchmarks';
import {benchmarks as benchContent} from './content';
import {easeOut, ramp} from './film';
import {color, font} from './theme';

/** Bottom of the score axis (percent). Both ends are labelled, so the zoom stays honest. */
const AXIS_MIN = 80;
const GLOW = 'rgba(245,165,36,';
const BAR_GREY = '#3b4450';

const Sfx: React.FC<{name: string; from: number; volume: number}> = ({name, from, volume}) =>
	from >= 0 ? (
		<Sequence from={from} layout="none">
			<Audio src={staticFile(`assets/sfx/${name}.wav`)} volume={volume} />
		</Sequence>
	) : null;

/** Camera kick: a short punch-in and shake that decays after frame `at`. */
const useKick = (at: number, strength = 1) => {
	const frame = useCurrentFrame();
	const t = frame - at;
	const kick = t >= 0 ? Math.exp(-t / 7) : 0;
	const shake = t >= 0 && t < 10 ? kick * 10 * strength : 0;
	return {
		kick,
		transform: `translate(${(random(`bx${frame}`) - 0.5) * shake}px, ${(random(`by${frame}`) - 0.5) * shake}px) scale(${1 + 0.04 * strength * kick})`,
	};
};

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

// ------------------------------------------------------------------ shot 1: the setup, three slams

export const BenchSetupShot: React.FC<{frames: number; benchmarks: Benchmarks}> = ({frames, benchmarks: b}) => {
	const frame = useCurrentFrame();
	const {fps} = useVideoConfig();
	const items: [number | undefined, string][] = [
		[b.designs.length, benchContent.setup.designs],
		[b.questions, benchContent.setup.questions],
		[b.runs, benchContent.setup.runs],
	];
	const beats = items.filter((it): it is [number, string] => it[0] !== undefined);
	const beat = Math.max(1, Math.floor(frames / beats.length));
	const i = Math.min(beats.length - 1, Math.floor(frame / beat));
	const t = frame - i * beat;
	const s = spring({frame: t, fps, config: {damping: 14, stiffness: 220, mass: 0.7}});
	const {transform} = useKick(i * beat, 0.8);
	const [n, label] = beats[i];
	return (
		<AbsoluteFill style={{fontFamily: font.sans, justifyContent: 'center', alignItems: 'center'}}>
			{beats.map((_, k) => (
				<Sfx key={k} name="impact" from={k * beat} volume={0.45} />
			))}
			<div style={{display: 'flex', alignItems: 'baseline', gap: 48, transform}}>
				<div
					style={{
						fontSize: 300,
						fontWeight: 800,
						color: color.accent,
						lineHeight: 1,
						letterSpacing: -8,
						fontVariantNumeric: 'tabular-nums',
						transform: `scale(${1.5 - 0.5 * s})`,
						opacity: Math.min(1, s * 1.4),
						filter: `blur(${(1 - s) * 10}px)`,
						textShadow: `0 0 ${60 * (1 - s) + 30}px ${GLOW}0.35)`,
					}}
				>
					{n}
				</div>
				<div style={{fontSize: 84, fontWeight: 600, color: color.text, opacity: ramp(t, 4, 14), transform: `translateX(${(1 - ramp(t, 4, 16, easeOut)) * 40}px)`}}>
					{label}
				</div>
			</div>
			{/* beat counter: three ticks under the slam */}
			<div style={{position: 'absolute', top: 760, display: 'flex', gap: 18}}>
				{beats.map((_, k) => (
					<div key={k} style={{width: 90, height: 6, borderRadius: 3, background: k <= i ? color.accent : color.line}} />
				))}
			</div>
		</AbsoluteFill>
	);
};

/** Design name, and under it one muted line on how it answers a question. */
export const DesignLabel: React.FC<{d: Design; width: number; size?: number}> = ({d, width, size = 44}) => (
	<div style={{width, textAlign: 'right', whiteSpace: 'nowrap'}}>
		<div style={{fontSize: size, fontWeight: d.ours ? 800 : 600, color: d.ours ? color.accent : color.text}}>{d.name}</div>
		{d.detail ? <div style={{fontSize: size * 0.6, color: color.muted, marginTop: 6}}>{d.detail}</div> : null}
	</div>
);


// ------------------------------------------------------------------ shot 2: the steps, one column each

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

/** The stages a question goes through, stacked top to bottom; the stage that is new in this step is gold. */
const Pipeline: React.FC<{d: Design; t: number}> = ({d, t}) => {
	const stages = d.pipeline ?? [d.name];
	return (
		<div style={{display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4}}>
			{stages.map((s, i) => {
				const p = ramp(t, 6 + i * 5, 14 + i * 5, easeOut);
				const isNew = s === d.added;
				return (
					<React.Fragment key={s}>
						{i > 0 ? <div style={{fontSize: 26, lineHeight: 1, color: color.muted, opacity: p}}>↓</div> : null}
						<div
							style={{
								opacity: p,
								transform: `translateY(${(1 - p) * 10}px) scale(${isNew ? 1 + 0.15 * Math.exp(-Math.max(0, t - 14 - i * 5) / 6) : 1})`,
								padding: '8px 18px',
								borderRadius: 10,
								fontSize: 28,
								fontWeight: isNew ? 800 : 600,
								whiteSpace: 'nowrap',
								color: isNew ? color.accent : color.text,
								border: `2px solid ${isNew ? color.accent : color.line}`,
								background: isNew ? 'rgba(245,165,36,0.12)' : 'transparent',
								boxShadow: isNew ? `0 0 24px ${GLOW}0.35)` : 'none',
							}}
						>
							{s}
						</div>
					</React.Fragment>
				);
			})}
		</div>
	);
};

/** One column per design, left to right in story order: step title, its pipeline, a score bar that climbs. */
export const BenchStepsShot: React.FC<{frames: number; benchmarks: Benchmarks}> = ({frames, benchmarks: b}) => {
	const frame = useCurrentFrame();
	const {fps} = useVideoConfig();
	const ds = b.designs.slice(0, 3);
	const at = (v: number) => Math.max(0, Math.min(1, (v - AXIS_MIN) / (100 - AXIS_MIN)));
	const STEP = Math.round(frames * 0.27);
	const starts = ds.map((_, k) => 6 + k * STEP);
	const GROW = 26;
	const last = starts[ds.length - 1] + 14 + GROW;
	const win = spring({frame: frame - last, fps, config: {damping: 10, stiffness: 180, mass: 0.6}});
	const {transform} = useKick(last);
	return (
		<AbsoluteFill style={{fontFamily: font.sans}}>
			{starts.map((s, k) => (
				<Sfx key={k} name="whoosh" from={s} volume={0.3} />
			))}
			{starts.slice(0, -1).map((s, k) => (
				<Sfx key={`c${k}`} name="click" from={s + 14 + GROW} volume={0.55} />
			))}
			<Sfx name="impact" from={last} volume={0.7} />
			<Sfx name="chime" from={last} volume={0.55} />
			<AbsoluteFill style={{transform, transformOrigin: '75% 60%'}}>
				{/* axis: baseline at 80 %, dashed line at 100 %, both labelled */}
				<div style={{position: 'absolute', left: COL_LEFT - 20, width: 3 * COL_W + 2 * COL_GAP + 40, top: BASE, borderTop: `2px solid ${color.line}`, opacity: ramp(frame, 0, 10)}} />
				<div style={{position: 'absolute', left: COL_LEFT - 20, width: 3 * COL_W + 2 * COL_GAP + 40, top: BASE - BAR_MAX, borderTop: `2px dashed ${color.line}`, opacity: ramp(frame, 0, 10)}} />
				<div style={{position: 'absolute', left: COL_LEFT - 110, top: BASE - 18, width: 80, textAlign: 'right', fontSize: 26, color: color.muted}}>{AXIS_MIN}%</div>
				<div style={{position: 'absolute', left: COL_LEFT - 110, top: BASE - BAR_MAX - 18, width: 80, textAlign: 'right', fontSize: 26, color: color.muted}}>100%</div>
				{ds.map((d, k) => {
					const t = frame - starts[k];
					if (t < 0) return null;
					const v = d.score_pct ?? 0;
					const grow = ramp(t, 14, 14 + GROW, easeOut);
					const h = at(v) * BAR_MAX * grow;
					const head = ramp(t, 0, 10, easeOut);
					const later = ds.length - 1 > k ? ramp(frame, last, last + 12) : 0;
					const glow = d.ours ? win : 0;
					const prev = k > 0 ? ds[k - 1].score_pct ?? 0 : null;
					const pctUp = prev === null ? 0 : v - prev;
					return (
						<div key={d.name} style={{position: 'absolute', left: colX(k), top: 0, width: COL_W, height: 1080, opacity: 1 - 0.45 * later}}>
							<div style={{position: 'absolute', top: 120, width: '100%', textAlign: 'center', opacity: head, transform: `translateY(${(1 - head) * 16}px)`}}>
								<div style={{fontSize: 24, fontWeight: 800, letterSpacing: '0.3em', color: color.muted}}>STEP {k + 1}</div>
								<div style={{fontSize: 54, fontWeight: 800, color: d.ours ? color.accent : color.text, marginTop: 6}}>{d.step ?? d.name}</div>
							</div>
							<div style={{position: 'absolute', top: 236, width: '100%'}}>
								<Pipeline d={d} t={t} />
							</div>
							<div
								style={{
									position: 'absolute',
									left: (COL_W - BAR_W) / 2,
									width: BAR_W,
									top: BASE - h,
									height: h,
									borderRadius: '12px 12px 0 0',
									background: d.ours ? `linear-gradient(0deg, #b8741a, ${color.accent} 70%, #ffd27a)` : `linear-gradient(0deg, #2a313a, ${BAR_GREY})`,
									boxShadow: d.ours ? `0 0 ${20 + 70 * glow}px ${GLOW}${0.25 + 0.45 * glow})` : 'none',
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
									opacity: ramp(t, 14, 20),
									transform: d.ours ? `scale(${1 + 0.2 * glow * Math.exp(-Math.max(0, frame - last) / 8)})` : undefined,
								}}
							>
								{pct(AXIS_MIN + (v - AXIS_MIN) * grow)}
							</div>
							<div style={{position: 'absolute', top: BASE + 18, width: '100%', textAlign: 'center', fontSize: 30, color: color.muted, opacity: ramp(t, 20, 30), fontVariantNumeric: 'tabular-nums'}}>
								{d.name}
							</div>
							{prev !== null ? (
								<Delta
									text={`${pctUp >= 0 ? '+' : '−'}${Math.abs(pctUp).toFixed(1)} pts`}
									good={pctUp >= 0}
									style={{left: -COL_GAP / 2 - 70, top: BASE - at(v) * BAR_MAX - 30, opacity: ramp(t, 14 + GROW, 14 + GROW + 8), transform: `scale(${0.6 + 0.4 * ramp(t, 14 + GROW, 14 + GROW + 8, easeOut)})`}}
								/>
							) : null}
						</div>
					);
				})}
			</AbsoluteFill>
		</AbsoluteFill>
	);
};

// ------------------------------------------------------------------ shot 3: cost per answer, same columns

/** Cost bars start at zero, so their heights compare honestly; each step shows its change against the one before. */
export const BenchCostBarsShot: React.FC<{frames: number; benchmarks: Benchmarks}> = ({frames, benchmarks: b}) => {
	const frame = useCurrentFrame();
	const ds = b.designs.slice(0, 3);
	const top = Math.max(...ds.map((d) => d.usd_per_answer ?? 0), 1e-9);
	const starts = ds.map((_, k) => 8 + k * Math.round(frames * 0.16));
	const GROW = 20;
	const oursAt = starts[ds.findIndex((d) => d.ours)] ?? starts[ds.length - 1];
	const {transform} = useKick(oursAt + GROW, 0.7);
	return (
		<AbsoluteFill style={{fontFamily: font.sans}}>
			{starts.map((s, k) => (
				<Sfx key={k} name={ds[k].ours ? 'impact' : 'click'} from={s + GROW} volume={ds[k].ours ? 0.6 : 0.5} />
			))}
			<div style={{position: 'absolute', top: 130, width: '100%', textAlign: 'center', fontSize: 34, fontWeight: 600, letterSpacing: '0.3em', color: color.muted, opacity: ramp(frame, 0, 12)}}>
				{benchContent.costTitle.toUpperCase()}
			</div>
			<AbsoluteFill style={{transform, transformOrigin: '75% 70%'}}>
				<div style={{position: 'absolute', left: COL_LEFT - 20, width: 3 * COL_W + 2 * COL_GAP + 40, top: BASE, borderTop: `2px solid ${color.line}`}} />
				{ds.map((d, k) => {
					const t = frame - starts[k];
					const c = d.usd_per_answer ?? 0;
					const grow = ramp(t, 0, GROW, easeOut);
					const h = (c / top) * BAR_MAX * grow;
					const prev = k > 0 ? ds[k - 1].usd_per_answer ?? 0 : null;
					const change = prev ? (c - prev) / prev : 0;
					return (
						<div key={d.name} style={{position: 'absolute', left: colX(k), top: 0, width: COL_W, height: 1080, opacity: ramp(t, 0, 6)}}>
							<div
								style={{
									position: 'absolute',
									left: (COL_W - BAR_W) / 2,
									width: BAR_W,
									top: BASE - h,
									height: h,
									borderRadius: '12px 12px 0 0',
									background: d.ours ? `linear-gradient(0deg, #b8741a, ${color.accent})` : `linear-gradient(0deg, #2a313a, ${BAR_GREY})`,
									boxShadow: d.ours ? `0 0 50px ${GLOW}0.4)` : 'none',
								}}
							/>
							<div style={{position: 'absolute', width: '100%', top: BASE - h - 92, textAlign: 'center', fontSize: 72, fontWeight: 800, fontVariantNumeric: 'tabular-nums', color: d.ours ? color.accent : color.text}}>
								{usd(c * grow)}
							</div>
							<div style={{position: 'absolute', top: BASE + 18, width: '100%', textAlign: 'center', fontSize: 30, color: color.muted}}>{d.name}</div>
							{prev ? (
								<Delta
									text={`${change >= 0 ? '+' : '−'}${Math.abs(Math.round(change * 100))}%`}
									good={change < 0}
									style={{left: -COL_GAP / 2 - 60, top: BASE - (c / top) * BAR_MAX - 30, opacity: ramp(t, GROW, GROW + 8), transform: `scale(${0.6 + 0.4 * ramp(t, GROW, GROW + 8, easeOut)})`}}
								/>
							) : null}
						</div>
					);
				})}
			</AbsoluteFill>
		</AbsoluteFill>
	);
};


// ------------------------------------------------------------------ shot 4: the cost multiple

export const BenchCostShot: React.FC<{frames: number; benchmarks: Benchmarks}> = ({benchmarks: b}) => {
	const frame = useCurrentFrame();
	const {fps} = useVideoConfig();
	const d = ours(b);
	const priciest = b.designs.reduce<Design>((a, x) => ((x.usd_per_answer ?? 0) > (a.usd_per_answer ?? 0) ? x : a), d);
	const times = (priciest.usd_per_answer ?? 0) / Math.max(1e-9, d.usd_per_answer ?? 1);
	const SLAM = 6;
	const s = spring({frame: frame - SLAM, fps, config: {damping: 11, stiffness: 240, mass: 0.7}});
	const {transform} = useKick(SLAM + 6, 1.2);
	const words = ramp(frame, SLAM + 12, SLAM + 26, easeOut);
	return (
		<AbsoluteFill style={{fontFamily: font.sans, justifyContent: 'center', alignItems: 'center'}}>
			<Sfx name="impact" from={SLAM + 6} volume={0.8} />
			<div style={{display: 'flex', flexDirection: 'column', alignItems: 'center', transform, marginTop: -60}}>
				<div
					style={{
						fontSize: 340,
						fontWeight: 800,
						lineHeight: 1,
						letterSpacing: -10,
						color: color.text,
						transform: `scale(${2.2 - 1.2 * s})`,
						opacity: Math.min(1, s * 2),
						filter: `blur(${Math.max(0, 1 - s) * 14}px)`,
					}}
				>
					{Number(times.toFixed(1))}
					<span style={{color: color.accent}}>×</span>
				</div>
				<div style={{fontSize: 58, color: color.text, marginTop: 24, opacity: words, transform: `translateY(${(1 - words) * 18}px)`}}>
					{benchContent.cheaper} <span style={{fontWeight: 800}}>{priciest.short ?? priciest.name}</span>
				</div>
			</div>
			<div
				style={{
					position: 'absolute',
					top: 800,
					fontSize: 46,
					color: color.muted,
					opacity: ramp(frame, SLAM + 30, SLAM + 44, easeOut),
					transform: `translateY(${(1 - ramp(frame, SLAM + 30, SLAM + 44, easeOut)) * 18}px)`,
				}}
			>
				{benchContent.andTop} <span style={{color: color.accent, fontWeight: 800}}>{pct(d.score_pct ?? 0)}</span>
			</div>
		</AbsoluteFill>
	);
};
