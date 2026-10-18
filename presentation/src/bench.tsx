// Scene 3 benchmarks in film style: the setup in three slams, a bar race ours wins, every graded answer lighting up
// under the score, then the cost multiple. Numbers come only from public/assets/benchmarks.json.
import React from 'react';
import {AbsoluteFill, Audio, random, Sequence, spring, staticFile, useCurrentFrame, useVideoConfig} from 'remotion';
import type {Benchmarks, Design} from './benchmarks';
import {benchmarks as benchContent} from './content';
import {easeOut, ramp} from './film';
import {color, font} from './theme';

/** Left end of the race axis (percent). Ticks are labelled, so the zoom stays honest. */
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

// ------------------------------------------------------------------ shot 2: the race

/** Design name, and under it one muted line on how it answers a question. */
export const DesignLabel: React.FC<{d: Design; width: number; size?: number}> = ({d, width, size = 44}) => (
	<div style={{width, textAlign: 'right', whiteSpace: 'nowrap'}}>
		<div style={{fontSize: size, fontWeight: d.ours ? 800 : 600, color: d.ours ? color.accent : color.text}}>{d.name}</div>
		{d.detail ? <div style={{fontSize: size * 0.6, color: color.muted, marginTop: 6}}>{d.detail}</div> : null}
	</div>
);

const TRACK = 860;
const LABEL_W = 620;
/** Room right of the track for the value label. */
const VALUE_W = 200;

