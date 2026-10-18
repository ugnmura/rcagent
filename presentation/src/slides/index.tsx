import React from 'react';
import {AbsoluteFill} from 'remotion';
import {isComplete, type Benchmarks} from '../benchmarks';
import {SlideFrame, type Mode} from '../components';
import {DramatizationTag} from '../scenes';
import {FlowShot, RED, Ring, TitleCaption} from '../shots';
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

// ------------------------------------------------------------------ slide 3

export const Slide3: React.FC<{mode: Mode}> = ({mode}) => (
	<SlideFrame mode={mode} title={teamLead.title}>
		<div style={{display: 'flex', gap: 56, flex: 1, minHeight: 0}}>
			<div style={{flex: 1, display: 'flex', flexDirection: 'column'}}>
				<div style={{fontSize: 30, color: color.muted, marginBottom: 12}}>Entries by team and level, whole corpus</div>
				{teamLead.table.map((r) => (
					<div
						key={r.team}
						style={{
							display: 'flex',
							gap: 24,
							padding: '6px 0',
							borderTop: `2px solid ${color.line}`,
							alignItems: 'baseline',
						}}
					>
						<div style={{width: 400, flexShrink: 0, fontSize: size.small, fontWeight: 600, lineHeight: 1.15}}>
							{r.team}
							<div style={{fontSize: 24, color: color.muted, fontWeight: 400}}>{r.log}</div>
						</div>
						<div style={{fontSize: size.small, color: color.text, lineHeight: 1.15}}>{r.levels}</div>
					</div>
				))}
			</div>
			<div
				style={{
					width: 460,
					flexShrink: 0,
					alignSelf: 'flex-start',
					background: color.panel,
					border: `3px solid ${color.accent}`,
					borderRadius: 20,
					padding: 36,
					display: 'flex',
					flexDirection: 'column',
					gap: 18,
				}}
			>
				<div style={{fontSize: size.small}}>{teamLead.highlight.message}</div>
				<div style={{fontSize: 80, fontWeight: 800, color: color.accent, lineHeight: 1}}>{teamLead.highlight.days}</div>
				<div style={{fontSize: size.small, color: color.muted}}>{teamLead.highlight.detail}</div>
				<div style={{fontSize: size.small, fontWeight: 600}}>{teamLead.highlight.first}</div>
			</div>
		</div>
	</SlideFrame>
);

// ------------------------------------------------------------------ slide 4

export const Slide4: React.FC<{mode: Mode}> = ({mode}) => (
	<SlideFrame mode={mode} title={manager.title}>
		<div style={{display: 'flex', flexDirection: 'column', gap: 16}}>
			{manager.risks.map((r, i) => (
				<div key={r.risk} style={{display: 'flex', alignItems: 'baseline', gap: 28}}>
					<div style={{fontSize: size.body, fontWeight: 800, color: i === 0 ? color.accent : color.muted, width: 48}}>
						{i + 1}
					</div>
					<div style={{flex: 1, fontSize: size.body, fontWeight: i === 0 ? 600 : 400}}>{r.risk}</div>
					<div style={{fontSize: size.small, color: color.muted, textAlign: 'right'}}>{r.owner}</div>
				</div>
			))}
		</div>
		<div style={{marginTop: 'auto', fontSize: size.small, color: color.muted, fontStyle: 'italic'}}>{manager.honest}</div>
	</SlideFrame>
);

// ------------------------------------------------------------------ slide 5

export const Slide5: React.FC<{mode: Mode}> = ({mode}) => (
	<SlideFrame mode={mode} title={evidence.title}>
		<div
			style={{
				background: color.panel,
				border: `2px solid ${color.line}`,
				borderRadius: 16,
				padding: '24px 32px',
				display: 'flex',
				flexDirection: 'column',
				gap: 12,
			}}
		>
			<div style={{fontSize: size.small}}>
				<Mono style={{color: color.accent, fontWeight: 600}}>[{evidence.handle}]</Mono>{' '}
				<Mono style={{fontSize: 30}}>{evidence.call}</Mono>
			</div>
			<Mono style={{fontSize: 26, color: color.muted, lineHeight: 1.4}}>{evidence.sql}</Mono>
			<div style={{fontSize: 26, color: color.muted}}>{evidence.measured}</div>
		</div>
		<div style={{flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 60}}>
			{[evidence.left, evidence.right].map((n, i) => (
				<React.Fragment key={n.label}>
					{i === 1 ? <div style={{fontSize: 120, fontWeight: 800, color: color.muted}}>=</div> : null}
					<div style={{display: 'flex', flexDirection: 'column', alignItems: 'center', width: 640, gap: 8}}>
						<div style={{fontSize: 120, fontWeight: 800, color: color.accent, lineHeight: 1}}>{n.value}</div>
						<div style={{fontSize: size.small, color: color.text, textAlign: 'center'}}>{n.label}</div>
					</div>
				</React.Fragment>
			))}
		</div>
	</SlideFrame>
);

