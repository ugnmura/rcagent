import React from 'react';
import {AbsoluteFill, Audio, Freeze, OffthreadVideo, staticFile, useCurrentFrame} from 'remotion';
import {ASSETS, type AssetKey, type ResolvedAssets} from './assets';
import {color, font, size, VIDEO_BOTTOM_RESERVE} from './theme';
import {FPS} from './timeline';

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

export const DialogAudio: React.FC<{assets: ResolvedAssets}> = ({assets}) =>
	assets.dialog.present ? <Audio src={src('dialog')} /> : null;

/** A present recording, muted; holds its last frame when shorter than the slot. */
export const RecordingVideo: React.FC<{assetKey: AssetKey; assets: ResolvedAssets}> = ({assetKey, assets}) => {
	const frame = useCurrentFrame();
	const recFrames = Math.ceil(assets[assetKey].seconds * FPS);
	const video = <OffthreadVideo src={src(assetKey)} muted style={{width: '100%', height: '100%', objectFit: 'contain'}} />;
	return frame < recFrames - 1 ? video : <Freeze frame={recFrames - 2}>{video}</Freeze>;
};
