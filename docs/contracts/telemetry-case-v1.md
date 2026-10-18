# Telemetry case contract, v1

This is the hand-off between the bench (track B, `serenedb-bench`) and the extractor (track A). The bench converts any RCA dataset (RCAEval, Eadro, ...) into this shape; the extractor only ever reads this shape. Nothing dataset-specific crosses the line.

Changing this contract needs agreement from both tracks in the coordination issue. Bump the version on any change.

## Layout

```
<data root>/
  <case_id>/
    logs.parquet       optional
    metrics.parquet    optional
    traces.parquet     optional
    case.json
<labels dir, outside the data root and never mounted into SereneDB>/
  labels.yaml
```

- `case_id` is neutral: `rca-NN` (test), `rch-NN` (held-out), `dev-NN` (development, e.g. Eadro). Assigned with a fixed, recorded seed that is **not** v2's seed (v2's ids and their answers are readable in v2's repo), shuffled, so it encodes nothing about system, fault or service.
- The data root is `/data/cases/` on the host and in the SereneDB container. No dataset name, set name or other hint appears anywhere in a path the agent can see (registry `source` columns, `describe_logs`, the `filename` column of in-place views, occurrence ids).
- A source that does not exist for a case is **absent as a file**. Never ship an empty or header-only file (13 RE3-SS cases have header-only traces in RCAEval: drop them).
- The data root is what the runner mounts into the SereneDB container (`LOGS_HOST_DIR` → `LOGS_CONTAINER_DIR`), so in-place views read from it. The labels dir must not be under it.

## `case.json`

```json
{"case_id": "rca-07", "pivot": "2024-01-15T17:30:22Z", "sources": ["logs", "metrics", "traces"]}
```

- `pivot`: the detect time given to the agent in the question (RCAEval: the inject time). ISO 8601, UTC, second precision.
- `sources`: exactly the files present.
- Nothing else. No system name, no fault, no service list.

## `logs.parquet`

| Column | Type | Notes |
|---|---|---|
| `ts` | TIMESTAMP, UTC-adjusted (`isAdjustedToUTC=true`) | from epoch, not from text inside the message |
| `service` | VARCHAR | pod names already masked to the service name |
| `message` | VARCHAR | pod names inside the text masked the same way |
| `level` | VARCHAR, nullable | only if the source has it |

Sorted by `ts`.

## `metrics.parquet` (long format)

| Column | Type | Notes |
|---|---|---|
| `ts` | TIMESTAMP, UTC-adjusted | |
| `service` | VARCHAR | |
| `metric` | VARCHAR | short generic name: `cpu`, `mem`, `diskio`, `socket`, `workload`, `error`, `latency-50`, `latency-90`, ... |
| `value` | DOUBLE | NULL / NaN / ±inf rows dropped, not filled |

RCAEval's wide `{service}_{metric}` columns are split at the **last** `_` by the bench converter. The extractor never parses column names.

## `traces.parquet` (one row per span)

| Column | Type | Notes |
|---|---|---|
| `trace_id` | VARCHAR | |
| `span_id` | VARCHAR | |
| `parent_span_id` | VARCHAR, nullable | NULL for root spans (empty string becomes NULL) |
| `service` | VARCHAR | |
| `operation` | VARCHAR | RCAEval `operationName` |
| `start` | TIMESTAMP, UTC-adjusted, µs | |
| `duration_us` | BIGINT | |
| `status` | VARCHAR, nullable | NULL = unknown (Train Ticket, some OB spans). `"ok"` or `"error"` otherwise: gRPC 0 and HTTP 2xx/3xx are `"ok"`, everything else `"error"`. Note for comparability: v2 counted 3xx as errors |

## `labels.yaml`

One entry per case: `case_id`, `dataset`, `source_case`, `system`, `root_cause_service`, `fault`, `pivot`. Read only by the scorer.

## Shared service names

`service` must use one vocabulary across logs, metrics and traces of a case (tools match coverage and edges on it). The converter checks this and reports every service name that appears in only one source.

## Leak rules (checked by the leak scan before any run)

The agent can reach file paths (occurrence ids, registry `source` columns, the `filename` column of in-place views), every column value and every table name. None of these may contain:

- the source case name or any part of it that names the root-cause service together with a fault (`cartservice_cpu`, `re2ob`, ...);
- fault words in names: `cpu`/`mem`/`disk`/`delay`/`loss`/`socket` only as metric names, never in paths, case ids or table names;
- injection tooling: `stress-ng`, `chaosblade`, `chaos-mesh`, `tc qdisc`, `netem`, `inject` in any string the bench added;
- pod hashes (`<service>-[a-z0-9]{8,10}-[a-z0-9]{5}`) after masking.

Strings that were already in the original telemetry (for example an application log line that happens to say "cpu") stay as they are; the scan reports them, a human decides.

## Table names in the extractor

Setup names a case's tables with its case id as prefix: `rca_07_logs`, `rca_07_metrics`, `rca_07_traces`. The prefix is how the tools group a case's tables (`telemetry_overview(prefix="rca_07_")`).