// ------------------------------------------------------------------ slide 6

const TodoStamp: React.FC = () => (
	<div
		style={{
			position: 'absolute',
			top: 64,
			right: 96,
			transform: 'rotate(-8deg)',
			border: `8px solid ${color.placeholder}`,
			color: color.placeholder,
			fontSize: 72,
			fontWeight: 800,
			padding: '6px 32px',
			borderRadius: 12,
			letterSpacing: 6,
			background: 'rgba(13,17,23,0.85)',
		}}
	>
		TODO
	</div>
);

export const Slide6: React.FC<{mode: Mode; benchmarks: Benchmarks | null}> = ({mode, benchmarks}) => {
	const b = benchmarks;
	const complete = b !== null && isComplete(b);
	const designs = b?.designs ?? [];
	const max = complete ? Math.max(...designs.map((d) => d.score_pct ?? 0), 1) : 1;
	return (
		<SlideFrame mode={mode} title="Same questions, graded blind">
			<div style={{flex: 1, display: 'flex', flexDirection: 'column', justifyContent: 'center', gap: 34}}>
				{designs.map((d) => {
					const width = complete ? `${((d.score_pct ?? 0) / max) * 100}%` : '100%';
					return (
						<div key={d.name} style={{display: 'flex', alignItems: 'center', gap: 32}}>
							<div
								style={{
									width: 560,
									flexShrink: 0,
									fontSize: size.small,
									fontWeight: d.ours ? 800 : 400,
									color: d.ours ? color.accent : color.text,
								}}
							>
								{d.name}
							</div>
							<div style={{flex: 1, height: 96, position: 'relative'}}>
								<div
									style={{
										width,
										height: '100%',
										borderRadius: 10,
										background: complete ? (d.ours ? color.accent : '#3b4450') : 'transparent',
										border: complete ? 'none' : `3px dashed ${d.ours ? color.accent : color.line}`,
										display: 'flex',
										alignItems: 'center',
										padding: '0 28px',
										boxSizing: 'border-box',
										fontSize: size.small,
										fontWeight: 600,
										color: complete && d.ours ? color.bg : color.text,
									}}
								>
									{complete
										? `${d.score_pct}% · $${d.usd_per_answer} per answer`
										: 'score: TODO · cost per answer: TODO'}
								</div>
							</div>
						</div>
					);
				})}
			</div>
			<div style={{fontSize: 30, color: complete ? color.muted : color.placeholder}}>{b?.footnote ?? ''}</div>
			{complete ? null : <TodoStamp />}
		</SlideFrame>
	);
};

// ------------------------------------------------------------------ slide 7

export const Slide7: React.FC<{mode: Mode}> = ({mode}) => (
	<SlideFrame mode={mode} title={close.title}>
		<div style={{flex: 1, display: 'flex', flexDirection: 'column', justifyContent: 'center', gap: 30}}>
			{close.answers.map((a) => (
				<div key={a.role} style={{fontSize: 56}}>
					<span style={{color: color.muted, display: 'inline-block', width: 340}}>{a.role}</span>
					<span style={{fontWeight: 600}}>{a.line}</span>
				</div>
			))}
			<div style={{fontSize: 56, fontWeight: 800, color: color.accent, marginTop: 20}}>{close.traceable}</div>
		</div>
		<Mono style={{fontSize: 48, fontWeight: 600}}>{REPO_URL}</Mono>
	</SlideFrame>
);

export const SLIDES = [Slide1, Slide2, Slide3, Slide4, Slide5, Slide6, Slide7] as const;

export const Blank: React.FC = () => <AbsoluteFill style={{backgroundColor: color.bg}} />;
