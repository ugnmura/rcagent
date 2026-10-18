import React from 'react';
import {AbsoluteFill} from 'remotion';
import type {Benchmarks} from '../benchmarks';
import {SlideFrame, type Mode} from '../components';
import {DONE_TIMES, SplitBoard} from '../split';
import {FactShot, FlowDiagramShot, TemplatesShot, TitleCaption} from '../shots';
import {BenchShot, CitationShot, LogoPair, SnapShot} from '../shots2';
import {close, coldOpen, demo, evidence, REPO_URL, reveal} from '../content';
import {color, font} from '../theme';

const Mono: React.FC<{children: React.ReactNode; style?: React.CSSProperties}> = ({children, style}) => (
	<span style={{fontFamily: font.mono, ...style}}>{children}</span>
);

// ------------------------------------------------------------------ slides 1–3 (the call, the node, the scale)
// Static pages that carry the talk without the video: each is the final frame of its video shot.

export const SlideCall: React.FC<{mode: Mode}> = () => (
	<AbsoluteFill style={{backgroundColor: '#030405', color: color.text, fontFamily: font.sans}}>
		<div style={{position: 'absolute', left: 110, top: 90}}>
			<TitleCaption done scale={0.62} />
		</div>
		<div style={{position: 'absolute', right: 56, top: 70}}>
			<LogoPair height={30} />
		</div>
		<div style={{position: 'absolute', left: 110, right: 110, top: 430, display: 'flex', flexDirection: 'column', gap: 26}}>
			{coldOpen.dialog.map((d, i) => (
				<div key={i} style={{fontSize: 40, lineHeight: 1.3}}>
					<span style={{color: color.accent, fontWeight: 700}}>{d.speaker}: </span>
					<span>{d.text}</span>
				</div>
			))}
		</div>
	</AbsoluteFill>
);

export const SlideCounter: React.FC<{mode: Mode}> = () => (
	<AbsoluteFill style={{backgroundColor: '#030405', color: color.text, fontFamily: font.sans, justifyContent: 'center', alignItems: 'center'}}>
		<div style={{fontSize: 240, fontWeight: 800, color: color.accent, letterSpacing: -6, lineHeight: 1}}>{reveal.counter.value}</div>
		<div style={{fontSize: 56, marginTop: 30}}>{reveal.counter.label}</div>
	</AbsoluteFill>
);

export const SlideFact: React.FC<{mode: Mode}> = () => (
	<AbsoluteFill style={{backgroundColor: '#030405'}}>
		<FactShot done />
	</AbsoluteFill>
);

// ------------------------------------------------------------------ slides 4–5 (the approach, as in the reveal)
// Templating, then the How-it-works diagram: the final frames of the two reveal shots.

export const SlideTemplating: React.FC<{mode: Mode}> = () => (
	<AbsoluteFill style={{backgroundColor: '#030405'}}>
		<TemplatesShot done />
	</AbsoluteFill>
);

export const SlideHowItWorks: React.FC<{mode: Mode}> = () => (
	<AbsoluteFill style={{backgroundColor: '#030405'}}>
		<FlowDiagramShot done />
	</AbsoluteFill>
);

// ------------------------------------------------------------------ slides 6–7 (the roles, the live demo)
// The split's final frame: all three cards side by side and lit, with the evidence equation.

export const SlideSplit: React.FC<{mode: Mode}> = () => (
	<AbsoluteFill style={{backgroundColor: '#030405'}}>
		<SplitBoard times={DONE_TIMES} />
	</AbsoluteFill>
);

// The live demo: what we type into Claude Code (README, quick start), one prompt per role.
export const SlideDemo: React.FC<{mode: Mode}> = () => (
	<AbsoluteFill style={{backgroundColor: '#030405', color: color.text, fontFamily: font.sans, padding: '0 140px', justifyContent: 'center'}}>
		<div style={{display: 'flex', alignItems: 'center', gap: 16, fontSize: 34, fontWeight: 800, letterSpacing: 4}}>
			<div style={{width: 16, height: 16, borderRadius: 8, background: color.accent}} />
			LIVE DEMO
		</div>
		<div style={{display: 'flex', flexDirection: 'column', gap: 34, marginTop: 70}}>
			{demo.prompts.map((p) => (
				<div key={p.command} style={{fontFamily: font.mono, fontSize: 40, lineHeight: 1.35}}>
					<span style={{color: color.accent}}>{p.command} </span>
					<span>{p.question}</span>
				</div>
			))}
		</div>
	</AbsoluteFill>
);

// ------------------------------------------------------------------ slides 8–10 (evidence, benchmarks, close)
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

export const SLIDES = [SlideCall, SlideCounter, SlideFact, SlideTemplating, SlideHowItWorks, SlideSplit, SlideDemo, Slide5, Slide6, Slide7] as const;

export const Blank: React.FC = () => <AbsoluteFill style={{backgroundColor: color.bg}} />;
