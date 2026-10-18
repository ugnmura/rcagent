import React from 'react';
import {AbsoluteFill, Series} from 'remotion';
import type {ResolvedAssets} from './assets';
import type {Benchmarks} from './benchmarks';
import type {TalkProps} from './calculate-metadata';
import {MusicBed} from './music';
import {
	BenchmarksScene,
	CloseScene,
	ColdOpenScene,
	IntroScene,
	RevealScene,
	StarScene,
} from './scenes';
import {SplitScene} from './split';
import {type ScenePart, type SceneId} from './timeline';

type SceneProps = {assets: ResolvedAssets; frames: number; benchmarks: Benchmarks | null; parts: ScenePart[]};

const renderScene = (id: SceneId, p: SceneProps): React.ReactNode => {
	switch (id) {
		case 'intro':
			return <IntroScene frames={p.frames} />;
		case 'coldOpen':
			return <ColdOpenScene {...p} />;
		case 'reveal':
			return <RevealScene {...p} />;
		case 'split':
			return <SplitScene assets={p.assets} frames={p.frames} parts={p.parts} />;
		case 'benchmarks':
			return <BenchmarksScene {...p} />;
		case 'close':
			return <CloseScene {...p} />;
		case 'star':
			return <StarScene frames={p.frames} />;
	}
};

export const Talk: React.FC<TalkProps> = ({assets, scenes, benchmarks: b}) => {
	if (!assets || !scenes) {
		return null; // calculateMetadata fills these before anything renders
	}
	return (
		<AbsoluteFill style={{backgroundColor: '#000'}}>
			<Series>
				{scenes.map((s) => (
					<Series.Sequence key={s.id} durationInFrames={s.frames} name={s.label}>
						{renderScene(s.id, {assets, frames: s.frames, benchmarks: b, parts: s.parts ?? []})}
					</Series.Sequence>
				))}
			</Series>
			<MusicBed assets={assets} scenes={scenes} />
		</AbsoluteFill>
	);
};
