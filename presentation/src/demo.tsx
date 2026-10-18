// Scene 2b: the live demo. A real Claude Code session with the RCAgent MCP server (demo.mp4, already cut and
// sped up, muted) shown like a screen inside the film, narrated by presenter B's take (s-demo.mp4) in the corner.
import React from 'react';
import {AbsoluteFill, Freeze, interpolate, OffthreadVideo, Sequence, spring, staticFile, useCurrentFrame, useVideoConfig} from 'remotion';
import {ASSETS, type ResolvedAssets} from './assets';
import {BlackFades, easeOut, FilmFacecam, Grain, ramp, SoftPlaceholder, Vignette} from './film';
import {color, font} from './theme';
import {FPS} from './timeline';

/** The terminal panel: 16:9 on the flat dark background, a 2 px line border, no shadow. */
/** Shifted up-left so the corner facecam (bottom right) never covers the recording, even at the end of the push-in. */
const PANEL = {w: 1440, h: 810, radius: 22, dx: -80, dy: -40};
const FADE_FRAMES = 10;
/**
 * s-demo.mp4 is two of Frederick's clips joined at normal speed: slide2-three-commands.mp4 (he introduces the three
 * slash commands /engineer, /team-lead, /manager) then demo-commentary.mp4 (commentary over the /engineer run).
 * INTRO_SECONDS is the exact length of the first clip (ffprobe), TAKE_SECONDS the nominal length of the joined take.
 * During the intro his facecam is full screen; the screen recording starts when the commentary begins.
 */
const INTRO_SECONDS = 21.873197;
const TAKE_SECONDS = 21.873197 + 20.767869;
/** Frames the facecam takes to shrink into the corner once the recording starts. */
const TO_CORNER_FRAMES = 18;

/** The intro length in frames; scaled to the scene length if the take is missing (placeholder timing). */
const introFrames = (assets: ResolvedAssets, frames: number): number => {
	const raw = assets.sDemo.present ? Math.round(INTRO_SECONDS * FPS) : Math.round((INTRO_SECONDS / TAKE_SECONDS) * frames);
	return Math.max(0, Math.min(frames - 1, raw));
};

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
	const intro = introFrames(assets, frames);
	const demoFrames = frames - intro;
	// 0..intro: the three-commands intro, facecam full screen. From intro on: the recording, facecam in the corner.
	const corner = interpolate(frame, [intro, intro + TO_CORNER_FRAMES], [0, 1], {
		extrapolateLeft: 'clamp',
		extrapolateRight: 'clamp',
		easing: easeOut,
	});
	const s = spring({frame: frame - intro, fps, config: {damping: 200}, durationInFrames: 24});
	// The screen settles once and then stays still: no push-in, so the recording reads like a real screen.
	const scale = interpolate(s, [0, 1], [0.9, 1]);
	return (
		<AbsoluteFill style={{backgroundColor: color.bg}}>
			<AbsoluteFill style={{justifyContent: 'center', alignItems: 'center'}}>
				<div
					style={{
						width: PANEL.w,
						height: PANEL.h,
						borderRadius: PANEL.radius,
						overflow: 'hidden',
						background: '#0b0e13',
						border: `2px solid ${color.line}`,
						opacity: s,
						transform: `translate(${PANEL.dx}px, ${PANEL.dy}px) scale(${scale})`,
					}}
				>
					{assets.demo.present ? (
						<Sequence from={intro} durationInFrames={demoFrames} name="recording (after intro)">
							<DemoVideo seconds={assets.demo.seconds} frames={demoFrames} />
						</Sequence>
					) : (
						<SoftPlaceholder
							assetKey="demo"
							note="live demo · Claude Code + RCAgent"
							style={{width: '100%', height: '100%', borderRadius: 'inherit'}}
						/>
					)}
				</div>
			</AbsoluteFill>
			<Sequence from={intro} name="LIVE DEMO tag">
				<DemoTag />
			</Sequence>
			<FilmFacecam assetKey="sDemo" assets={assets} corner={corner} />
			<Vignette strength={0.5} />
			<Grain />
			<BlackFades frames={frames} fadeIn={FADE_FRAMES} fadeOut={FADE_FRAMES} />
		</AbsoluteFill>
	);
};
