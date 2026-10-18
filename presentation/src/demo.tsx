// Scene 2b: the live demo. A real Claude Code session with the serenedb-extractor MCP server (demo.mp4, already cut and
// sped up, muted) shown like a screen inside the film, narrated by presenter B's take (s-demo.mp4) in the corner.
import React from 'react';
import {AbsoluteFill, Freeze, interpolate, OffthreadVideo, Sequence, spring, staticFile, useCurrentFrame, useVideoConfig} from 'remotion';
import {ASSETS, type ResolvedAssets} from './assets';
import {BlackFades, easeOut, FilmFacecam, Grain, ramp, SoftPlaceholder, Vignette} from './film';
import {color, font} from './theme';
import {FPS} from './timeline';

const INK = '#030405';
/** The terminal panel: 16:9, centred, with room around it for the background to read as a stage. */
/** Shifted up-left so the corner facecam (bottom right) never covers the recording, even at the end of the push-in. */
const PANEL = {w: 1440, h: 810, radius: 22, dx: -80, dy: -40};
const FADE_FRAMES = 10;

const DemoTag: React.FC = () => {
	const frame = useCurrentFrame();
	const o = ramp(frame, 12, 30, easeOut);
	return (
		<div
			style={{
				position: 'absolute',
				top: 40,
				left: 48,
				display: 'flex',
				alignItems: 'center',
				gap: 12,
				fontFamily: font.sans,
				fontSize: 24,
				fontWeight: 800,
				letterSpacing: 3,
				color: color.text,
				opacity: o,
				transform: `translateY(${(1 - o) * -8}px)`,
			}}
		>
			<div style={{width: 12, height: 12, borderRadius: 6, background: color.accent}} />
			LIVE DEMO
		</div>
	);
};

/** demo.mp4, muted (the facecam take is the narration); if it is shorter than the take, its last frame holds. */
const DemoVideo: React.FC<{seconds: number; frames: number}> = ({seconds, frames}) => {
	const videoFrames = Math.max(1, Math.min(frames, Math.floor(seconds * FPS)));
	const src = staticFile(`assets/${ASSETS.demo.file}`);
	const style: React.CSSProperties = {width: '100%', height: '100%', objectFit: 'cover'};
	return (
		<>
			<Sequence durationInFrames={videoFrames} name="demo.mp4">
				<OffthreadVideo src={src} muted style={style} />
			</Sequence>
			{frames > videoFrames ? (
				<Sequence from={videoFrames} durationInFrames={frames - videoFrames} name="hold last frame">
					<Freeze frame={videoFrames - 1}>
						<OffthreadVideo src={src} muted style={style} />
					</Freeze>
				</Sequence>
			) : null}
		</>
	);
};

export const DemoScene: React.FC<{assets: ResolvedAssets; frames: number}> = ({assets, frames}) => {
	const frame = useCurrentFrame();
	const {fps} = useVideoConfig();
	const s = spring({frame, fps, config: {damping: 200}, durationInFrames: 24});
	const scale = interpolate(s, [0, 1], [0.9, 1]) * interpolate(frame, [0, Math.max(1, frames)], [1, 1.04], {extrapolateRight: 'clamp'});
	return (
		<AbsoluteFill style={{background: `radial-gradient(ellipse 80% 75% at 50% 45%, #1a2130 0%, #0b0f16 55%, ${INK} 100%)`}}>
			<AbsoluteFill style={{justifyContent: 'center', alignItems: 'center'}}>
				<div
					style={{
						width: PANEL.w,
						height: PANEL.h,
						borderRadius: PANEL.radius,
						overflow: 'hidden',
						background: '#0b0e13',
						border: `1px solid ${color.line}`,
						boxShadow: '0 30px 80px rgba(0,0,0,0.55), 0 8px 24px rgba(0,0,0,0.4)',
						opacity: s,
						transform: `translate(${PANEL.dx}px, ${PANEL.dy}px) scale(${scale})`,
					}}
				>
					{assets.demo.present ? (
						<DemoVideo seconds={assets.demo.seconds} frames={frames} />
					) : (
						<SoftPlaceholder
							assetKey="demo"
							note="live demo · Claude Code + serenedb-extractor"
							style={{width: '100%', height: '100%', borderRadius: 'inherit'}}
						/>
					)}
				</div>
			</AbsoluteFill>
			<DemoTag />
			<FilmFacecam assetKey="sDemo" assets={assets} corner={1} />
			<Vignette strength={0.5} />
			<Grain />
			<BlackFades frames={frames} fadeIn={FADE_FRAMES} fadeOut={FADE_FRAMES} />
		</AbsoluteFill>
	);
};
