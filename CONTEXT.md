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
A log source whose entries already carry named fields (e.g. Parquet, JSON lines). Structured logs are read in place.
_Avoid_: Parsed log

**Log source**:
Where log entries originate: a local file, a set of files, a remote URL (HTTP/S3), or an existing SereneDB table. Remote and large sources are read where they sit, never downloaded.

**Log table**:
The SereneDB relation the tools query for one log source, holding one application's logs — a view over the source when it is read in place, or a real table when its entries were copied in.
_Avoid_: Dataset

**Field roles**:
The mapping from a log table's columns to the meanings the tools rely on: timestamp, message, level, service, host, component, and trace id. A role the log table lacks is simply absent.
_Avoid_: Schema, column mapping

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

### Indexes

**Filter index**:
A small index over a log table's few-valued and identifying columns (timestamp, level, service, component, trace id) that makes filtering and value lookup fast. Optional; built only when the user explicitly chooses it.

**Search index**:
An optional full-text index over a log table's message; built only when its storage cost is justified by how the logs will be queried.
_Avoid_: FTS, inverted index (outside implementation discussion)
