// Film language shared by the redesigned scenes: grain, vignette, letterbox, push-in, fades, typewriter,
// the moving facecam frame, chapter cards and quiet placeholders.
import React from 'react';
import {AbsoluteFill, Easing, interpolate, OffthreadVideo, spring, staticFile, useCurrentFrame, useVideoConfig} from 'remotion';
import {ASSETS, type AssetKey, type ResolvedAssets} from './assets';
import {color, FACECAM_CORNER, font} from './theme';

const clamp = {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'} as const;
export const ease = Easing.bezier(0.45, 0, 0.2, 1);
export const easeOut = Easing.bezier(0.16, 1, 0.3, 1);

/** 0→1 between two frames, eased. */
export const ramp = (frame: number, from: number, to: number, easing = ease) =>
	interpolate(frame, [from, to], [0, 1], {...clamp, easing});

/** Letterbox bar height for 2.39:1 inside 1920×1080. */
export const LETTERBOX = Math.round((1080 - 1920 / 2.39) / 2);

export const Letterbox: React.FC = () => (
	<>
		<div style={{position: 'absolute', left: 0, right: 0, top: 0, height: LETTERBOX, background: '#000'}} />
		<div style={{position: 'absolute', left: 0, right: 0, bottom: 0, height: LETTERBOX, background: '#000'}} />
	</>
);

/** Fine animated film grain (fractal noise re-seeded every frame), drawn at half resolution. */
export const Grain: React.FC<{opacity?: number}> = ({opacity = 0.055}) => {
	const frame = useCurrentFrame();
	return (
		<AbsoluteFill style={{pointerEvents: 'none', opacity}}>
			<svg width="100%" height="100%" viewBox="0 0 960 540" preserveAspectRatio="none">
				<filter id="film-grain">
					<feTurbulence type="fractalNoise" baseFrequency="0.85" numOctaves={2} seed={frame % 24} stitchTiles="stitch" />
					<feColorMatrix type="saturate" values="0" />
				</filter>
				<rect width="100%" height="100%" filter="url(#film-grain)" />
			</svg>
		</AbsoluteFill>
	);
};

export const Vignette: React.FC<{strength?: number; tint?: string}> = ({strength = 0.6, tint = '0,0,0'}) => (
	<AbsoluteFill
		style={{
			pointerEvents: 'none',
			background: `radial-gradient(ellipse 75% 70% at 50% 50%, rgba(${tint},0) 55%, rgba(${tint},${strength}) 100%)`,
		}}
	/>
);

/** Slow push-in over the whole shot: scale 1.00 → 1.05. */
export const PushIn: React.FC<{frames: number; children: React.ReactNode; to?: number}> = ({frames, children, to = 1.05}) => {
	const frame = useCurrentFrame();
	const scale = interpolate(frame, [0, Math.max(1, frames)], [1, to], clamp);
	return <AbsoluteFill style={{transform: `scale(${scale})`}}>{children}</AbsoluteFill>;
};

/** Black overlay: fade from black at the start, to black at the end of `frames`. */
export const BlackFades: React.FC<{frames: number; fadeIn?: number; fadeOut?: number}> = ({frames, fadeIn = 0, fadeOut = 0}) => {
	const frame = useCurrentFrame();
	const a = fadeIn > 0 ? 1 - ramp(frame, 0, fadeIn) : 0;
	const b = fadeOut > 0 ? ramp(frame, frames - fadeOut, frames) : 0;
	return <AbsoluteFill style={{background: '#000', opacity: Math.max(a, b), pointerEvents: 'none'}} />;
};

/** Text that types on from frame `start` at `cps` characters per second, with a blinking caret while typing. */
export const Typewriter: React.FC<{text: string; start: number; cps?: number; style?: React.CSSProperties; done?: boolean}> = ({
	text,
	start,
	cps = 24,
	style,
	done,
}) => {
	const frame = useCurrentFrame();
	const {fps} = useVideoConfig();
	const n = done ? text.length : Math.max(0, Math.min(text.length, Math.floor(((frame - start) * cps) / fps)));
	const typing = !done && frame >= start && n < text.length;
	const caretOn = typing || (!done && frame >= start && frame - start < (text.length / cps) * fps + 20 && Math.floor(frame / 8) % 2 === 0);
	return (
		<div style={{whiteSpace: 'pre', ...style}}>
			{text.slice(0, n)}
			<span style={{opacity: caretOn ? 0.9 : 0, color: color.accent}}>▍</span>
		</div>
	);
};

/** A quiet stand-in for a missing asset: dark, thin dashed pink outline, small but readable label. */
export const SoftPlaceholder: React.FC<{assetKey: AssetKey; note: string; detail?: string; compact?: boolean; style?: React.CSSProperties}> = ({
	assetKey,
	note,
	detail,
	compact,
	style,
}) => {
	const a = ASSETS[assetKey];
	return (
		<div
			style={{
				border: `${compact ? 3 : 2}px dashed ${color.placeholder}`,
				background: '#0b0e13',
				color: color.muted,
				fontFamily: font.sans,
				display: 'flex',
				flexDirection: 'column',
				alignItems: 'center',
				justifyContent: 'center',
				textAlign: 'center',
				gap: compact ? 2 : 10,
				padding: compact ? 8 : 32,
				boxSizing: 'border-box',
				...style,
			}}
		>
			<div style={{fontSize: compact ? 15 : 22, fontWeight: 800, color: color.placeholder, letterSpacing: 3}}>PLACEHOLDER</div>
			<div style={{fontSize: compact ? 15 : 30, fontWeight: 600, fontFamily: font.mono, color: color.text}}>{a.file}</div>
			{compact ? null : (
				<div style={{fontSize: 22}}>
					{note} · target {a.target}
				</div>
			)}
			{detail && !compact ? <div style={{fontSize: 22, maxWidth: 1100, whiteSpace: 'pre-wrap'}}>{detail}</div> : null}
		</div>
	);
};

/**
 * The presenter's take, mounted for the whole scene (its audio is the narration). `corner` moves the frame
 * between full screen (0) and the small round corner frame (1); `opacity` hides it without stopping the audio.
 */
export const FilmFacecam: React.FC<{assetKey: AssetKey; assets: ResolvedAssets; corner: number; opacity?: number}> = ({
	assetKey,
	assets,
	corner,
	opacity = 1,
}) => {
	const d = 200;
	const m = FACECAM_CORNER.margin;
	const mix = (a: number, b: number) => a + (b - a) * corner;
	const box: React.CSSProperties = {
		position: 'absolute',
		left: mix(0, 1920 - m - d),
		top: mix(0, 1080 - m - d),
		width: mix(1920, d),
		height: mix(1080, d),
		borderRadius: mix(0, d / 2),
		overflow: 'hidden',
		opacity,
		boxShadow: corner > 0.5 ? '0 10px 40px rgba(0,0,0,0.7)' : undefined,
		outline: corner > 0.98 ? '3px solid rgba(230,237,243,0.85)' : undefined,
	};
	if (!assets[assetKey].present) {
		return (
			<div style={box}>
				<SoftPlaceholder
					assetKey={assetKey}
					note="facecam + narration"
					compact={corner > 0.5}
					style={{width: '100%', height: '100%', borderRadius: 'inherit'}}
				/>
			</div>
		);
	}
	return (
		<div style={box}>
			<OffthreadVideo src={staticFile(`assets/${ASSETS[assetKey].file}`)} style={{width: '100%', height: '100%', objectFit: 'cover'}} />
		</div>
	);
};

/** Chapter card before a role: a thin line draws, the title settles, the question follows. */
export const ChapterCard: React.FC<{title: string; question: string; frames: number}> = ({title, question, frames}) => {
	const frame = useCurrentFrame();
	const {fps} = useVideoConfig();
	const s = spring({frame: frame - 4, fps, config: {damping: 200}, durationInFrames: 30});
	const line = ramp(frame, 0, 24, easeOut);
	const q = ramp(frame, 22, 40);
	const out = 1 - ramp(frame, frames - 12, frames);
	return (
		<AbsoluteFill style={{background: '#000', justifyContent: 'center', alignItems: 'center', fontFamily: font.sans, opacity: out}}>
			<div style={{width: 120 * line, height: 3, background: color.accent, marginBottom: 36}} />
			<div
				style={{
					fontSize: 120,
					fontWeight: 300,
					color: color.text,
					letterSpacing: `${interpolate(s, [0, 1], [0.3, 0.02])}em`,
					opacity: s,
				}}
			>
				{title}
			</div>
			<div style={{fontSize: 40, color: color.muted, marginTop: 28, opacity: q, transform: `translateY(${(1 - q) * 12}px)`}}>
				{question}
			</div>
		</AbsoluteFill>
	);
};

/** Subtitles inside the bottom letterbox bar (only for voices without a facecam). */
export const BarSubtitles: React.FC<{cues: readonly {speaker?: string; text: string}[]; timing: [number, number][]}> = ({cues, timing}) => {
	const frame = useCurrentFrame();
	const i = timing.findIndex(([from, to]) => frame >= from && frame < to);
	if (i < 0) {
		return null;
	}
	const [from, to] = timing[i];
	const o = Math.min(ramp(frame, from, from + 6), 1 - ramp(frame, to - 6, to));
	const cue = cues[i];
	return (
		<div
			style={{
				position: 'absolute',
				left: 0,
				right: 0,
				bottom: 0,
				height: LETTERBOX,
				display: 'flex',
				alignItems: 'center',
				justifyContent: 'center',
				pointerEvents: 'none',
			}}
		>
			<div
				style={{
					maxWidth: 1500,
					fontFamily: font.sans,
					fontSize: 36,
					fontWeight: 600,
					lineHeight: 1.25,
					color: '#fff',
					textAlign: 'center',
					opacity: o,
				}}
			>
				{cue.speaker ? <span style={{color: color.accent}}>{cue.speaker}: </span> : null}
				{cue.text}
			</div>
		</div>
	);
};
