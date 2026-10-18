# Metrics and traces are their own table kinds next to log tables; trace tables are copied once to add self time

Metric tables (long format: time, service, metric, value) and trace tables (one row per span) are new kinds of table with their own registries, `extractor.metric_tables` and `extractor.trace_tables`. Log tables, their registry, their roles and their tools are not changed. Tables that belong to one system are grouped by a shared name prefix (`rca_07_logs`, `rca_07_metrics`, `rca_07_traces`), not by a new registry column.

Metric tables follow ADR-0003: read in place through a view. Trace tables do not: setup copies the spans once into a table and adds each span's self time (its duration minus the time covered by its children). Self time never depends on the question, and computing it needs a self-join on `parent_span_id`, which would otherwise run on every tool call over up to millions of spans.

All aggregation (per series, per operation, per caller-callee edge, per time window) happens at query time. Nothing is pre-bucketed, so a single trace can always be read back span by span.

## Considered Options

- **Generalise log tables into "telemetry tables"** — one registry with a kind column. Rejected: it renames and reshapes what log users rely on, and the mandatory message role and the template catalog make no sense for metrics or spans.
- **Force metrics and spans into log tables** with a synthetic message — rejected: templating and surveys would run over fake messages.
- **Pre-aggregate spans into time buckets at setup** (what v2 did) — rejected: the agent can no longer look at one trace, and the bucket size is fixed before the question is known.
- **Trace tables in place, self time in the view** — kept as the fallback if the measured join cost is small; the pilot measures it.
- **A `system` column on log tables** — rejected: it changes the log table schema. A separate systems registry was also deferred; the prefix is enough for now.

## Consequences

- Log users see no change: same tools, same schema, same outputs. Existing tests must stay byte-identical.
- Trace setup costs one join and the storage of a copy. Setup reports both.
- Metric and trace tables accept integer epoch timestamps with an explicit unit (s, ms, µs, ns), guessed from magnitude and confirmable at setup. Log tables keep today's behaviour; epoch support for logs would be a separate change with its own regression proof.
- Every change tool reports coverage per service (logs / metrics / traces: yes or no), so "no data" is never shown as "no change".
- Wide metric files (one column per series) are not read; converting them to long format is the data owner's job. The extractor never parses column names for meaning.
