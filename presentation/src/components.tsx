import React from 'react';
import {AbsoluteFill, Audio, Freeze, OffthreadVideo, staticFile, useCurrentFrame} from 'remotion';
import {ASSETS, type AssetKey, type ResolvedAssets} from './assets';
import {color, FACECAM_CORNER, font, size, VIDEO_BOTTOM_RESERVE} from './theme';
import {cueFrames, FPS} from './timeline';

export type Mode = 'video' | 'print';

const src = (key: AssetKey) => staticFile(`assets/${ASSETS[key].file}`);

/** Full-frame slide shell: dark background, title, content area that keeps clear of subtitles in the video. */
export const SlideFrame: React.FC<{title?: string; mode: Mode; children: React.ReactNode}> = ({title, mode, children}) => (
	<AbsoluteFill
		style={{
			backgroundColor: color.bg,
			color: color.text,
			fontFamily: font.sans,
			padding: `56px 96px ${mode === 'video' ? VIDEO_BOTTOM_RESERVE : 96}px`,
			display: 'flex',
			flexDirection: 'column',
		}}
	>
		{title ? (
			<div style={{fontSize: size.title, fontWeight: 800, letterSpacing: -1, marginBottom: 28}}>{title}</div>
		) : null}
		<div style={{flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0}}>{children}</div>
	</AbsoluteFill>
);

/** Labelled stand-in for a missing asset. */
export const Placeholder: React.FC<{
	assetKey: AssetKey;
	note?: string;
	detail?: string;
	style?: React.CSSProperties;
	compact?: boolean;
}> = ({assetKey, note, detail, style, compact}) => {
	const a = ASSETS[assetKey];
	return (
		<div
			style={{
				border: `4px dashed ${color.placeholder}`,
				background: 'rgba(255,92,138,0.08)',
				color: color.text,
				fontFamily: font.sans,
				display: 'flex',
				flexDirection: 'column',
				alignItems: 'center',
				justifyContent: 'center',
				textAlign: 'center',
				gap: compact ? 4 : 16,
				padding: compact ? 8 : 40,
				boxSizing: 'border-box',
				...style,
			}}
		>
			<div style={{fontSize: compact ? 20 : 30, fontWeight: 800, color: color.placeholder, letterSpacing: 2}}>
				PLACEHOLDER
			</div>
			<div style={{fontSize: compact ? 17 : 44, fontWeight: 600, fontFamily: font.mono}}>{a.file}</div>
			<div style={{fontSize: compact ? 18 : 32, color: color.muted}}>
				{note ?? a.kind} · target {a.target}
			</div>
			{detail && !compact ? <div style={{fontSize: 30, color: color.muted, maxWidth: 1300}}>{detail}</div> : null}
		</div>
	);
};

export type FacecamLayout = 'full' | 'corner' | 'hidden';

/**
 * The presenter's take: always mounted for the whole scene so its audio (the narration) never restarts;
 * only its frame moves between full screen and the corner.
 */
export const Facecam: React.FC<{assetKey: AssetKey; assets: ResolvedAssets; layout: FacecamLayout}> = ({
	assetKey,
	assets,
	layout,
}) => {
	const {size: d, margin} = FACECAM_CORNER;
	const frameStyle: React.CSSProperties =
		layout === 'full'
			? {position: 'absolute', inset: 0, width: '100%', height: '100%'}
			: {
					position: 'absolute',
					right: margin,
					bottom: margin,
					width: d,
					height: d,
					borderRadius: '50%',
					overflow: 'hidden',
					border: `4px solid ${color.text}`,
					boxShadow: '0 8px 30px rgba(0,0,0,0.6)',
					opacity: layout === 'hidden' ? 0 : 1,
				};
	if (!assets[assetKey].present) {
		return (
			<div style={frameStyle}>
				<Placeholder
					assetKey={assetKey}
					note="facecam + narration"
					compact={layout !== 'full'}
					style={{width: '100%', height: '100%', borderRadius: layout === 'full' ? 0 : '50%', background: color.panel}}
				/>
			</div>
		);
	}
	return (
		<div style={frameStyle}>
			<OffthreadVideo src={src(assetKey)} style={{width: '100%', height: '100%', objectFit: 'cover'}} />
		</div>
	);
};

export const DialogAudio: React.FC<{assets: ResolvedAssets}> = ({assets}) =>
	assets.dialog.present ? <Audio src={src('dialog')} /> : null;

/**
 * Screen recording that fills `frames`. A recording shorter than the slot holds its last frame; a longer one
 * is cut (the check warns).
 */
export const Recording: React.FC<{
	assetKey: AssetKey;
	assets: ResolvedAssets;
	frames: number;
	prompt: string;
	cue: string;
	mode: Mode;
}> = ({assetKey, assets, frames, prompt, cue, mode}) => {
	const frame = useCurrentFrame();
	const box: React.CSSProperties = {
		position: 'absolute',
		left: 96,
		right: 96,
		top: 56,
		bottom: mode === 'video' ? VIDEO_BOTTOM_RESERVE - 20 : 56,
	};
	if (!assets[assetKey].present) {
		return (
			<AbsoluteFill style={{backgroundColor: color.bg}}>
				<Placeholder
					assetKey={assetKey}
					note={`screen recording · slot ${(frames / FPS).toFixed(1)} s`}
					detail={`${prompt}\n${cue}`}
					style={{...box, whiteSpace: 'pre-wrap'}}
				/>
			</AbsoluteFill>
		);
	}
	const recFrames = Math.ceil(assets[assetKey].seconds * FPS);
	const video = <OffthreadVideo src={src(assetKey)} muted style={{width: '100%', height: '100%', objectFit: 'contain'}} />;
	return (
		<AbsoluteFill style={{backgroundColor: '#000'}}>
			{frame < recFrames - 1 ? video : <Freeze frame={recFrames - 2}>{video}</Freeze>}
		</AbsoluteFill>
	);
};

/** Bottom-centre subtitles; cues share the scene by length (see cueFrames). */
export const Subtitles: React.FC<{
	cues: readonly {speaker?: string; text: string}[];
	sceneFrames: number;
	lead?: number;
	tail?: number;
}> = ({cues, sceneFrames, lead, tail}) => {
	const frame = useCurrentFrame();
	const timing = cueFrames(
		cues.map((c) => c.text),
		sceneFrames,
		lead,
		tail,
	);
	const i = timing.findIndex(([from, to]) => frame >= from && frame < to);
	if (i < 0) {
		return null;
	}
	const cue = cues[i];
	return (
		<AbsoluteFill style={{justifyContent: 'flex-end', alignItems: 'center', paddingBottom: 56, pointerEvents: 'none'}}>
			<div
				style={{
					maxWidth: 1240,
					background: 'rgba(0,0,0,0.82)',
					color: '#fff',
					fontFamily: font.sans,
					fontSize: size.subtitle,
					fontWeight: 600,
					lineHeight: 1.25,
					padding: '14px 28px',
					borderRadius: 12,
					textAlign: 'center',
				}}
			>
				{cue.speaker ? <span style={{color: color.accent}}>{cue.speaker}: </span> : null}
				{cue.text}
			</div>
		</AbsoluteFill>
	);
};

/** Frame from which cue `index` shows. */
export const useCueStart = (cues: readonly string[], index: number, sceneFrames: number) =>
	cueFrames(cues, sceneFrames)[index][0];
