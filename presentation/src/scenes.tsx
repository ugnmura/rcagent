// Scenes 1a, 1b and 2 in film style: one idea per shot, push-ins, hard cuts on beats, fades between acts.
import React from 'react';
import {AbsoluteFill, Sequence, spring, useCurrentFrame, useVideoConfig, interpolate} from 'remotion';
import type {ResolvedAssets} from './assets';
import {DialogAudio, RecordingVideo} from './components';
import {coldOpen, DRAMATIZATION_LABEL, engineer, reveal} from './content';
import {BarSubtitles, BlackFades, ChapterCard, FilmFacecam, Grain, Letterbox, LETTERBOX, PushIn, ramp, SoftPlaceholder, Vignette} from './film';
import {CounterShot, FactShot, FloodShot, FlowShot, LogStorm, NodeShot, RingShot, TitleCaption} from './shots';
import {color, font} from './theme';
import {cueFrames, DIALOG_LEAD_SECONDS, FPS, SLIDE_SECONDS} from './timeline';

type SceneProps = {assets: ResolvedAssets; frames: number};

const INK = '#030405';

/** A shot: its own Sequence (local frames) with a slow push-in. */
const Shot: React.FC<{from: number; to: number; name: string; children: React.ReactNode}> = ({from, to, name, children}) =>
	to > from ? (
		<Sequence from={from} durationInFrames={to - from} name={name}>
			<PushIn frames={to - from}>{children}</PushIn>
		</Sequence>
	) : null;

const FilmFinish: React.FC<{vignette?: number; tint?: string}> = ({vignette, tint}) => (
	<>
		<Vignette strength={vignette} tint={tint} />
		<Grain />
	</>
);

// ---------------------------------------------------------------- 1a cold open

export const DramatizationTag: React.FC<{top?: number}> = ({top = (LETTERBOX - 44) / 2}) => (
	<div
		style={{
			position: 'absolute',
			top,
			right: 48,
			fontFamily: font.sans,
			fontSize: 24,
			fontWeight: 600,
			color: '#d0d7de',
			border: '1px solid rgba(208,215,222,0.35)',
			borderRadius: 8,
			padding: '8px 14px',
		}}
	>
		{DRAMATIZATION_LABEL}
	</div>
);

export const ColdOpenScene: React.FC<SceneProps> = ({assets, frames}) => {
	const frame = useCurrentFrame();
	const subs = cueFrames(
		coldOpen.dialog.map((d) => d.text),
		frames,
		DIALOG_LEAD_SECONDS,
		0.5,
	);
	// The title dims as the storm takes over; a red glow rises at the edges.
	const dim = 1 - 0.45 * ramp(frame, frames * 0.55, frames * 0.8);
	const glow = ramp(frame, frames * 0.3, frames);
	return (
		<AbsoluteFill style={{backgroundColor: INK}}>
			<PushIn frames={frames}>
				<LogStorm frames={frames} />
				<AbsoluteFill style={{background: 'linear-gradient(90deg, rgba(3,4,5,0.92) 0%, rgba(3,4,5,0.6) 55%, rgba(3,4,5,0) 100%)'}} />
				<AbsoluteFill style={{justifyContent: 'center', paddingLeft: 170, opacity: dim}}>
					<TitleCaption />
				</AbsoluteFill>
			</PushIn>
			<FilmFinish vignette={0.55 + 0.25 * glow} tint={`${Math.round(90 * glow)},0,0`} />
			<Letterbox />
			<DramatizationTag />
			{assets.dialog.present ? null : (
				<div style={{position: 'absolute', left: 48, top: (LETTERBOX - 30) / 2, fontFamily: font.sans, fontSize: 22, fontWeight: 700, color: color.placeholder}}>
					PLACEHOLDER · dialog.mp3 (audio, 18–24 s) is missing
				</div>
			)}
			<BarSubtitles cues={coldOpen.dialog} timing={subs} />
			<BlackFades frames={frames} fadeIn={12} fadeOut={24} />
			<DialogAudio assets={assets} />
		</AbsoluteFill>
	);
};

// ---------------------------------------------------------------- 1b reveal

