import React from 'react';
import {AbsoluteFill} from 'remotion';
import type {Benchmarks} from '../benchmarks';
import {SlideFrame, type Mode} from '../components';
import {DONE_TIMES, SplitBoard} from '../split';
import {FactShot, FlowDiagramShot, IntroducingShot, TemplatesShot, TitleCaption} from '../shots';
import {BenchShot, CitationShot, LogoPair, SnapShot} from '../shots2';
import {close, coldOpen, demo, evidence, features, intro, PROJECT_NAME, reveal} from '../content';
import {color, font} from '../theme';

const Mono: React.FC<{children: React.ReactNode; style?: React.CSSProperties}> = ({children, style}) => (
	<span style={{fontFamily: font.mono, ...style}}>{children}</span>
);

/** SchubKI × SereneDB, the same corner on every page (the close shows it next to the repository link instead). */
const Brand: React.FC = () => (
	<div style={{position: 'absolute', right: 48, bottom: 40}}>
		<LogoPair height={26} />
	</div>
);

// ------------------------------------------------------------------ title slide

export const SlideTitle: React.FC<{mode: Mode}> = () => (
	<AbsoluteFill style={{backgroundColor: '#030405', color: color.text, fontFamily: font.sans, justifyContent: 'center', alignItems: 'center', gap: 40}}>
		<div style={{fontSize: 30, letterSpacing: '0.3em', color: color.muted, fontWeight: 600}}>{intro.event.toUpperCase()}</div>
		<div style={{fontSize: 140, fontWeight: 800, letterSpacing: -3, lineHeight: 1}}>{intro.title}</div>
		<div style={{fontSize: 40, color: color.muted, maxWidth: 1300, textAlign: 'center', lineHeight: 1.35}}>{intro.tagline}</div>
		<div style={{marginTop: 50}}>
			<LogoPair height={64} />
		</div>
	</AbsoluteFill>
);

// ------------------------------------------------------------------ slides 1–3 (the call, the node, the scale)
// Static pages that carry the talk without the video: each is the final frame of its video shot.

export const SlideCall: React.FC<{mode: Mode}> = () => (
	<AbsoluteFill style={{backgroundColor: '#030405', color: color.text, fontFamily: font.sans}}>
		<div style={{position: 'absolute', left: 110, top: 90}}>
			<TitleCaption done scale={0.62} />
		</div>
		<div style={{position: 'absolute', left: 110, right: 110, top: 430, display: 'flex', flexDirection: 'column', gap: 26}}>
			{coldOpen.dialog.map((d, i) => (
				<div key={i} style={{fontSize: 40, lineHeight: 1.3}}>
					<span style={{color: color.accent, fontWeight: 700}}>{d.speaker}: </span>
					<span>{d.text}</span>
				</div>
			))}
		</div>
		<Brand />
	</AbsoluteFill>
);

export const SlideCounter: React.FC<{mode: Mode}> = () => (
	<AbsoluteFill style={{backgroundColor: '#030405', color: color.text, fontFamily: font.sans, justifyContent: 'center', alignItems: 'center'}}>
		<div style={{fontSize: 240, fontWeight: 800, color: color.accent, letterSpacing: -6, lineHeight: 1}}>{reveal.counter.value}</div>
		<div style={{fontSize: 56, marginTop: 30}}>{reveal.counter.label}</div>
		<Brand />
	</AbsoluteFill>
);

export const SlideFact: React.FC<{mode: Mode}> = () => (
	<AbsoluteFill style={{backgroundColor: '#030405'}}>
		<FactShot done />
		<Brand />
	</AbsoluteFill>
);

export const SlideIntroducing: React.FC<{mode: Mode}> = () => (
	<AbsoluteFill style={{backgroundColor: '#030405'}}>
		<IntroducingShot done />
		<Brand />
	</AbsoluteFill>
);

// ------------------------------------------------------------------ slides 4–5 (the approach, as in the reveal)
// Templating, then the How-it-works diagram: the final frames of the two reveal shots.

export const SlideTemplating: React.FC<{mode: Mode}> = () => (
	<AbsoluteFill style={{backgroundColor: '#030405'}}>
		<TemplatesShot done />
		<Brand />
	</AbsoluteFill>
);

export const SlideHowItWorks: React.FC<{mode: Mode}> = () => (
	<AbsoluteFill style={{backgroundColor: '#030405'}}>
		<FlowDiagramShot done />
		<Brand />
	</AbsoluteFill>
);

// ------------------------------------------------------------------ slides 6–7 (the roles, the live demo)
// The split's final frame: all three cards side by side and lit, with the evidence equation.

export const SlideSplit: React.FC<{mode: Mode}> = () => (
	<AbsoluteFill style={{backgroundColor: '#030405'}}>
		<SplitBoard times={DONE_TIMES} />
		<Brand />
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
		<Brand />
	</AbsoluteFill>
);

// ------------------------------------------------------------------ slides 9–12 (evidence, benchmarks, features, close)
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
		<Brand />
	</SlideFrame>
);

export const Slide6: React.FC<{mode: Mode; benchmarks: Benchmarks | null}> = ({benchmarks}) => (
	<AbsoluteFill style={{backgroundColor: color.bg}}>
		<BenchShot done benchmarks={benchmarks} footnote />
		<Brand />
	</AbsoluteFill>
);

// The README's most important optional features, one row each with its measured number.
export const SlideFeatures: React.FC<{mode: Mode}> = ({mode}) => (
	<SlideFrame mode={mode} title={features.title}>
		<div style={{flex: 1, display: 'flex', flexDirection: 'column', justifyContent: 'center', gap: 44}}>
			{features.items.map((f) => (
				<div key={f.name} style={{display: 'flex', alignItems: 'baseline', gap: 40}}>
					<div style={{width: 600, flexShrink: 0, fontSize: 46, fontWeight: 700}}>{f.name}</div>
					<div style={{flex: 1, fontSize: 32, color: color.muted, lineHeight: 1.3}}>{f.what}</div>
					<div style={{width: 560, flexShrink: 0, fontSize: 34, fontWeight: 700, color: color.accent, textAlign: 'right'}}>{f.stat}</div>
				</div>
			))}
		</div>
		<Brand />
	</SlideFrame>
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
			<Mono style={{fontSize: 46, fontWeight: 600}}>{PROJECT_NAME}</Mono>
			<LogoPair height={40} />
		</div>
	</SlideFrame>
);

export const SLIDES = [SlideTitle, SlideCall, SlideCounter, SlideFact, SlideIntroducing, SlideTemplating, SlideHowItWorks, SlideSplit, SlideDemo, Slide5, Slide6, SlideFeatures, Slide7] as const;

export const Blank: React.FC = () => <AbsoluteFill style={{backgroundColor: color.bg}} />;
