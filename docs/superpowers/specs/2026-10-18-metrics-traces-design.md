# Metrics and traces support, and the RCAEval run

Date: 2026-10-18. Status: agreed in a grilling session (Q1–Q41), not yet built. This document is both the design and the plan; there is no separate plan document because of the time box.

## Intent

Score high on the RCAEval root-cause benchmark with an agent (Claude) that uses the extractor's MCP tools, and do it with tools that are generic, so the same tools help on any system with logs, metrics and traces. Issue #23 (ugnmura/serenedb-extractor) is blocked on this.

Why it matters: today the extractor reads logs only. v2's logs-only arm scored AC@1 0.30 on RCAEval's RE2 resource faults (CPU, memory, disk, network), because those faults show up in metrics, not in logs.

## Goals

- Metric tables and trace tables as new table kinds, with setup and analysis tools.
- A benchmark run on RCAEval with pre-registered hypotheses and an honest report.
- Track B (bench) can be picked up by other people's Claude sessions at any time, through one coordination issue.

## Non-goals

- Live fault injection, Kubernetes testbeds.
- Pivot scan (finding the change time without being told), hidden-detect-time variant: stretch only.
- A systems registry; Nezha; iterative tuning of tools or prompts.
- Matching or beating v2's numbers. v2 comparison is optional and never a gate.

## Anti-goals (failure even if it technically works)

- Any change in behaviour or output for log users.
- Tools that know RCAEval: hardcoded service names, fault types, metric names or thresholds tuned on RCAEval.
- A tool that outputs "the root cause is X". Tools report changes; the agent reasons about causes.
- A score that leaks labels (folder names, pod names, injection tooling).
- Numbers reported without saying what they can and cannot be compared with.

## Hard rules

1. Log tables: no schema change, no renames, `log_tables` registry untouched.
2. All existing tests and outputs byte-identical; `mypy` green.
3. No new required dependency.
4. Existing MCP tools keep names and signatures. New tools are additions; `trend` gains a `minute` bucket value only.
5. Branch `feat/metrics-traces` (worktree). Nothing pushed, no PR, no issue published without the owner's OK.
6. Benchmark code and datasets live outside this repo (`serenedb-bench`, data hosts). This repo gets product code and synthetic fixtures only.
7. Tools may be merged later only with evidence (dev set) that the agent does not get worse.

## Hypotheses (fixed before the first scored run)

- **H1** With metric and trace tools (arm T), AC@1 on the 30 RE2-OB resource-fault cases is ≥ 0.90 (v2 logs-only: 0.30).
- **H2** No regression: all existing tests and `mypy` green, existing log outputs unchanged; S1–S6 and the logs-only arm L are not worse than the pre-change baseline (being run now on current `main`).
- **H3** Traces add value: on the RE3 cases (code faults), arm T is at least as good as logs+metrics, and it names the right service with trace evidence in at least half of the answers. (Arm T with traces disabled is not run in the time box; H3 is judged qualitatively from the transcripts unless time allows a logs+metrics arm.)

## Product design (track A)

### Data the extractor accepts

Long-format metrics and one-row-per-span traces, as Parquet or JSON, local or remote. The benchmark delivers exactly `docs/contracts/telemetry-case-v1.md`; other users can bring any data in that shape. Integer epoch timestamps are allowed for metric and trace tables with a unit role (`s`, `ms`, `us`, `ns`), guessed from magnitude and shown at setup for confirmation.

### Registries (extractor schema)

- `extractor.metric_tables`: name, source, source_format, mode (`in_place`), relation, `role_timestamp`, `role_timestamp_unit`, `role_service`, `role_metric`, `role_value`, row_count, timezone.
- `extractor.trace_tables`: name, source, relation (`extractor.tt_<name>`, a real table), `role_*` for trace_id, span_id, parent_span_id, service, operation, start (+ unit), duration (+ unit), status; row_count, span_count_without_parent_match, setup_seconds.

