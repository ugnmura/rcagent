# SereneDB Log Extractor

An MCP server that lets an agent point SereneDB at logs and analyze them — grouping recurring messages into templates, pulling out their parameters, following them over time, and inspecting the entries around an occurrence — and explain the findings to people in plain language.

## Language

### Logs

**Entry**:
One log record. In a raw log an entry may span several physical lines (e.g. an error followed by its stack trace); in a structured log it is one record.
_Avoid_: Line, row, event, record

**Raw log**:
A log source whose entries are plain text; fields like timestamp and level must be parsed out of the text. Raw logs are copied into a log table once, so that multi-line entries are joined.
_Avoid_: Unstructured log, text log

**Structured log**:
A log source whose entries already carry named fields (e.g. Parquet, JSON lines). Structured logs are read in place when SereneDB can reach them; a local file outside the mounted folder is copied instead.
_Avoid_: Parsed log

**Log source**:
Where log entries originate: a local file, a set of files, a remote URL (HTTP/S3), or an existing SereneDB table. Remote and large sources are read where they sit, never downloaded.

**Log table**:
The SereneDB relation the tools query for one log source, holding one application's logs — a view over the source when it is read in place, or a real table when its entries were copied in.
_Avoid_: Dataset

**Field roles**:
The mapping from a log table's columns to the meanings the tools rely on: timestamp, message, level, service, host, component, and trace id. A role the log table lacks is simply absent.
_Avoid_: Schema, column mapping

**Log time zone**:
The time zone a log table's timestamps were written in when they carry none, chosen at setup: the one given, else the line format's own (BGL logs US Pacific local time), else UTC. Results show times in it unless another zone is asked for.
_Avoid_: Default time zone, display zone

**Setup**:
The one-time step that turns a log source into a log table: inspect the source, propose field roles, have them confirmed, and record them with an empty template catalog.
_Avoid_: Import, ingestion, onboarding

### Analysis

**Template**:
The fixed shape of a recurring log message with its varying parts replaced by placeholders; entries that differ only in those parts share one template.
_Avoid_: Pattern, signature, group

**Parameter**:
One varying part of a template — the value a placeholder stands for in a given entry. Each parameter has a name, first guessed from the surrounding text and renamable; the name describes the template, not any one question.
_Avoid_: Variable, field

**Template catalog**:
The templates discovered so far for one log table, kept in SereneDB and built up across surveys and sessions. Catalogs are not shared or merged across log tables. A catalog holds what surveys observed plus parameter names, but never judgments about a template (such as "noise"), since those depend on the question being asked.
_Avoid_: Template store, pattern library

**Survey**:
A cheap, approximate first look at a log table: filter, sample, and report the top templates with estimated counts and where they occur.
_Avoid_: Overview, scan

**Investigation**:
Exact, targeted analysis of templates chosen from a survey — exact counts, parameters, trends, and context.
_Avoid_: Drill-down, deep dive

**Estimate**:
A number derived from a sample rather than counted over every entry in scope. An estimate always travels with its method and margin, and must be presented to the end user as an estimate.
_Avoid_: Approximation, guess

**Exact count**:
A number counted over every entry in scope.

**Trend**:
How a set of templates' counts change across time buckets within a period, compared with the preceding period of equal length, including on how many buckets each template was present.

**Occurrence**:
One entry that matches a given template, identified by its position in the log source so it can be found again.
_Avoid_: Hit, instance, match

**Context**:
The entries shortly before and after an occurrence in time, within a context scope.
_Avoid_: Surrounding lines, neighbourhood

**Context scope**:
Which entries count as neighbours of an occurrence: those sharing the occurrence's values on a chosen set of columns (e.g. the same trace, or the same service and host), or everything. Only scopes whose columns exist in the log table are available; "everything" always is.

### Metrics and traces

**Metric table**:
The SereneDB relation holding one system's metrics in long form: one row per time, service, metric name and value. Read in place like a structured log. Wide files (one column per series) are converted by the data owner first.
_Avoid_: Metrics dataset, time series table

**Series**:
All values of one metric for one service in a metric table, e.g. `cartservice` / `cpu`.
_Avoid_: Signal, column

**Trace table**:
The SereneDB table holding one system's spans, one row per span, copied in once at setup so each span's self time can be stored with it.
_Avoid_: Trace dataset, span log

**Span**:
One timed unit of work inside a trace: which service did which operation, when, for how long, with which parent span and status.
_Avoid_: Event, call

**Operation**:
The name of what a span did within its service (e.g. `/GetCart`). Operations are to spans what templates are to entries: the unit the tools count and compare.
_Avoid_: Endpoint, method

**Self time**:
A span's duration minus the time covered by its child spans: the time the service spent itself rather than waiting on others. Change tools rank trace latency by self time so a caller is not blamed for its callee.
_Avoid_: Exclusive time, own time

**Edge**:
A caller → callee pair of services seen in parent and child spans, with the latency and errors of those calls.
_Avoid_: Link, dependency

**Pivot**:
The time an investigation compares around: the window before it is the baseline, the window after it is the incident. Given in the question when the detect time is known.
_Avoid_: Detect time (in tool names), anchor

**Change**:
How far a series, operation or log rate moved from before the pivot to after it, as a robust z-score: the shift of the median in units of the baseline's typical deviation (1.4826 × MAD). A change says what moved, never what caused it.
_Avoid_: Anomaly score, root cause score

**Coverage**:
Which of logs, metrics and traces exist for a service. Tools report it so that "no data" is never read as "no change".

**Table prefix**:
The shared start of the names of one system's log, metric and trace tables (`rca_07_`), which is how tools find the tables that belong together.
_Avoid_: Group, case (outside the benchmark)

### Indexes

**Filter index**:
A small index over a log table's few-valued and identifying columns (timestamp, level, service, component, trace id) that makes filtering and value lookup fast. Optional; built only when the user explicitly chooses it.

**Search index**:
An optional full-text index over a log table's message; built only when its storage cost is justified by how the logs will be queried.
_Avoid_: FTS, inverted index (outside implementation discussion)
