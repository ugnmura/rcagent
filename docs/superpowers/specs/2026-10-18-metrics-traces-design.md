# Metrics and traces support, and the RCAEval run

Date: 2026-10-18. Status: agreed in a grilling session (Q1–Q41) and an adversarial review (R1–R6), not yet built. This document is both the design and the plan; there is no separate plan document because of the time box.

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

- Any change in behaviour or output for log users beyond the allowed list below.
- Tools that know RCAEval: hardcoded service names, fault types, metric names or thresholds tuned on RCAEval.
- A tool that outputs "the root cause is X". Tools report changes; the agent reasons about causes.
- A score that leaks labels (paths, folder names, pod names, case ids that match v2's, injection tooling).
- Numbers reported without saying what they can and cannot be compared with.

## Hard rules

1. Log tables: no schema change, no renames, `log_tables` registry untouched.
2. All existing tests and outputs byte-identical, `mypy` green, except this allowed list:
   - `tests/tools/test_skeleton.py`: the expected tool set and count grow by the new tools.
   - `tests/tools/test_prompts.py`: its expected tool set grows by the new tools; `tests/tools/test_indexes.py`: the list of tables bootstrap may create grows by `metric_tables` and `trace_tables`.
   - `trend`: the `bucket` error text and docstring name `minute` as a third value (`tools/trend.py`, `server.py`).
   - Server instructions (`instructions.py`): one added sentence, "If metric or trace tables exist, start with `telemetry_overview`."
3. No new required dependency.
4. Existing MCP tools keep names and signatures. New tools are additions.
5. Branch `feat/metrics-traces` (worktree). Nothing pushed, no PR, no issue published without the owner's OK.
6. Benchmark code and datasets live outside this repo (`serenedb-bench`, data hosts). This repo gets product code and synthetic fixtures only.
7. Tools may be merged later only with evidence (dev set) that the agent does not get worse.

## Hypotheses (fixed before the first scored run)

The 48 cases of issue #23 are at the ceiling (v2: every arm with metrics, and bare SQL, scored 1.00; RE3 is solved by restart lines in the logs). They are a sanity check only. **The held-out set is the primary result.**

- **H1** On the held-out RE2 resource-fault cases (rep 2, OB/SS/TT, 90 cases), arm T reaches AC@1 ≥ 0.90. Reported per system.
- **H2** No regression for log users: all existing tests and `mypy` green with only the allowed changes above; S1–S3 rerun with the frozen build fall inside the confidence interval of the pre-change baseline (being run now on current `main`).
- **H3 (exploratory, not a gate)** Traces help where metrics alone are ambiguous. Judged from transcripts of RE3 and RE2-TT cases (how often trace evidence decided the answer). No arm without traces is run. Train Ticket spans have no status, so trace errors are unknown there.

## Product design (track A)

### Data the extractor accepts

Long-format metrics and one-row-per-span traces, as Parquet or JSON, local or remote. The benchmark delivers exactly `docs/contracts/telemetry-case-v1.md`; other users can bring any data in that shape. Integer epoch timestamps are allowed for metric and trace tables with a unit role (`s`, `ms`, `us`, `ns`), guessed from magnitude and shown at setup for confirmation. Timestamp columns without a zone are read in the table's time zone (default UTC), like log tables.

### Registries (extractor schema)

- `extractor.metric_tables`: name, source, source_format, mode (`in_place`), relation, `role_timestamp`, `role_timestamp_unit`, `role_service`, `role_metric`, `role_value`, row_count, timezone.
- `extractor.trace_tables`: name, source, relation (`extractor.tt_<name>`, a real table), `role_*` for trace_id, span_id, parent_span_id, service, operation, start (+ unit), duration (+ unit), status; row_count, orphan_spans, setup_seconds, timezone.

`extractor.log_tables` is not touched (ADR-0004).

### Shared conventions

- `prefix` selects all tables (log, metric, trace) whose name starts with it, matched with `starts_with`, never `LIKE` (`_` is a wildcard there). A prefix must end in `_`.
- `pivot` is a time; `before_minutes` / `after_minutes` default to 10 / 10. These defaults are RCAEval's ±10 min window and are disclosed as such in every report.
- Every result shows **coverage** per service: logs / metrics / traces, yes or no. "No data" is never shown as "no change".

### The change statistic (fixed, not tuned)

```
z = (median_after - median_before) / spread
spread = 1.4826 * MAD_before, or stddev_before if MAD is 0, floored at 1% of |median_before|
```

- At least 5 points on each side, otherwise listed as "too little data".
- If the baseline is all zero (or spread is 0 after the floors) and the after-window is not, the series is listed in a separate **"rose from zero"** group with its after-median, not ranked by z. Series that are zero on both sides are "unchanged".
- This is the same idea as BARO's robust scaling (median and IQR/MAD). Disclosed in every report; BARO itself is run as the main reference (B5).

### Tools

| Tool | Inputs | Returns |
|---|---|---|
| `setup_metric_table` | source, name, roles (optional), timezone | proposed or confirmed roles, row count, time range, services, metric names |
| `setup_trace_table` | source, name, roles (optional), timezone | roles, span count, time range, services, operations, orphan spans, setup time |
| `telemetry_overview` | prefix, pivot, before/after | per service: coverage, metric names, log and span counts before/after with change %. No ranking. |
| `metric_changes` | prefix or table, pivot, before/after, services?, metrics?, sort (`median`/`peak`), top (20) | top series by \|z\| with medians before/after and peak; "rose from zero" group; per service its max \|z\|; coverage |
| `metric_series` | table, services, metrics, start, end, bucket_seconds (30) | bucketed min/median/max per series, so the agent can check a change is real |
| `trace_changes` | prefix or table, pivot, before/after, services?, operations?, sort (`self_time`/`errors`/`volume`), top (20) | per (service, operation): self-time p50/p95 before/after + z, error rate before/after (NULL status = unknown, never 0), volume z, 2–3 slowest example trace ids after the pivot; per edge (caller → callee): call latency, **network time** (caller's client span minus callee's matching server span) and errors, each before/after + z; coverage |
| `get_trace` | table, trace_id | span tree: service, operation, start offset, duration, self time, status |
| `log_changes` | prefix or log table, pivot, before/after, services? | per service: exact counts before and after the pivot for every catalog template seen in either window (the after-window is surveyed first so templates that only appear after the pivot, e.g. restart lines, are in the catalog), templates with zero count before; error-ish rate before/after; volume z per minute. Needs the service role, says so if absent |
| `trend` (existing) | adds `bucket="minute"` | unchanged otherwise |

**Error-ish** (fixed): the level role is `error`/`fatal`/`critical` (case-insensitive) when the table has a level role; otherwise the message matches `error|exception|fail|fatal|panic|traceback` (case-insensitive).

**Self time:** `setup_trace_table` copies spans into `extractor.tt_<name>` and adds `self_time_us` = duration − the union of child intervals clipped to the parent (overlapping children are not double-counted; children outside the parent are clipped; orphan spans keep their full duration and are counted). Whether the copy is needed is measured in slice A3 on the fixtures and on B1 data, and decided before the freeze; after the freeze it does not change. **Decided (slice A3 measurement, synthetic data):** keep the copy. Setup 0.43 s for 8,400 spans and 0.57 s for 84,000; a per-operation aggregate on a self-time view costs about 2× the copy at 84,000 spans, and `trace_changes` reads spans in three queries. To recheck on B1 data before the freeze.

### Code layout (so slices can run in parallel)

`server.py` registers everything in one function today. Slice A1 adds `src/serenedb_extractor/telemetry/` and a single `register_telemetry_tools(mcp, runner)` call in `server.py`; the registration list in `telemetry/__init__.py` already names every slice's module (stubs), so parallel slices only edit their own module and test file.

| Slice | Owns |
|---|---|
| A1 foundation | `catalog/schema.py` (new DDL only), `telemetry/__init__.py`, `telemetry/common.py` (prefix resolver, coverage helper, window helper), `telemetry/stats.py` (robust z incl. rose-from-zero), `telemetry/roles.py`, `telemetry/metric_setup.py` (`setup_metric_table`), `instructions.py` (the one sentence), `tests/test_skeleton.py` update, `server.py` (one line), `tests/telemetry/fixtures.py` (synthetic generator incl. a network-delay case) |
| A2 metrics | `telemetry/metrics.py` (`metric_changes`, `metric_series`), `tests/telemetry/test_metrics.py` |
| A3 traces | `telemetry/trace_setup.py` (`setup_trace_table`, self time), `telemetry/traces.py` (`trace_changes`, `get_trace`), `tests/telemetry/test_traces.py` |
| A4 logs and overview | `telemetry/log_changes.py`, `telemetry/overview.py`, `tools/trend.py` (minute bucket only), tests |

### Tests

- TDD with the synthetic generator: small Parquet files in the contract shape with a known answer, e.g. 5 services, 20 minutes, service C's `cpu` steps up at the pivot, its callers' total latency rises but their self time does not, C logs a new exception template; plus a network-delay case where only the edge's network time moves, and a rose-from-zero error series.
- Each slice uses its own test database, `SERENEDB_TEST_URL=.../extractor_test_<slice>`, because `tests/conftest.py` drops the `extractor` schema on every run.
- Tests run against `scripts/test-db.sh`'s pinned image locally if it starts; otherwise against atlas through `ssh -L`.

## Bench design (track B, `serenedb-bench`)

Coordinated through one GitHub issue with claimable units (draft: `docs/coordination/issue-track-b.md`); any Claude can join with the generic prompt (`docs/coordination/track-b-prompt.md`).

- **B1** Test set: the 48 cases of issue #23 (RE2-OB rep 1, RE3-OB rep 1, RE3-TT rep 1) from the Hugging Face copy (`phamquiluan/RCAEval`, pinned revision as in v2), converted to the contract. v2's `scripts/_rcaeval.py` / `load_rcaeval.py` may be ported for masking, but with a **new id seed**: v2's seed gives v2's ids, whose answers are readable in v2's repo.
- **B2** Held-out set (primary): RE2 rep 2 for OB, SS, TT (90) + RE3-SS (30), minus v2's 4 practice cases (answers readable in v2) = 116 cases, ids `rch-NN`.
- **B6** Dev set: Eadro SocialNetwork (Zenodo 7615394), ids `dev-NN`. No licence: internal use only, never redistributed.
- **B3** Arms and preseed:
  - L: extractor at `b022894` (current `main`), log tools only by construction.
  - T: frozen build, `run_sql` hidden on the harness side (`--disallowedTools` for it; no product change).
  - T+SQL: frozen build, `SERENEDB_ALLOW_SQL=1`.
  - Every trial gets a fresh SereneDB holding **only its own case** (log, metric and trace tables with the case prefix, `survey` run on the log table). Trials are therefore independent and can run in parallel, several containers per host as RAM allows. The S1–S6 databases are never used.
- **B4** Leak scan per the contract, including registry `source` columns and every path the agent can see.
- **B5** RCAEval's BARO and MM-BARO on the same cases: the main non-LLM reference.
- **R1…Rn** Run shards: one arm × ~12 cases × k, claimable by any machine and account.

Question per case (RCAEval protocol): "An anomaly was detected at `<pivot>` UTC in the system whose telemetry tables start with `<prefix>`. Which service is the root cause? End with `RANKING: a, b, c`." Scoring: v2's `score_rca` (already ported in `serenedb-bench/harness`), AC@1 and AC@3, reported per subset (system × fault family).

## Protocol

- No tuning on any data. The statistic, defaults and error-ish rule above are fixed now.
- One dev round on Eadro SN (36 cases, arm T, k=1) after slices merge: only bug fixes may follow.
- Freeze: tag `metrics-traces-freeze-1` when tests, `mypy` and the allowed-change check are green and the dev round's bugs are fixed.
- Pilot after the freeze: 5 held-out cases, arm T, k=1, to measure cost and time per run.
- Scored runs on any RCAEval set: at most 2 per set. Every run is logged; no silent reruns.
- Runs:
  - held-out 120 × T × k=3 (360) and × T+SQL × k=1 (120): primary;
  - test 48 × {T, T+SQL} × k=1 (96): sanity;
  - test 48 × L × k=1 (48) at `b022894`: logs-only reference;
  - S1–S3 with the frozen build: H2.
  - If the pilot shows > 2 min per run, held-out T drops to k=1, flagged.
- Every score table says what it is comparable with: extractor commit, SereneDB digest, model, k, arm, case set, harness settings, machine/account; and notes that the status mapping counts 3xx as ok (v2 did not).

## Topology

- One SereneDB image everywhere: `serenedb/serenedb@sha256:6d41ac6577e797289158786a2015ba8fbd6875feadb5c491518e166c011058c9` (26.10.1, amd64), recorded in each run's metadata.
- amd64 hosts only (26.10.1 does not run under emulation for the bench): `atlas` for the Mac (4 cores, 7 GB RAM, ~4 GB available, 14 GB free disk, shared with home services: 1–2 containers), plus the joiners' machines. About 600 trials at ~75 s need at least 6 containers running in parallel to finish in ~2 h; hosts are listed in the issue before the pilot.
- Neutral paths everywhere the agent can see: data root `/data/cases/<case_id>/` on the host and in the container.
- RWTH HPC only as a fallback. No Docker clean-up; nothing deleted.

## Time box (T = start of building)

| Time | Track A | Track B |
|---|---|---|
| T+0:00–0:30 | docs (done) | waits for publication |
| T+0:30–2:00 | A1 foundation | B1, B2, B6, host list |
| T+2:00–3:30 | A2, A3, A4 in parallel sessions | B3, B4, B5 |
| T+3:30–4:00 | merge, gates | |
| T+4:00–4:30 | Eadro dev round, bug fixes | |
| T+4:30 | freeze, pilot | pilot |
| T+4:45–6:45 | | shards |
| T+6:45–7:30 | report | |

Deadline 12 h from start. Cut order if late: `log_changes`, then the Eadro round, then T+SQL on the held-out set, then held-out k=3 → k=1.

## Left to the builder

- Exact SQL of the aggregations, as long as the statistic above is kept.
- Output formatting, following the existing tools' style (`format.py`).
- Tool descriptions, following the shape in `server.py` (what, when, inputs, returns).
- How the synthetic generator is parameterised.
