// Optional music bed (public/assets/music.mp3): low, ducked under the voices, fades in and out.
// Missing file = silence; it never shows a placeholder.
import React from 'react';
import {Audio, interpolate, staticFile} from 'remotion';
import {ASSETS, type ResolvedAssets} from './assets';
import {DIALOG_LEAD_SECONDS, FPS, TAKE_PADDING_SECONDS, totalFrames, type SceneTiming} from './timeline';

/** Volume while nobody speaks (rings, chapter cards, the end) and under a voice. */
export const MUSIC_VOLUME = {open: 0.22, ducked: 0.07};
const DUCK_FRAMES = 12;
const FADE_IN_FRAMES = 2 * FPS;
const FADE_OUT_FRAMES = 3 * FPS;

/** [from, to) frames of the talk where a voice speaks. */
const voiceWindows = (scenes: SceneTiming[]): [number, number][] => {
	let at = 0;
	return scenes.map((s) => {
		const lead = Math.round((s.id === 'coldOpen' ? DIALOG_LEAD_SECONDS : TAKE_PADDING_SECONDS) * FPS);
		const tail = Math.round((s.id === 'coldOpen' ? 0.5 : TAKE_PADDING_SECONDS) * FPS);
		const w: [number, number] = s.lengthFrom === null ? [at, at] : [at + lead, at + s.frames - tail];
		at += s.frames;
		return w;
	});
};

export const musicVolume = (frame: number, scenes: SceneTiming[]): number => {
	const duck = voiceWindows(scenes).reduce(
		(acc, [from, to]) =>
			Math.max(acc, Math.min(interpolate(frame, [from - DUCK_FRAMES, from], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'}),
				interpolate(frame, [to, to + DUCK_FRAMES], [1, 0], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'}))),
		0,
	);
	const level = MUSIC_VOLUME.open + (MUSIC_VOLUME.ducked - MUSIC_VOLUME.open) * duck;
	const total = totalFrames(scenes);
	const fade = Math.min(
		interpolate(frame, [0, FADE_IN_FRAMES], [0, 1], {extrapolateRight: 'clamp'}),
		interpolate(frame, [total - FADE_OUT_FRAMES, total], [1, 0], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'}),
	);
	return level * fade;
};

export const MusicBed: React.FC<{assets: ResolvedAssets; scenes: SceneTiming[]}> = ({assets, scenes}) =>
	assets.music.present ? (
		<Audio src={staticFile(`assets/${ASSETS.music.file}`)} loop volume={(f) => musicVolume(f, scenes)} />
	) : null;
