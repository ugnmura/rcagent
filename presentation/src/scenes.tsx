// Scenes 1a, 1b and 2 in film style: one idea per shot, push-ins, hard cuts on beats, fades between acts.
import React from 'react';
import {AbsoluteFill, Audio, Freeze, Sequence, spring, staticFile, useCurrentFrame, useVideoConfig} from 'remotion';
import {ASSETS, type AssetKey, type ResolvedAssets} from './assets';
import type {Benchmarks} from './benchmarks';
import {DialogAudio} from './components';
import {coldOpen, DRAMATIZATION_LABEL, reveal} from './content';
import {BarSubtitles, BlackFades, FilmFacecam, Grain, Letterbox, LETTERBOX, NameTag, PushIn, ramp, Vignette} from './film';
import {BenchShot, EndCard, IntroShot, StarShot} from './shots2';
import {CounterShot, FactShot, FlowShot, LogStorm, TitleCaption} from './shots';
import {color, font} from './theme';
import {CLOSE_PARTS, cueFrames, DIALOG_LEAD_SECONDS, END_CARD_SECONDS, FPS, secondsToFrames} from './timeline';

type SceneProps = {assets: ResolvedAssets; frames: number};

const INK = '#030405';

/** Lower-third name tag at a presenter's first appearance: from 1 s into the take, about 3 s. */
const NAME_TAG_FROM = 30;
const NAME_TAG_FRAMES = 90;
const REVEAL_UP_FROM = 24;
const REVEAL_UP_TO = 75;

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

/** The line goes dead: the last 0.4 s of the cold open is a frozen picture and silence after one click. */
const DEAD_LINE_FRAMES = 12;
/** Frames where TitleCaption starts typing its three lines (its default `starts`, src/shots.tsx). */
const TYPE_STARTS = [15, 72, 112];

/** Typewriter ticks as the caption types on, a drone that swells under the call, keyboard taps after the last line; all of it
 * stops dead at `end`, where the click of the hung-up line plays. */
const ColdOpenSfx: React.FC<{end: number}> = ({end}) => {
	const keysFrom = Math.max(0, end - Math.round(3.5 * FPS));
	return (
		<>
			{TYPE_STARTS.map((from, i) => (
				<Sequence key={i} from={from} durationInFrames={Math.round(2 * FPS)}>
					<Audio src={staticFile(`assets/sfx/cold-type-${i + 1}.wav`)} volume={0.5} />
				</Sequence>
			))}
			<Sequence durationInFrames={end}>
				<Audio src={staticFile('assets/sfx/cold-drone.wav')} volume={(f) => 0.8 * Math.min(1, f / 30)} />
			</Sequence>
			<Sequence from={keysFrom} durationInFrames={end - keysFrom}>
				<Audio src={staticFile('assets/sfx/cold-keys.wav')} volume={0.45} />
			</Sequence>
			<Sequence from={end} durationInFrames={DEAD_LINE_FRAMES}>
				<Audio src={staticFile('assets/sfx/cold-click.wav')} volume={1} />
			</Sequence>
		</>
	);
};

export const ColdOpenScene: React.FC<SceneProps> = ({assets, frames}) => {
	const frame = useCurrentFrame();
	const subs: [number, number][] = assets.dialog.present
		? coldOpen.dialogSeconds.map(([a, b]) => [Math.round(a * FPS), Math.round(b * FPS) + 6])
		: cueFrames(
				coldOpen.dialog.map((d) => d.text),
				frames,
				DIALOG_LEAD_SECONDS,
				0.5,
			);
	// The title dims as the storm takes over; a red glow rises at the edges.
	const dim = 1 - 0.45 * ramp(frame, frames * 0.55, frames * 0.8);
	const glow = ramp(frame, frames * 0.3, frames);
	const end = frames - DEAD_LINE_FRAMES;
	return (
		<AbsoluteFill style={{backgroundColor: INK}}>
			<Freeze frame={end - 1} active={frame >= end}>
				<AbsoluteFill>
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
				</AbsoluteFill>
			</Freeze>
			<BlackFades frames={frames} fadeIn={12} />
			<Sequence durationInFrames={end}>
				<DialogAudio assets={assets} />
			</Sequence>
			<ColdOpenSfx end={end} />
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
	// Opens on black after the dead line; the facecam fades up as the narration starts.
	const up = ramp(frame, REVEAL_UP_FROM, REVEAL_UP_TO);
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
			<AbsoluteFill style={{background: '#000', opacity: 1 - up}} />
			<Sequence from={Math.max(NAME_TAG_FROM, REVEAL_UP_TO)} durationInFrames={NAME_TAG_FRAMES} name="name tag">
				<NameTag assetKey="s1" frames={NAME_TAG_FRAMES} />
			</Sequence>
			<BlackFades frames={frames} fadeOut={24} />
		</AbsoluteFill>
	);
};

