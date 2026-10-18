# DRAFT — issue for ugnmura/serenedb-bench (not published)

**Title:** RCAEval with metrics and traces: bench track (claimable units)

## What this is

The extractor is getting metric and trace tables plus change tools (branch `feat/metrics-traces` in serenedb-extractor; design: `docs/superpowers/specs/2026-10-18-metrics-traces-design.md`). This issue coordinates the bench side: data conversion, leak scan, arms, and the runs. Anyone's Claude can join at any time with the prompt in `docs/coordination/track-b-prompt.md` (serenedb-extractor, same branch).

**Data contract (read first):** `docs/contracts/telemetry-case-v1.md` in serenedb-extractor, branch `feat/metrics-traces`. Changing it needs agreement here from both tracks; bump the version.

**Time box:** tools and runs finished by <T+7h, fill in>. Hard deadline <T+12h, fill in>.

## Rules

1. Claim before you start: comment `claim <unit>` (first comment wins). Post progress at least every 45 min; a unit with no comment for 45 min is open again.
2. Work on a branch `bench/<unit>` in serenedb-bench. Never push to `main`; the owner merges.
3. Labels never reach the agent: case folders, table names, file paths, metric names and span attributes must be neutral (contract, "Leak rules"). Labels live outside the data root.
4. No tuning on RCAEval (test or held-out): don't change tools, prompts or questions because of RCAEval results. Bugs found on RCAEval go into this issue, not into a fix, until the owner decides.
5. At most 2 scored runs on the test set, ever. Every run is logged with its run id; no silent reruns.
6. Every score you post says: extractor commit, arm, model, k, case set, harness settings, machine/account, and what it can and cannot be compared with.
7. Datasets are not committed. Eadro has no licence: internal use only, never redistributed.

## Units

| Unit | What | Done when | Status |
|---|---|---|---|
| B1 | RCAEval test set: the 48 cases of serenedb-extractor#23 (RE2-OB rep 1 = 30, RE3-OB rep 1 = 10, RE3-TT rep 1 = 8) from HF `phamquiluan/RCAEval` (pin the revision v2 used) → contract shape, ids `rca-NN`, `labels.yaml`. Port v2's `scripts/_rcaeval.py` / `load_rcaeval.py` for pod masking, but use a **new, recorded id seed** (v2's seed reproduces v2's ids, whose answers are readable in v2). Data root `/data/cases/`. Check service names match across logs/metrics/traces. Sanity set only: it is at the ceiling. | 48 case folders + labels on the runner hosts; converter committed with a test | open |
| B2 | **Primary** held-out set: RE2 rep 2 for OB, SS, TT (90) + all RE3-SS (30), ids `rch-NN`, same converter. Sock Shop has no traces; drop header-only trace files. | 120 case folders + labels | open |
| B6 | Dev set: Eadro SocialNetwork (Zenodo 7615394) → contract shape, ids `dev-NN`, labels from its fault files. | case folders + labels; note any field you could not map | open |
| B3 | Arms + preseed in the harness: L (extractor at `b022894`), T (frozen build, `run_sql` hidden via `--disallowedTools`), T+SQL (frozen build, `SERENEDB_ALLOW_SQL=1`). **Every trial gets a fresh SereneDB holding only its own case**: setup the case's log/metric/trace tables with prefix `<case_id with - as _>_`, run `survey` on the log table. Several containers per host as RAM allows. Pinned image `serenedb/serenedb@sha256:6d41ac6577e797289158786a2015ba8fbd6875feadb5c491518e166c011058c9` on amd64 only; record it per run. Never use the S1–S6 databases. Question text and scorer as in the design doc. | `bench preseed` + `bench run` work on one case per arm, in parallel containers | open |
| B4 | Leak scan per the contract over every case folder, path, table name, registry `source` column and preseeded table. | report posted here; zero findings in names/paths, findings in original telemetry listed for a human | open |
| B5 | Required (main reference): RCAEval's BARO and MM-BARO on the same cases as a non-LLM reference. | AC@1/AC@3 table posted, with comparability note | open |
| H | Host list: every amd64 host and how many SereneDB containers it can run in parallel (need ≥ 6 in total). | list posted here | open |
| P | Pilot: 5 held-out cases, arm T, k=1, after the extractor freeze tag exists. Measures cost and time per run. | numbers posted | blocked on freeze |
| R1…Rn | Run shards: one arm × ~12 cases × k (held-out: T k=3 and T+SQL k=1 — primary; test 48: T and T+SQL k=1, and L k=1 at `b022894` — sanity). Shard list posted after the pilot. | trials.jsonl + summary posted | blocked on pilot |

## Track A status (extractor, read-only here)

| Slice | What | Status |
|---|---|---|
| A1 | foundation: registries, `setup_metric_table`, robust z, prefix/coverage helpers, fixtures | not started |
| A2 | `metric_changes`, `metric_series` | not started |
| A3 | `setup_trace_table` (self time), `trace_changes`, `get_trace` | not started |
| A4 | `log_changes`, `telemetry_overview`, `trend` minute bucket | not started |
| Freeze | tag `metrics-traces-freeze-1` | not yet |