`extractor.log_tables` is not touched (ADR-0004).

### Tools

Shared conventions: `prefix` selects all tables whose name starts with it; `pivot` is a time; `before_minutes` / `after_minutes` default to 10 / 10 (RCAEval's ±10 min); results show coverage per service. Robust z everywhere:

```
z = (median_after - median_before) / spread
spread = 1.4826 * MAD_before, or stddev_before if MAD is 0, floored at 1% of |median_before| and at a tiny epsilon
```

A series or operation needs at least 5 points on each side, otherwise it is listed as "too little data", not dropped silently. No thresholds, weights or rules tuned on any dataset.

| Tool | Inputs | Returns |
|---|---|---|
| `setup_metric_table` | source, name, roles (optional), timezone | proposed or confirmed roles, row count, time range, services, metric names |
| `setup_trace_table` | source, name, roles (optional) | roles, span count, time range, services, operations, orphan spans, setup time |
| `telemetry_overview` | prefix, pivot, before/after | per service: coverage, metric names, log and span counts before/after with change %. No ranking. |
| `metric_changes` | prefix or table, pivot, before/after, services?, metrics?, sort (`median`/`peak`), top (20) | top series by \|z\| with medians before/after and peak; per service its max \|z\|; coverage |
| `metric_series` | table, services, metrics, start, end, bucket_seconds (30) | bucketed min/median/max per series, so the agent can check a change is real |
| `trace_changes` | prefix or table, pivot, before/after, services?, operations?, sort (`self_time`/`errors`/`volume`), top (20) | per (service, operation): self-time p50/p95 before/after + z, error rate before/after (NULL status = unknown, never 0), volume z, 2–3 slowest example trace ids after the pivot; per edge (caller → callee): latency and error change; coverage |
| `get_trace` | table, trace_id | span tree: service, operation, start offset, duration, self time, status |
| `log_changes` | prefix or log table, pivot, before/after, services? | per service: templates first seen after the pivot (from the template catalog), error-ish rate before/after, volume z per minute; needs the service role, says so if absent |
| `trend` (existing) | adds `bucket="minute"` | unchanged otherwise |

`setup_trace_table` copies spans into `extractor.tt_<name>` and adds `self_time_us` = duration − union of child intervals clipped to the parent (overlapping children are not double-counted). If the pilot shows the join is cheap as a view, we switch to in place (ADR-0004).

### Code layout (so slices can run in parallel)

`server.py` registers everything in one function today. Slice A1 adds `src/serenedb_extractor/telemetry/` with one module per tool group and a single `register_telemetry_tools(mcp, runner)` call in `server.py`; the registration list in `telemetry/__init__.py` already names every slice's module (stubs), so parallel slices only edit their own module and its test file.

| Slice | Files |
|---|---|
| A1 foundation | `catalog/schema.py` (new DDL only), `telemetry/__init__.py`, `telemetry/setup.py`, `telemetry/stats.py` (robust z), `telemetry/roles.py`, one line in `server.py`, `tests/telemetry/fixtures.py` (synthetic generator) |
| A2 metrics | `telemetry/metrics.py` (`metric_changes`, `metric_series`), `tests/telemetry/test_metrics.py` |
| A3 traces | `telemetry/traces.py` (`trace_changes`, `get_trace`), `tests/telemetry/test_traces.py` |
| A4 logs and overview | `telemetry/log_changes.py`, `telemetry/overview.py`, `tools/trend.py` (minute bucket only), tests |

### Synthetic fixtures (TDD)

A generator in `tests/telemetry/fixtures.py` writes small Parquet files in the contract shape with a known answer: e.g. 5 services, 20 minutes, service C's `cpu` steps up at the pivot, its callers' total latency rises but their self time does not, service C logs a new exception template. Tests assert the tools rank C first for the right reason (self time, not total), report coverage, and report "too little data" where it applies. Tests reach SereneDB the way existing db tests do.

## Bench design (track B, `serenedb-bench`)

Coordinated through one GitHub issue with claimable units (draft: `docs/coordination/issue-track-b.md`); any Claude can join with the generic prompt (`docs/coordination/track-b-prompt.md`).

- **B1** RCAEval test set: the 48 cases of issue #23 (RE2-OB rep 1, RE3-OB rep 1, RE3-TT rep 1) from the Hugging Face copy (`phamquiluan/RCAEval`, pinned revision as in v2), converted to the contract. v2's `scripts/_rcaeval.py` and `load_rcaeval.py` can be ported (seeded ids, pod masking).
- **B2** Held-out set: RE2 rep 2 for OB, SS, TT (90) + RE3-SS (30) = 120 cases, ids `rch-NN`.
- **B6** Dev set: Eadro SocialNetwork (Zenodo 7615394), ids `dev-NN`. No licence: internal use only, never redistributed.
- **B3** Arms and preseed: L (current extractor log tools), T (all tools, no `run_sql`), T+SQL. Preseed per case: setup of the three tables with the case prefix, `survey` on the log table.
- **B4** Leak scan per the contract.
- **B5** Optional: RCAEval's BARO and MM-BARO on the same cases as a non-LLM reference.
- **R1…Rn** Run shards: one arm × ~12 cases × k, claimable by any machine and account.

Question per case (RCAEval protocol): "An anomaly was detected at `<pivot>` UTC in the system whose telemetry tables start with `<prefix>`. Which service is the root cause? End with `RANKING: a, b, c`." Scoring: v2's `score_rca` (already ported in `serenedb-bench/harness`), AC@1 and AC@3.

## Protocol

- No tuning on any data. The statistic and defaults above are fixed now.
- One dev round on Eadro SN (36 cases, arm T, k=1) after slices merge: only bug fixes may follow.
- 5-case RCAEval pilot (arm T, k=1) to measure cost and time per run.
- Freeze: tag `metrics-traces-freeze-1` when tests, `mypy` and H2 are green and the dev round's bugs are fixed.
- Scored runs on the test set: at most 2. Every run is logged; no silent reruns.
- Runs: test 48 × {T, T+SQL} × k=3 (288); held-out 120 × T × k=1 (120); arm L from the baseline already running. Sonnet throughout. If the pilot shows > 2 min per run, k drops to 1 on the test set too, flagged.
- Every score table says what it is comparable with (commit, model, k, arm, case set, harness settings).

## Topology

- SereneDB on an amd64 host per runner: `atlas` for the Mac (native amd64, 4 cores, 7 GB RAM, 14 GB free disk, reached through `ssh -L`); runners on other machines use their own SereneDB. SereneDB 26.10.1 does not run under emulation on Apple Silicon.
- RWTH HPC only as a fallback.
- No Docker clean-up; nothing deleted.

## Time box (T = start of building)

| Time | Track A | Track B |
|---|---|---|
| T+0:00–0:30 | contract, ADR-0004, this spec, issue and prompt drafts | waits for publication |
| T+0:30–1:00 | A1 foundation | B1, B2, B6 |
| T+1:00–3:00 | A2, A3, A4 in parallel sessions | B3, B4, B5 |
| T+3:00–3:30 | merge, gates | pilot ready |
| T+3:30–4:00 | Eadro dev round + pilot | |
| T+4:00 | freeze | |
| T+4:00–6:00 | | shards |
| T+6:00–7:00 | scoring, report | |

Deadline 12 h from start. Cut order if late: `log_changes`, then the Eadro round, then held-out shrinks to RE2-TT rep 2.

## Left to the builder

- Exact SQL of the aggregations, as long as the statistic above is kept.
- Output formatting, following the existing tools' style (`format.py`).
- Tool descriptions, following the shape in `server.py` (what, when, inputs, returns).
- How the synthetic generator is parameterised.