// ---------------------------------------------------------------- 3 benchmarks

type ShotSpec = {name: string; weight: number; render: (frames: number) => React.ReactNode};

/** Lays shots out between `from` and `to` in proportion to their weights. */
const ShotRun: React.FC<{from: number; to: number; shots: ShotSpec[]}> = ({from, to, shots}) => {
	const sum = shots.reduce((a, s) => a + s.weight, 0);
	let at = from;
	return (
		<>
			{shots.map((s, i) => {
				const end = i === shots.length - 1 ? to : at + Math.round(((to - from) * s.weight) / sum);
				const node = (
					<Shot key={s.name} from={at} to={end} name={s.name}>
						{s.render(end - at)}
					</Shot>
				);
				at = end;
				return node;
			})}
		</>
	);
};

/** A slide-only act: shots over the whole take, facecam in the corner, fades at both ends. */
const ActScene: React.FC<SceneProps & {facecam: AssetKey; shots: ShotSpec[]}> = ({assets, frames, facecam, shots}) => (
	<AbsoluteFill style={{backgroundColor: INK}}>
		<ShotRun from={0} to={frames} shots={shots} />
		<FilmFacecam assetKey={facecam} assets={assets} corner={1} />
		<FilmFinish />
		<BlackFades frames={frames} fadeIn={15} fadeOut={20} />
	</AbsoluteFill>
);

export const BenchmarksScene: React.FC<SceneProps & {benchmarks: Benchmarks | null}> = ({benchmarks, ...p}) => (
	<ActScene {...p} facecam="s6" shots={[{name: 'bars', weight: 1, render: () => <BenchShot benchmarks={benchmarks} />}]} />
);

/**
 * The close. With the joint take s7-close.mp4: facecam full screen, then it shrinks to the corner and the end
 * card shows. Without it: s7-close-a/b/c back to back with hard cuts, each full screen with a small name tag;
 * the end card takes the last part of the final clip (at most END_CARD_SECONDS, at most half of that clip).
 */
export const CloseScene: React.FC<SceneProps> = ({assets, frames}) => {
	const frame = useCurrentFrame();
	const {fps} = useVideoConfig();
	const endCard = Math.round(END_CARD_SECONDS * FPS);
	const joint = assets.s7.present;
	const parts = CLOSE_PARTS.map((key) => ({key, frames: secondsToFrames(assets[key].seconds)}));
	const starts = parts.map((_, i) => parts.slice(0, i).reduce((a, p) => a + p.frames, 0));
	const last = parts[parts.length - 1];
	const lastStart = starts[starts.length - 1];
	const endFrom = joint ? Math.max(0, frames - endCard) : lastStart + last.frames - Math.min(endCard, Math.round(last.frames / 2));
	const corner = spring({frame: frame - endFrom, fps, config: {damping: 200}, durationInFrames: 22});
	return (
		<AbsoluteFill style={{backgroundColor: INK}}>
			<Shot from={endFrom} to={frames} name="end card">
				<EndCard />
			</Shot>
			{joint ? (
				<FilmFacecam assetKey="s7" assets={assets} corner={corner} />
			) : (
				parts.map((p, i) => {
					const isLast = i === parts.length - 1;
					return (
						<Sequence key={p.key} from={starts[i]} durationInFrames={p.frames} name={ASSETS[p.key].file}>
							<FilmFacecam assetKey={p.key} assets={assets} corner={isLast ? corner : 0} />
						</Sequence>
					);
				})
			)}
			<FilmFinish />
			{joint
				? null
				: parts.map((p, i) => (
						<Sequence key={p.key} from={starts[i]} durationInFrames={p.frames} name={`name tag ${p.key}`}>
							<AbsoluteFill style={{opacity: i === parts.length - 1 ? 1 - corner : 1}}>
								<NameTag assetKey={p.key} hold small />
							</AbsoluteFill>
						</Sequence>
					))}
			<BlackFades frames={frames} fadeIn={15} fadeOut={15} />
		</AbsoluteFill>
	);
};

// ---------------------------------------------------------------- bookends

export const IntroScene: React.FC<{frames: number}> = ({frames}) => (
	<AbsoluteFill style={{backgroundColor: '#000'}}>
		<PushIn frames={frames}>
			<IntroShot />
		</PushIn>
		<FilmFinish />
		<BlackFades frames={frames} fadeIn={6} fadeOut={16} />
	</AbsoluteFill>
);

export const StarScene: React.FC<{frames: number}> = ({frames}) => (
	<AbsoluteFill style={{backgroundColor: INK}}>
		<PushIn frames={frames} to={1.03}>
			<StarShot />
		</PushIn>
		<FilmFinish />
		<BlackFades frames={frames} fadeIn={8} fadeOut={18} />
	</AbsoluteFill>
);
