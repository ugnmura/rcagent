import React from 'react';
import {Composition} from 'remotion';
import {calculateSlideMetadata, calculateTalkMetadata} from './calculate-metadata';
import {SLIDES, Slide6} from './slides';
import {Talk} from './Talk';
import {FPS, HEIGHT, WIDTH} from './timeline';

export const SLIDE_IDS = SLIDES.map((_, i) => `Slide${i + 1}`);

export const Root: React.FC = () => (
	<>
		<Composition
			id="Talk"
			component={Talk}
			width={WIDTH}
			height={HEIGHT}
			fps={FPS}
			durationInFrames={1}
			defaultProps={{assets: null, scenes: null, benchmarks: null, report: null}}
			calculateMetadata={calculateTalkMetadata}
		/>
		{SLIDES.map((S, i) =>
			S === Slide6 ? (
				<Composition
					key={i}
					id={`Slide${i + 1}`}
					component={Slide6}
					width={WIDTH}
					height={HEIGHT}
					fps={FPS}
					durationInFrames={1}
					defaultProps={{mode: 'print' as const, benchmarks: null}}
					calculateMetadata={calculateSlideMetadata}
				/>
			) : (
				<Composition
					key={i}
					id={`Slide${i + 1}`}
					component={S as React.FC<{mode: 'video' | 'print'}>}
					width={WIDTH}
					height={HEIGHT}
					fps={FPS}
					durationInFrames={1}
					defaultProps={{mode: 'print' as const}}
				/>
			),
		)}
	</>
);