export const BenchRaceShot: React.FC<{frames: number; benchmarks: Benchmarks}> = ({frames, benchmarks: b}) => {
	const frame = useCurrentFrame();
	const {fps} = useVideoConfig();
	const top = Math.max(...b.designs.map((d) => d.score_pct ?? 0));
	const at = (v: number) => Math.max(0, Math.min(1, (v - AXIS_MIN) / (100 - AXIS_MIN)));
	// One shared front moves right with ease-out; each bar stops at its score, so the winner is the last to stop.
	const START = 12;
	const FINISH = Math.round(frames * 0.55);
	const front = ramp(frame, START, FINISH, easeOut) * at(top);
	const stopFrame = (v: number) => {
		// invert the ease numerically: first frame where the front reaches v
		for (let f = START; f <= FINISH; f++) if (ramp(f, START, FINISH, easeOut) * at(top) >= at(v) - 1e-6) return f;
		return FINISH;
	};
	const win = spring({frame: frame - FINISH, fps, config: {damping: 10, stiffness: 180, mass: 0.6}});
	const won = frame >= FINISH;
	const {transform} = useKick(FINISH);
	const ticks = [80, 85, 90, 95, 100].filter((v) => v >= AXIS_MIN);
	return (
		<AbsoluteFill style={{fontFamily: font.sans}}>
			<Sfx name="whoosh" from={START - 4} volume={0.4} />
			{b.designs.filter((d) => !d.ours).map((d) => (
				<Sfx key={d.name} name="click" from={stopFrame(d.score_pct ?? 0)} volume={0.55} />
			))}
			<Sfx name="impact" from={FINISH} volume={0.7} />
			<Sfx name="chime" from={FINISH} volume={0.55} />
			<div style={{position: 'absolute', top: 150, width: '100%', textAlign: 'center', fontSize: 34, fontWeight: 600, letterSpacing: '0.3em', color: color.muted, opacity: ramp(frame, 0, 12)}}>
				{benchContent.race.toUpperCase()}
			</div>
			<AbsoluteFill style={{transform, transformOrigin: '60% 50%'}}>
				<div style={{position: 'absolute', left: (1920 - LABEL_W - 40 - TRACK - VALUE_W) / 2, top: 290}}>
					{/* grid + axis */}
					<div style={{position: 'absolute', left: LABEL_W + 40, top: -30, width: TRACK, height: b.designs.length * 150 + 30}}>
						{ticks.map((v) => (
							<div key={v} style={{position: 'absolute', left: at(v) * TRACK, top: 0, bottom: 0, borderLeft: `2px ${v === 100 ? 'solid' : 'dashed'} ${color.line}`}}>
								<div style={{position: 'absolute', bottom: -52, left: -40, width: 80, textAlign: 'center', fontSize: 28, color: color.muted, fontVariantNumeric: 'tabular-nums'}}>{v}%</div>
							</div>
						))}
					</div>
					{b.designs.map((d, i) => {
						const v = d.score_pct ?? 0;
						const w = Math.min(front, at(v));
						const shown = AXIS_MIN + w * (100 - AXIS_MIN);
						const done = frame >= stopFrame(v);
						const dim = !d.ours && won ? 1 - 0.55 * Math.min(1, win) : 1;
						const glow = d.ours && won ? win : 0;
						const enter = ramp(frame, i * 4, i * 4 + 12, easeOut);
						return (
							<div key={d.name} style={{display: 'flex', alignItems: 'center', gap: 40, height: 150, opacity: enter * dim, transform: `translateX(${(1 - enter) * -30}px)`}}>
								<DesignLabel d={d} width={LABEL_W} size={38} />
								<div style={{position: 'relative', width: TRACK, height: 96}}>
									<div
										style={{
											position: 'absolute',
											left: 0,
											top: 0,
											height: '100%',
											width: Math.max(8, w * TRACK),
											borderRadius: 12,
											background: d.ours ? `linear-gradient(90deg, #b8741a, ${color.accent} 70%, #ffd27a)` : `linear-gradient(90deg, #2a313a, ${BAR_GREY})`,
											boxShadow: d.ours ? `0 0 ${20 + 70 * glow}px ${GLOW}${0.25 + 0.45 * glow})` : 'none',
										}}
									/>
									{/* bright leading edge while the bar is still moving */}
									{!done ? (
										<div style={{position: 'absolute', left: Math.max(8, w * TRACK) - 6, top: -6, width: 6, height: 108, borderRadius: 3, background: '#fff', opacity: 0.8, boxShadow: '0 0 24px #fff'}} />
									) : null}
									<div
										style={{
											position: 'absolute',
											left: Math.max(8, w * TRACK) + 14,
											top: 12,
											height: 72,
											padding: '0 12px',
											borderRadius: 10,
											background: '#030405',
											display: 'flex',
											alignItems: 'center',
											fontSize: 54,
											fontWeight: 800,
											fontVariantNumeric: 'tabular-nums',
											color: d.ours ? color.accent : color.text,
											transform: d.ours && won ? `scale(${1 + 0.25 * Math.exp(-(frame - FINISH) / 8)})` : undefined,
											transformOrigin: 'left center',
										}}
									>
										{pct(done ? v : shown)}
									</div>
								</div>
							</div>
						);
					})}
				</div>
				{/* winner badge */}
				{won ? (
					<div
						style={{
							position: 'absolute',
							right: 120,
							top: 190,
							transform: `scale(${win}) rotate(${(1 - win) * -20}deg)`,
							padding: '12px 26px',
							borderRadius: 999,
							background: color.accent,
							color: '#030405',
							fontSize: 34,
							fontWeight: 800,
							letterSpacing: '0.08em',
							boxShadow: `0 0 50px ${GLOW}0.6)`,
						}}
					>
						★ {benchContent.winner.toUpperCase()}
					</div>
				) : null}
			</AbsoluteFill>
		</AbsoluteFill>
	);
};

// ------------------------------------------------------------------ shot 3: every answer, then the score

