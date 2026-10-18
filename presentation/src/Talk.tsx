import React from 'react';
import {AbsoluteFill, interpolate, Sequence, Series, useCurrentFrame} from 'remotion';
import type {AssetKey, ResolvedAssets} from './assets';
import type {Benchmarks} from './benchmarks';
import type {TalkProps} from './calculate-metadata';
import {DialogAudio, Facecam, Recording, Subtitles, type FacecamLayout} from './components';
import {benchmarks, close, coldOpen, engineer, evidence, manager, reveal, teamLead} from './content';
import {
	ColdOpenCaption,
	DramatizationLabel,
	FlowLine,
	RevealHeadline,
	Slide2,
	Slide3,
	Slide4,
	Slide5,
	Slide6,
	Slide7,
} from './slides';
import {color, font} from './theme';
import {cueFrames, DIALOG_LEAD_SECONDS, END_CARD_SECONDS, FPS, SLIDE_SECONDS, type SceneId} from './timeline';

type SceneProps = {assets: ResolvedAssets; frames: number; benchmarks: Benchmarks | null};

const textCues = (cues: readonly string[]) => cues.map((text) => ({text}));

// ---------------------------------------------------------------- 1a
const ColdOpen: React.FC<SceneProps> = ({assets, frames}) => (
	<AbsoluteFill style={{backgroundColor: '#05070a', fontFamily: font.sans, color: color.text}}>
		<AbsoluteFill style={{justifyContent: 'center', alignItems: 'center', paddingBottom: 160}}>
			<ColdOpenCaption />
		</AbsoluteFill>
		<DramatizationLabel />
		<DialogAudio assets={assets} />
		{assets.dialog.present ? null : (
			<div style={{position: 'absolute', left: 40, top: 36, fontSize: 26, color: color.placeholder, fontWeight: 700}}>
				PLACEHOLDER: dialog.mp3 (audio, 18–24 s) is missing
			</div>
		)}
		<Subtitles cues={coldOpen.dialog} sceneFrames={frames} lead={DIALOG_LEAD_SECONDS} tail={0.5} />
	</AbsoluteFill>
);

