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
| B1 | RCAEval test set: the 48 cases of serenedb-extractor#23 (RE2-OB rep 1 = 30, RE3-OB rep 1 = 10, RE3-TT rep 1 = 8) from HF `phamquiluan/RCAEval` (pin the revision v2 used) → contract shape, ids `rca-NN`, `labels.yaml`. Port v2's `scripts/_rcaeval.py` / `load_rcaeval.py` (seeded ids, pod masking). | 48 case folders + labels on the runner hosts; converter committed with a test | open |
| B2 | Held-out set: RE2 rep 2 for OB, SS, TT (90) + all RE3-SS (30), ids `rch-NN`, same converter. Sock Shop has no traces; drop header-only trace files. | 120 case folders + labels | open |
| B6 | Dev set: Eadro SocialNetwork (Zenodo 7615394) → contract shape, ids `dev-NN`, labels from its fault files. | case folders + labels; note any field you could not map | open |
| B3 | Arms + preseed in the harness: L (extractor log tools as on current main), T (all tools, `run_sql` off), T+SQL. Preseed per case: setup the case's log/metric/trace tables with prefix `<case_id with - as _>_`, run `survey` on the log table. Question text and scorer as in the design doc. | `bench preseed` + `bench run` work on one case per arm | open |
| B4 | Leak scan per the contract over every case folder, table name and preseeded table. | report posted here; zero findings in names/paths, findings in original telemetry listed for a human | open |
| B5 | Optional: RCAEval's BARO and MM-BARO on the same cases as a non-LLM reference. | AC@1/AC@3 table posted, with comparability note | open |
| P | Pilot: 5 test cases, arm T, k=1, after the extractor freeze tag exists. Measures cost and time per run. | numbers posted | blocked on freeze |
| R1…Rn | Run shards: one arm × ~12 cases × k (test: T and T+SQL, k=3; held-out: T, k=1). Shard list posted after the pilot. | trials.jsonl + summary posted | blocked on pilot |

## Track A status (extractor, read-only here)

| Slice | What | Status |
|---|---|---|
| A1 | foundation: registries, `setup_metric_table`, `setup_trace_table`, robust z | not started |
| A2 | `metric_changes`, `metric_series` | not started |
| A3 | `trace_changes`, `get_trace` | not started |
| A4 | `log_changes`, `telemetry_overview`, `trend` minute bucket | not started |
| Freeze | tag `metrics-traces-freeze-1` | not yet |