export const RevealScene: React.FC<SceneProps> = ({assets, frames}) => {
	const frame = useCurrentFrame();
	const {fps} = useVideoConfig();
	const timing = cueFrames(reveal.cues, frames);
	const counterFrom = timing[reveal.headlineFromCue][0];
	const factFrom = timing[reveal.factFromCue][0];
	const flowFrom = timing[reveal.flowFromCue][0];
	const corner = spring({frame: frame - counterFrom, fps, config: {damping: 200}, durationInFrames: 22});
	return (
		<AbsoluteFill style={{backgroundColor: INK}}>
			<Shot from={counterFrom} to={factFrom} name="counter">
				<CounterShot />
			</Shot>
			<Shot from={factFrom} to={flowFrom} name="4.7 million">
				<FactShot />
			</Shot>
			<Shot from={flowFrom} to={frames} name="flow line">
				<FlowShot />
			</Shot>
			<FilmFacecam assetKey="s1" assets={assets} corner={corner} />
			<FilmFinish />
			<BlackFades frames={frames} fadeIn={18} fadeOut={24} />
		</AbsoluteFill>
	);
};

// ---------------------------------------------------------------- 2 engineer

/** The recording slot zooms in like a screen inside the film. */
const ScreenInFilm: React.FC<SceneProps> = ({assets, frames}) => {
	const frame = useCurrentFrame();
	const {fps} = useVideoConfig();
	const s = spring({frame, fps, config: {damping: 200}, durationInFrames: 40});
	const scale = interpolate(s, [0, 1], [0.6, 0.8]) * interpolate(frame, [0, frames], [1, 1.04], {extrapolateRight: 'clamp'});
	const present = assets.engineerRec.present;
	return (
		<AbsoluteFill style={{background: 'radial-gradient(ellipse at 50% 45%, #141a22 0%, #030405 70%)'}}>
			<AbsoluteFill style={{transform: `translate(-64px, -34px) scale(${scale})`, opacity: ramp(frame, 0, 10)}}>
				<AbsoluteFill
					style={{
						borderRadius: 22,
						overflow: 'hidden',
						background: '#000',
						boxShadow: '0 40px 140px rgba(0,0,0,0.85), 0 0 0 3px #2a313a',
					}}
				>
					{present ? (
						<RecordingVideo assetKey="engineerRec" assets={assets} />
					) : (
						<SoftPlaceholder
							assetKey="engineerRec"
							note={`screen recording · slot ${(frames / FPS).toFixed(1)} s`}
							detail={`${engineer.prompt}\n${engineer.recordingCue}`}
							style={{width: '100%', height: '100%', fontSize: 30}}
						/>
					)}
				</AbsoluteFill>
			</AbsoluteFill>
		</AbsoluteFill>
	);
};

const CHAPTER_FRAMES = 78;

export const EngineerScene: React.FC<SceneProps> = ({assets, frames}) => {
	const frame = useCurrentFrame();
	const split = Math.min(frames - 1, Math.round(SLIDE_SECONDS.engineer * FPS));
	const rest = split - CHAPTER_FRAMES;
	const nodeTo = CHAPTER_FRAMES + Math.round(rest * 0.24);
	const ringTo = nodeTo + Math.round(rest * 0.34);
	const facecam = ramp(frame, CHAPTER_FRAMES - 6, CHAPTER_FRAMES + 12);
	return (
		<AbsoluteFill style={{backgroundColor: INK}}>
			<Sequence durationInFrames={CHAPTER_FRAMES} name="chapter card">
				<ChapterCard title={engineer.chapter.title} question={engineer.chapter.question} frames={CHAPTER_FRAMES} />
			</Sequence>
			<Shot from={CHAPTER_FRAMES} to={nodeTo} name="node">
				<NodeShot />
			</Shot>
			<Shot from={nodeTo} to={ringTo} name="17.8% ring">
				<RingShot />
			</Shot>
			<Shot from={ringTo} to={split} name="L2, then the flood">
				<FloodShot frames={split - ringTo} />
			</Shot>
			<Sequence from={split} durationInFrames={frames - split} name="recording">
				<ScreenInFilm assets={assets} frames={frames - split} />
			</Sequence>
			<FilmFacecam assetKey="s2" assets={assets} corner={1} opacity={facecam} />
			<FilmFinish />
			<BlackFades frames={frames} fadeOut={20} />
		</AbsoluteFill>
	);
};