// ---------------------------------------------------------------- 1b
const Reveal: React.FC<SceneProps> = ({assets, frames}) => {
	const frame = useCurrentFrame();
	const timing = cueFrames(reveal.cues, frames);
	const headlineFrom = timing[reveal.headlineFromCue][0];
	const flowFrom = timing[reveal.flowFromCue][0];
	const layout: FacecamLayout = frame < headlineFrom ? 'full' : 'corner';
	const fade = (from: number) => interpolate(frame, [from, from + 12], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
	return (
		<AbsoluteFill style={{backgroundColor: color.bg, fontFamily: font.sans, color: color.text}}>
			<AbsoluteFill style={{justifyContent: 'center', alignItems: 'center', gap: 110, paddingBottom: 200}}>
				<div style={{opacity: fade(headlineFrom)}}>
					<RevealHeadline />
				</div>
				<div style={{opacity: fade(flowFrom)}}>
					<FlowLine />
				</div>
			</AbsoluteFill>
			<Facecam assetKey="s1" assets={assets} layout={layout} />
			<Subtitles cues={textCues(reveal.cues)} sceneFrames={frames} />
		</AbsoluteFill>
	);
};

// ---------------------------------------------------------------- 2–4: slide, then recording
const SlideThenRecording: React.FC<
	SceneProps & {
		facecam: AssetKey;
		recording: AssetKey;
		splitSeconds: number;
		slide: React.ReactNode;
		cues: readonly string[];
		prompt: string;
		cue: string;
	}
> = ({assets, frames, facecam, recording, splitSeconds, slide, cues, prompt, cue}) => {
	const split = Math.min(frames - 1, Math.round(splitSeconds * FPS));
	return (
		<AbsoluteFill style={{backgroundColor: color.bg}}>
			<Sequence durationInFrames={split} name="slide">
				{slide}
			</Sequence>
			<Sequence from={split} durationInFrames={frames - split} name="recording">
				<Recording assetKey={recording} assets={assets} frames={frames - split} prompt={prompt} cue={cue} mode="video" />
			</Sequence>
			<Facecam assetKey={facecam} assets={assets} layout="corner" />
			<Subtitles cues={textCues(cues)} sceneFrames={frames} />
		</AbsoluteFill>
	);
};

const SlideOnly: React.FC<SceneProps & {facecam: AssetKey; slide: React.ReactNode; cues: readonly string[]}> = ({
	assets,
	frames,
	facecam,
	slide,
	cues,
}) => (
	<AbsoluteFill>
		{slide}
		<Facecam assetKey={facecam} assets={assets} layout="corner" />
		<Subtitles cues={textCues(cues)} sceneFrames={frames} />
	</AbsoluteFill>
);

// ---------------------------------------------------------------- 7
const Close: React.FC<SceneProps> = ({assets, frames}) => {
	const frame = useCurrentFrame();
	const endFrom = Math.max(0, frames - Math.round(END_CARD_SECONDS * FPS));
	const opacity = interpolate(frame, [endFrom, endFrom + 15], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
	return (
		<AbsoluteFill style={{backgroundColor: color.bg}}>
			<AbsoluteFill style={{opacity}}>
				<Slide7 mode="video" />
			</AbsoluteFill>
			<Facecam assetKey="s7" assets={assets} layout={frame < endFrom ? 'full' : 'corner'} />
			<Subtitles cues={textCues(close.cues)} sceneFrames={frames} />
		</AbsoluteFill>
	);
};

const renderScene = (id: SceneId, p: SceneProps): React.ReactNode => {
	switch (id) {
		case 'coldOpen':
			return <ColdOpen {...p} />;
		case 'reveal':
			return <Reveal {...p} />;
		case 'engineer':
			return (
				<SlideThenRecording
					{...p}
					facecam="s2"
					recording="engineerRec"
					splitSeconds={SLIDE_SECONDS.engineer}
					slide={<Slide2 mode="video" />}
					cues={engineer.cues}
					prompt={engineer.prompt}
					cue={engineer.recordingCue}
				/>
			);
		case 'teamLead':
			return (
				<SlideThenRecording
					{...p}
					facecam="s3"
					recording="teamLeadRec"
					splitSeconds={SLIDE_SECONDS.teamLead}
					slide={<Slide3 mode="video" />}
					cues={teamLead.cues}
					prompt={teamLead.prompt}
					cue={teamLead.recordingCue}
				/>
			);
		case 'manager':
			return (
				<SlideThenRecording
					{...p}
					facecam="s4"
					recording="managerRec"
					splitSeconds={SLIDE_SECONDS.manager}
					slide={<Slide4 mode="video" />}
					cues={manager.cues}
					prompt={manager.prompt}
					cue={manager.recordingCue}
				/>
			);
		case 'evidence':
			return <SlideOnly {...p} facecam="s5" slide={<Slide5 mode="video" />} cues={evidence.cues} />;
		case 'benchmarks':
			return (
				<SlideOnly
					{...p}
					facecam="s6"
					slide={<Slide6 mode="video" benchmarks={p.benchmarks} />}
					cues={benchmarks.cues}
				/>
			);
		case 'close':
			return <Close {...p} />;
	}
};

export const Talk: React.FC<TalkProps> = ({assets, scenes, benchmarks: b}) => {
	if (!assets || !scenes) {
		return null; // calculateMetadata fills these before anything renders
	}
	return (
		<AbsoluteFill style={{backgroundColor: color.bg}}>
			<Series>
				{scenes.map((s) => (
					<Series.Sequence key={s.id} durationInFrames={s.frames} name={s.label}>
						{renderScene(s.id, {assets, frames: s.frames, benchmarks: b})}
					</Series.Sequence>
				))}
			</Series>
		</AbsoluteFill>
	);
};
