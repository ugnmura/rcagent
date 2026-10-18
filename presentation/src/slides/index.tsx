import React from 'react';
import {AbsoluteFill} from 'remotion';
import type {Benchmarks} from '../benchmarks';
import {SlideFrame, type Mode} from '../components';
import {DramatizationTag} from '../scenes';
import {FlowShot, RED, Ring, TitleCaption} from '../shots';
import {BarsShot, BenchShot, CitationShot, DaysRing, LogoPair, RiskCards, SnapShot} from '../shots2';
import {
	close,
	engineer,
	evidence,
	manager,
	REPO_URL,
	reveal,
	teamLead,
} from '../content';
import {color, font, size} from '../theme';

const Accent: React.FC<{children: React.ReactNode}> = ({children}) => (
	<span style={{color: color.accent, fontWeight: 800}}>{children}</span>
);

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

export const Slide2: React.FC<{mode: Mode}> = ({mode}) => {
	const pct = Number(engineer.share.pct.replace('%', ''));
	return (
		<SlideFrame mode={mode} title={engineer.chapter.title}>
			<div style={{fontSize: size.small, color: color.muted, marginTop: -16}}>{engineer.chapter.question}</div>
			<div style={{flex: 1, display: 'flex', gap: 90, alignItems: 'center'}}>
				<div style={{display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 26, width: 620}}>
					<Mono style={{fontSize: 46, fontWeight: 600}}>{engineer.node}</Mono>
					<Ring fraction={pct / 100} r={150} stroke={24} label={engineer.share.pct} labelSize={80} />
					<div style={{fontSize: size.small, textAlign: 'center'}}>
						<Accent>{engineer.share.part}</Accent> of {engineer.share.whole} fatal entries
					</div>
				</div>
				<div style={{flex: 1, display: 'flex', flexDirection: 'column', gap: 26, borderLeft: `3px solid ${color.line}`, paddingLeft: 48}}>
					<div style={{display: 'flex', alignItems: 'baseline', gap: 28}}>
						<Mono style={{fontSize: 34, color: color.muted}}>{engineer.beforeLine.time}</Mono>
						<span style={{fontSize: 52, fontWeight: 800, color: color.accent}}>{engineer.beforeLine.text}</span>
					</div>
					<div style={{display: 'flex', alignItems: 'baseline', gap: 28}}>
						<Mono style={{fontSize: 34, color: color.muted}}>then</Mono>
						<Mono style={{fontSize: 40, color: RED}}>{engineer.message}</Mono>
					</div>
					<div style={{fontSize: size.small}}>non-stop {engineer.window}</div>
					<div style={{fontSize: size.small, color: color.muted}}>L2 error: {engineer.rarity}</div>
				</div>
			</div>
			<div style={{fontSize: size.small, borderLeft: `6px solid ${color.accent}`, paddingLeft: 24}}>{engineer.hypothesis}</div>
		</SlideFrame>
	);
};

// ------------------------------------------------------------------ slides 3–7
// Each page is the final, fully built state of its video shots, with a title for reading on its own.

const Region: React.FC<{style: React.CSSProperties; children: React.ReactNode}> = ({style, children}) => (
	<div style={{position: 'absolute', ...style}}>{children}</div>
);

export const Slide3: React.FC<{mode: Mode}> = ({mode}) => {
	const p = teamLead.persistent;
	return (
		<SlideFrame mode={mode} title={teamLead.chapter.title}>
			<div style={{fontSize: size.small, color: color.muted, marginTop: -16}}>{teamLead.chapter.question}</div>
			<Region style={{left: 0, top: 200, width: 1060, height: 560}}>
				<BarsShot done scale={0.62} />
			</Region>
			<Region style={{left: 1080, top: 230, width: 760, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 22}}>
				<Mono style={{fontSize: 38, color: RED}}>“{p.message}”</Mono>
				<div style={{position: 'relative'}}>
					<DaysRing lit={p.days} r={150} stroke={24} />
					<div style={{position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center'}}>
						<div style={{fontSize: 96, fontWeight: 800, lineHeight: 1}}>{p.days}</div>
						<div style={{fontSize: 30, color: color.muted}}>of {p.of} days</div>
					</div>
				</div>
				<div style={{fontSize: size.small}}>
					December: <Accent>{p.trend}</Accent>, {p.trendLabel}
				</div>
			</Region>
			<div style={{marginTop: 'auto', fontSize: size.body, borderLeft: `6px solid ${color.accent}`, paddingLeft: 24}}>
				{teamLead.first.label}: <Accent>{teamLead.first.team}</Accent>
			</div>
		</SlideFrame>
	);
};

export const Slide4: React.FC<{mode: Mode}> = ({mode}) => (
	<SlideFrame mode={mode} title={manager.chapter.title}>
		<div style={{fontSize: size.small, color: color.muted, marginTop: -16}}>{manager.chapter.question}</div>
		<RiskCards done scale={0.88} top={250} />
		<div style={{marginTop: 'auto', fontSize: size.small, color: color.muted, fontStyle: 'italic'}}>{manager.honest}</div>
	</SlideFrame>
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

export const SLIDES = [Slide1, Slide2, Slide3, Slide4, Slide5, Slide6, Slide7] as const;

export const Blank: React.FC = () => <AbsoluteFill style={{backgroundColor: color.bg}} />;
