import React from 'react';
import {AbsoluteFill} from 'remotion';
import type {Benchmarks} from '../benchmarks';
import {SlideFrame, type Mode} from '../components';
import {DONE_TIMES, SplitBoard} from '../split';
import {DramatizationTag} from '../scenes';
import {FlowShot, TitleCaption} from '../shots';
import {BenchShot, CitationShot, LogoPair, SnapShot} from '../shots2';
import {close, evidence, REPO_URL, reveal} from '../content';
import {color, font} from '../theme';

const Mono: React.FC<{children: React.ReactNode; style?: React.CSSProperties}> = ({children, style}) => (
	<span style={{fontFamily: font.mono, ...style}}>{children}</span>
);

// ------------------------------------------------------------------ slide 1
// The PDF page is the final, fully built frame of the video shots (caption, counter, flow line).

export const Slide1: React.FC<{mode: Mode}> = () => (
	<AbsoluteFill style={{backgroundColor: '#030405', color: color.text, fontFamily: font.sans}}>
		<div style={{position: 'absolute', left: 110, top: 90}}>
			<TitleCaption done scale={0.62} />
		</div>
		<DramatizationTag top={56} />
		<div style={{position: 'absolute', right: 56, top: 150}}>
			<LogoPair height={30} />
		</div>
		<div style={{position: 'absolute', left: 0, right: 0, top: 420, textAlign: 'center'}}>
			<div style={{fontSize: 170, fontWeight: 800, color: color.accent, letterSpacing: -4, lineHeight: 1}}>{reveal.counter.value}</div>
			<div style={{fontSize: 48, marginTop: 22}}>{reveal.counter.label}</div>
		</div>
		<FlowShot done y={900} scale={0.92} />
	</AbsoluteFill>
);

// ------------------------------------------------------------------ slide 2
// The split's final frame: all three cards side by side and lit, with the evidence equation.

export const SlideSplit: React.FC<{mode: Mode}> = () => (
	<AbsoluteFill style={{backgroundColor: '#030405'}}>
		<SplitBoard times={DONE_TIMES} />
	</AbsoluteFill>
);

// ------------------------------------------------------------------ slides 3–5 (evidence, benchmarks, close)
// Each page is the final, fully built state of its video shots, with a title for reading on its own.

const Region: React.FC<{style: React.CSSProperties; children: React.ReactNode}> = ({style, children}) => (
	<div style={{position: 'absolute', ...style}}>{children}</div>
);

export const Slide5: React.FC<{mode: Mode}> = ({mode}) => (
	<SlideFrame mode={mode} title={evidence.title}>
		<Region style={{left: 0, right: 0, top: 170, height: 420}}>
			<CitationShot done scale={0.8} />
		</Region>
		<Region style={{left: 0, right: 0, top: 600, height: 400}}>
			<SnapShot done scale={0.8} />
		</Region>
	</SlideFrame>
);

export const Slide6: React.FC<{mode: Mode; benchmarks: Benchmarks | null}> = ({benchmarks}) => (
	<AbsoluteFill style={{backgroundColor: color.bg}}>
		<BenchShot done benchmarks={benchmarks} footnote />
	</AbsoluteFill>
);

export const Slide7: React.FC<{mode: Mode}> = ({mode}) => (
	<SlideFrame mode={mode} title={close.title}>
		<div style={{flex: 1, display: 'flex', flexDirection: 'column', justifyContent: 'center', gap: 26}}>
			{close.answers.map((a) => (
				<div key={a.role} style={{fontSize: 52}}>
					<span style={{color: color.muted, display: 'inline-block', width: 320}}>{a.role}</span>
					<span style={{fontWeight: 600}}>{a.line}</span>
				</div>
			))}
			<div style={{fontSize: 52, fontWeight: 800, color: color.accent, marginTop: 16}}>{close.traceable}</div>
		</div>
		<div style={{display: 'flex', alignItems: 'center', justifyContent: 'space-between'}}>
			<Mono style={{fontSize: 46, fontWeight: 600}}>{REPO_URL}</Mono>
			<LogoPair height={40} />
		</div>
	</SlideFrame>
);

export const SLIDES = [Slide1, SlideSplit, Slide5, Slide6, Slide7] as const;

export const Blank: React.FC = () => <AbsoluteFill style={{backgroundColor: color.bg}} />;