export const BenchHeroShot: React.FC<{frames: number; benchmarks: Benchmarks}> = ({frames, benchmarks: b}) => {
	const frame = useCurrentFrame();
	const {fps} = useVideoConfig();
	const d = ours(b);
	const cols = b.questions ?? 30;
	const rows = b.runs ?? 5;
	const total = cols * rows;
	const CELL = 30;
	const GAP = 10;
	const gridW = cols * (CELL + GAP) - GAP;
	const sweepEnd = Math.round(frames * 0.42);
	const lit = ramp(frame, 4, sweepEnd, (x) => x) * (cols + rows);
	const back = ramp(frame, sweepEnd, sweepEnd + 14, easeOut);
	const NUM_FROM = sweepEnd + 4;
	const count = ramp(frame, NUM_FROM, NUM_FROM + 30, easeOut);
	const pop = spring({frame: frame - NUM_FROM, fps, config: {damping: 12, stiffness: 160}});
	const {transform} = useKick(NUM_FROM + 30, 0.6);
	const answered = Math.min(total, Math.round(ramp(frame, 4, sweepEnd, (x) => x) * total));
	return (
		<AbsoluteFill style={{fontFamily: font.sans, justifyContent: 'center', alignItems: 'center'}}>
			<Sfx name="whoosh" from={2} volume={0.25} />
			<Sfx name="impact" from={NUM_FROM + 30} volume={0.6} />
			<Sfx name="twinkle" from={NUM_FROM + 30} volume={0.3} />
			<div style={{position: 'absolute', opacity: 1 - 0.8 * back, transform: `scale(${1 - 0.1 * back})`, filter: `blur(${4 * back}px)`}}>
				<div style={{display: 'grid', gridTemplateColumns: `repeat(${cols}, ${CELL}px)`, gap: GAP, width: gridW}}>
					{Array.from({length: total}, (_, k) => {
						const c = k % cols;
						const r = Math.floor(k / cols);
						// diagonal sweep: a cell lights when the wave passes its column + row
						const on = Math.max(0, Math.min(1, lit - (c + r)));
						const flash = on > 0 && on < 1 ? 1 : 0;
						return (
							<div
								key={k}
								style={{
									width: CELL,
									height: CELL,
									borderRadius: 6,
									background: on > 0 ? (flash ? '#fff4d6' : color.accent) : color.panel,
									border: `1px solid ${on > 0 ? 'transparent' : color.line}`,
									boxShadow: flash ? `0 0 18px ${GLOW}0.9)` : 'none',
									opacity: 0.35 + 0.65 * on,
								}}
							/>
						);
					})}
				</div>
				<div style={{marginTop: 46, textAlign: 'center', fontSize: 46, color: color.text, fontVariantNumeric: 'tabular-nums', opacity: 1 - back}}>
					<span style={{fontWeight: 800, color: color.accent}}>{answered}</span> {benchContent.graded}
				</div>
			</div>
			{frame >= NUM_FROM ? (
				<div style={{display: 'flex', flexDirection: 'column', alignItems: 'center', transform}}>
					<div
						style={{
							fontSize: 320,
							fontWeight: 800,
							lineHeight: 1,
							letterSpacing: -10,
							color: color.accent,
							fontVariantNumeric: 'tabular-nums',
							transform: `scale(${0.7 + 0.3 * pop})`,
							textShadow: `0 0 80px ${GLOW}0.45)`,
						}}
					>
						{pct((d.score_pct ?? 0) * count)}
					</div>
					<div style={{fontSize: 56, color: color.text, marginTop: 30, opacity: ramp(frame, NUM_FROM + 24, NUM_FROM + 40)}}>{benchContent.hero}</div>
				</div>
			) : null}
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
	const sorted = [...b.designs].sort((x, y) => (x.usd_per_answer ?? 0) - (y.usd_per_answer ?? 0));
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
			<div style={{position: 'absolute', top: 820, display: 'flex', gap: 28}}>
				{sorted.map((x, i) => {
					const p = ramp(frame, SLAM + 22 + i * 5, SLAM + 34 + i * 5, easeOut);
					return (
						<div
							key={x.name}
							style={{
								opacity: p,
								transform: `translateY(${(1 - p) * 24}px)`,
								padding: '14px 26px',
								borderRadius: 12,
								border: `2px solid ${x.ours ? color.accent : color.line}`,
								background: x.ours ? 'rgba(245,165,36,0.12)' : 'transparent',
								fontSize: 34,
								color: x.ours ? color.accent : color.muted,
								fontWeight: x.ours ? 800 : 500,
								fontVariantNumeric: 'tabular-nums',
							}}
						>
							{usd(x.usd_per_answer ?? 0)} <span style={{fontSize: 26}}>· {x.short ?? x.name}</span>
						</div>
					);
				})}
			</div>
		</AbsoluteFill>
	);
};
