// One-off still: RCAEval summary for the deck. Not part of the talk. Numbers from benchmarks.json `rca` and
// OrFrederick/serenedb-bench results/rca/REPORT-2026-10-18.md (BARO row).
import React from 'react';
import {AbsoluteFill, Composition, registerRoot} from 'remotion';
import bench from '../public/assets/benchmarks.json';
import {LogoPair} from './shots2';
import {color, font} from './theme';

const r = bench.rca;
const BAR_GREY = '#3b4450';
const pct = (v: number) => `${Number.isInteger(v) ? v : v.toFixed(1)}%`;

const rows = [
	{label: 'BARO (RCAEval baseline, no LLM)', v: 23, cost: null as number | null, ours: false},
	{label: 'Logs only', v: r.logs_only_pct, cost: r.logs_only_usd, ours: false},
	{label: 'With metric + trace tools', v: r.with_metrics_pct, cost: r.with_metrics_usd, ours: true},
];
const BAR_W = 600;

const RcaSummary: React.FC = () => (
	<AbsoluteFill style={{backgroundColor: color.bg, color: color.text, fontFamily: font.sans}}>
		<div style={{position: 'absolute', top: 96, width: '100%', textAlign: 'center'}}>
			<div style={{fontSize: 64, fontWeight: 800, letterSpacing: -1}}>Root cause in microservices</div>
			<div style={{fontSize: 30, fontWeight: 600, letterSpacing: '0.3em', color: color.muted, marginTop: 18}}>RCAEVAL · LOGS, METRICS AND TRACES</div>
		</div>

		{/* left: the held-out headline */}
		<div style={{position: 'absolute', left: 110, top: 330, width: 760, textAlign: 'center'}}>
			<div style={{fontSize: 200, fontWeight: 800, lineHeight: 1, letterSpacing: -5, fontVariantNumeric: 'tabular-nums', color: color.accent}}>{pct(r.ac1_pct)}</div>
			<div style={{fontSize: 42, marginTop: 24}}>right root cause, first guess</div>
			<div style={{fontSize: 36, color: color.muted, marginTop: 28, fontVariantNumeric: 'tabular-nums'}}>
				<span style={{color: color.text, fontWeight: 800}}>{pct(r.ac3_pct)}</span> in the top three
			</div>
			<div style={{fontSize: 26, color: color.muted, marginTop: 36}}>116 held-out incidents (RE2 + RE3-SS) · 3 runs each</div>
		</div>

		{/* right: what metrics and traces add */}
		<div style={{position: 'absolute', left: 1000, top: 340, width: 820}}>
			<div style={{fontSize: 26, fontWeight: 600, letterSpacing: '0.25em', color: color.muted, marginBottom: 36}}>FIRST GUESS RIGHT · 48-CASE TEST SET</div>
			{rows.map((x) => (
				<div key={x.label} style={{marginBottom: 40}}>
					<div style={{fontSize: 32, fontWeight: x.ours ? 800 : 600, color: x.ours ? color.accent : color.text, marginBottom: 12}}>{x.label}</div>
					<div style={{display: 'flex', alignItems: 'center', gap: 24}}>
						<div style={{width: BAR_W, height: 44, position: 'relative'}}>
							<div style={{position: 'absolute', inset: 0, borderRadius: 8, background: '#161b22'}} />
							<div style={{position: 'absolute', left: 0, top: 0, bottom: 0, width: (BAR_W * x.v) / 100, borderRadius: 8, background: x.ours ? color.accent : BAR_GREY}} />
						</div>
						<div style={{fontSize: 40, fontWeight: 800, fontVariantNumeric: 'tabular-nums', color: x.ours ? color.accent : color.text, whiteSpace: 'nowrap'}}>{pct(x.v)}</div>
					</div>
					{x.cost !== null ? (
						<div style={{fontSize: 26, color: color.muted, marginTop: 8, fontVariantNumeric: 'tabular-nums'}}>${x.cost.toFixed(2)} per answer</div>
					) : null}
				</div>
			))}
		</div>

		<div style={{position: 'absolute', top: 960, left: 96, right: 420, fontSize: 22, color: color.muted, lineHeight: 1.4}}>
			RCAEval (Pham et al., WWW 2025) · Claude Sonnet · the test set is at its ceiling: 100% means parity with the best
		</div>
		<div style={{position: 'absolute', right: 48, bottom: 40}}>
			<LogoPair height={26} />
		</div>
	</AbsoluteFill>
);

registerRoot(() => <Composition id="RcaSummary" component={RcaSummary} width={1920} height={1080} fps={30} durationInFrames={1} />);
