# Reference

What the [README](../README.md) leaves out: tools in full, evidence records, the ranking score, large datasets, the
base corpus, team ownership, configuration, security, indexes, time zones, tests and all known limits.

- [Requirements checklist](#requirements-checklist): each requirement of the brief and where it is met
- [Tools](#tools): every tool with its inputs and outputs
- [Evidence records](#evidence-records)
- [How "what first" is decided](#how-what-first-is-decided)
- [Large datasets: TextBench](#large-datasets-textbench-remote-parquet-1-billion-rows-per-file)
- [The base corpus and the loader](#the-base-corpus-and-the-loader)
- [Team ownership](#team-ownership)
- [Configuration](#configuration)
- [Running SereneDB in Docker](#running-serenedb-in-docker)
- [Reader and writer roles](#reader-and-writer-roles)
- [Passwords](#passwords)
- [Private S3 / HTTP sources](#private-s3--http-sources)
- [Indexes](#indexes)
- [Time zones](#time-zones)
- [Safety](#safety)
- [Running the tests](#running-the-tests)
- [Known limits](#known-limits)

## Requirements checklist

Each requirement of the challenge brief, in its own words, and where this repository meets it. "Worked
investigation" means the [README section](../README.md#worked-investigation-one-corpus-three-roles) and the full
write-up in [docs/worked-investigation.md](worked-investigation.md).

| Brief requirement | Where it is met |
|---|---|
| An agent answers at least one question for each of the three roles, with relevant evidence, an appropriate level of detail and a next step suited to that role | [Worked investigation: one corpus, three roles](../README.md#worked-investigation-one-corpus-three-roles) (README) and [docs/worked-investigation.md](worked-investigation.md) sections 1 to 3 (engineer, team lead, manager). Role workflows in [src/serenedb_extractor/prompts.py](../src/serenedb_extractor/prompts.py), served as MCP prompts and as `/engineer`, `/team-lead`, `/manager` |
| Uses both retrieval and aggregation on BGL and OpenStack. At least one answer uses full-text search | `search_logs` (text search with time and field filters) and `get_context` (nearby events) in the engineer answer. See [Tools](#tools) |
| At least one aggregation over the whole base corpus, such as counts by dataset or mapped team. State the data scope and any filters | `count_logs` with no `log_tables` counts every log table, by team, component or level, in the team-lead and manager answers. Every result starts with "How this was measured" (period, filters, exact or sampled) |
| Practical recommendations supported by the findings: what to check or fix first and why | "Next check" (engineer), "Investigate first" (team lead) and the ranked risks with owner and action (manager), in the [README](../README.md#worked-investigation-one-corpus-three-roles) and [docs/worked-investigation.md](worked-investigation.md) |
| Exposes search and summary capabilities as tools whose descriptions explain purpose, inputs and outputs | [Tools](#tools). The docstrings in [src/serenedb_extractor/server.py](../src/serenedb_extractor/server.py) follow "Use when / Inputs / Returns" |
| Shows its work: executed queries and results behind every claim. Hypotheses and limitations labelled | [Evidence](#evidence-records) (`[Qn]` handles, `show_evidence`). Full queries and results in [docs/worked-investigation-transcript.md](worked-investigation-transcript.md). "Possible cause (hypothesis, not established by the logs)" and "What the data does and does not establish" in the worked investigation (README and docs) |
| Search returns a limited set of entries, aggregation returns calculated counts or trends, and truncation is indicated | Default limits per tool, exact totals with "showing N of M" and a "cut" marker, `trend` per period. See [Tools](#tools) |
| Runs from a clean checkout: connect to SereneDB, load the base data, start the agent workflow | [Quick start](../README.md#quick-start) and [The base corpus and the loader](#the-base-corpus-and-the-loader) |
| A public repository with a README explaining the workflow, setup, how to run it and known limitations | The [README](../README.md) and [Known limits](#known-limits) |
| One worked investigation of a real issue, with questions, tool calls, executed queries, results, and each role's answer and action | [README section](../README.md#worked-investigation-one-corpus-three-roles), full write-up in [docs/worked-investigation.md](worked-investigation.md), and its [transcript](worked-investigation-transcript.md) |
| A presentation or demo of no more than 5 minutes, and slides | Talk script, slides and video in `docs/presentation/` and `presentation/` |
| Optional: the agent manages its own workspace (create an index for an investigation and remove it after) | `create_index` (with a `dry_run` size and time estimate) and `drop_index`. See [Indexes](#indexes) |
| Optional: larger datasets, such as the remote OpenTelemetry Parquet data | [Large datasets: TextBench](#large-datasets-textbench-remote-parquet-1-billion-rows-per-file) |
| Optional: phrase and fuzzy matching | `search_logs` through the search index: phrase search finds the words in order (`ts_phrase`), `fuzzy=True` matches each word within a typo or two (`ts_levenshtein`). Without the index, text search is an exact substring scan and fuzzy is refused |
| Optional: row-level security per role | Not implemented. There is a reader/writer split of database roles ([Reader and writer roles](#reader-and-writer-roles)), not per-role row access |
| Optional: correlate logs with traces or metrics | Metric and trace tables next to the log tables. `telemetry_overview` shows a system's logs, metrics and traces around one moment, per service. `metric_changes`, `metric_series`, `trace_changes` (self time and network time per call) and `get_trace` go deeper. RCAEval held-out root cause: AC@1 96.3% over 348 trials ([evaluation](EVALUATION.md#rcaeval-logs-metrics-and-traces)) |

## Tools

The agent picks tools by their descriptions: what the tool does, when to use it, its inputs and what it returns. The
server instructions add a "which tool for which question" guide.

| tool | use it for | main inputs | returns |
|---|---|---|---|
| `describe_logs` | orientation: tables, fields, time range, value spellings. **Start here** | `log_table`, `find_values={"level": "err"}` | per table: field roles (incl. team), entry count, time range, context scopes, top values (exact when affordable) |
| `count_logs` | **aggregation**: how many, per team / component / level / day, over one or **all** log tables | `group_by` (≤3 of team, component, level, host, service, any column, `time:<n>m\|h\|d`), `filters`, `text`, `start`/`end` | per table the total and each group's count and share. A cut keeps the largest groups. A combined line for shared values. Exact unless marked |
| `search_logs` | **full-text search**: the entries matching words and/or filters in a time window | `text`, `fuzzy`, `filters`, `start`/`end`, `order`, `limit` | total matches, then up to 50 entries (time, fields, team, message, template tag, occurrence ID). Says when cut |
| `get_context` | nearby events before and after one entry | `occurrence` (from search/locate), `scope` (same trace / host / everything), `window_minutes`, `before`/`after` | the entries in time order, the occurrence marked → |
| `survey` | which kinds of messages (templates) occur, with counts | `filters`, `start`/`end`, `exclude`, `limit` | templates ranked by count with share, components, teams and an example. Exact or a stated sample. `NEW TO CATALOG` marks a template seen for the first time (not a problem that started now) |
| `locate_occurrences` | exact counts of chosen templates by where and when | `templates` (T-ids), `group_by` (team, host, `time:1h` …) | per template the total and per-group counts with example occurrence IDs |
| `trend` | rising, falling, new or persistent: a period against the one before | `start`, `end`, `templates` (default: the period's own largest, found by a survey and saved to the catalog), `bucket` hour\|day, `exact` (default: every entry counted when that fits the time budget, else a stated sample) | per template the counts per bucket, change, presence, components and teams. Refuses to call anything new across gaps |
| `extract_params` | the values inside a template (nodes, status codes, latencies) | `template`, `by` | top values per parameter. Min / p50 / p95 / max for numbers |
| `rank_problems` | **what to look at first**: warning-and-worse problems ranked by a stated, measured score | `start`, `end`, `log_tables`, `min_level` warning\|error\|fatal\|critical, `filters`, `limit` | per problem its score (0-18) and the points behind it: exact entries and levels, change against the preceding period, days (or hours) present, distinct hosts, components and owning team |
| `show_evidence` | the queries and results behind any earlier answer | `ids` (Q-handles) | the tool call, every query with its time and row count, the result |
| `show_team_ownership` | who owns what, and whether the teams are official | `log_table`, `coverage` | rules by team, their source, recent changes, entries per team and components without a team |
| `edit_team_ownership` | import the supplied ownership CSV, fix a team, export the rules | `action` import\|set\|remove\|export\|reset, `csv_path`/`csv_text`, `mode`, `rules`, `team`, `dry_run` | the rules added, changed and removed, then coverage |
| `inspect_source` | look at a new source before setting it up | `source`, `format_hint` | columns, samples, size, proposed roles |
| `setup_log_table` | register a source (Parquet/JSON/CSV that SereneDB can reach is read in place, a file only on this machine is copied, raw text is parsed and copied) | `name`, `source` (several files: `part_{000..009}.parquet`), `roles`, `format_hint`, `timezone` | roles, entries, files, size, setup time (copies too), index estimates |
| `create_index` / `drop_index` | build an index for repeated questions, remove it after the investigation | `log_table`, `kind` filter\|search, `dry_run` | size and build time (estimated with `dry_run`) |
| `rename_parameter` | a clearer name for a template parameter | `template`, `old_name`, `new_name` | the template |
| `run_sql` | last resort: one read-only SQL statement (e.g. latency percentiles) | `sql`, `limit` | rows, cut to 50. Cost-checked first |

Shared inputs: `start`/`end` are ISO times (end exclusive) in `timezone` (default: the log table's zone). A local
time that occurs twice (clocks going back) is refused with both UTC offsets to choose from. One that does not exist
(clocks going forward) is explained. `filters` is `{"role or column": value or [values]}`.
`confirmed_cost` runs a step the tool called **TOO EXPENSIVE** once the user agrees. Default result limits (survey
30 templates, search 50 entries, context 10 before and after) can be raised per call up to 10× ([Configuration](#configuration)).

Time buckets (`time:1h`, `time:1d`, `time:7d`, trend's `bucket`): an hour is a real hour labelled with its UTC
offset, so the night clocks go back has two 01:00 hours (`01:00-07:00` and `01:00-08:00`). A day is a local calendar
day (23 or 25 hours across a clock change). Weeks and longer buckets start on a Monday. A cut grouping keeps the
largest groups in reading order ("showing the 25 largest of 31,482 groups").

Occurrence IDs (from `search_logs` and `locate_occurrences`, for `get_context`):

| source | ID | note |
|---|---|---|
| Parquet / JSON / CSV file read in place | `<file>#<n>`, e.g. `/logs/bgl.parquet#222715` | the bare file name (`bgl.parquet#222715`) also works. `n` is a position SereneDB gives: the row for Parquet, a byte offset for JSON, not a line number for CSV |
| copied (raw text, or a file only on this machine) | `e:<n>` | a file's own `entry_id` column is kept as `source_entry_id` |
| database table | `pk:<value>` | when the table has an order column |

## Evidence records

Every tool result ends with a footer like this:

```text
Evidence [Q46]: the queries that produced this result. Cite [Q46] next to numbers taken from it; show_evidence(['Q46']) gives every query in full and the result again.
  Q46.5 (0.08 s, 16 row(s)): SELECT k0, k1, count(*) AS n FROM (SELECT 1 AS one, coalesce(((CASE WHEN ("component")::varchar ILIKE 'KERNEL' THEN 'Node OS' …
  plus 8 metadata lookups (columns, Parquet statistics) to plan the cost (show_evidence lists them)
```

Every query a tool call ran (parameters filled in, time, row count) is stored with the call's arguments and result
in `extractor.evidence` under a handle (`Q46`).

No evidence, no claim. Answers cite the handle next to every statement about the logs, not only numbers: a time, a
quoted message, a node, a team, a trend, "new" or "absent" (`it started at 17:17:44 PDT on node R30-M0-N9-C:J16-U01
[Q5]`). A sentence without a handle is a labelled hypothesis, a recommendation, or a statement of what the logs do
not show. The answer's **Evidence** section lists each cited handle with what it measured and its main query.
`show_evidence` returns the full record. Failed calls keep evidence too, so a timeout shows which query ran how long.

## How "what first" is decided

`rank_problems` makes the order measured and checkable, not the agent's judgement. Per log table it surveys entries
at warning or above, maps each finding to the broadest catalog template (so IDs and counts agree with `trend`), and
counts every candidate exactly over the period and the one before. Points come from fixed thresholds:

| factor | 3 | 2 | 1 | 0 |
|---|---|---|---|---|
| severity (counted twice) | fatal / critical | error / severe / failure | warning | none |
| change against the preceding period | new, or +50% or more | +10% to +50% | within ±10%, or not comparable (the data does not cover both periods, or has a gap) | falling |
| persistence: share of whole days with data that it appears in (hours for a period under two days, or when fewer than 3 whole days have data. Not judged, 0 points, when even hours give fewer than 3) | 75% or more | 40% or more | 10% or more | less |
| spread: distinct hosts (else services, else components) | 100 or more | 10 or more | 2 or more | one |
| share of the entries ranked | 10% or more | 1% or more | 0.1% or more | less |

Severity is the level most of a problem's entries have: fatal or critical (also crit, emerg, alert, panic) 3, error,
severe or failure 2, warning 1. `min_level` (warning, error, fatal or critical) picks the levels ranked. A gap is 3 or
more hours, or a whole day, without entries. Gap buckets are left out of persistence, and nothing is called new
across a gap. Ties go to the problem with more entries.

Each problem's points appear next to the numbers behind them. The score only orders what to look at first. It is
not a risk, impact or cost figure, and it counts entries, not incidents. A single-node storm scores low on spread even
with most entries, so the manager prompt has the agent add such items from other tools and say why.

## Large datasets: TextBench (remote Parquet, 1 billion rows per file)

Point setup at the URL. Nothing is downloaded:

```text
set up https://public-pme.s3.eu-west-3.amazonaws.com/text_bench/part_000.parquet as a log table called textbench
```

Several files make one log table: `…/text_bench/part_{000..009}.parquet` covers the first five hours (10 files,
10 billion rows). Roles are proposed from the OpenTelemetry column names (`Timestamp`, `Body`, `SeverityText`,
`ServiceName`, `TraceId`). Teams come from `ServiceName` through the ownership table.

Setup stays fast on a remote source:
- It reads only metadata: the Parquet footer (row count, row groups, sizes) and 5 sample entries of the plain
  columns, not the large attribute maps.
- It estimates index sizes from Parquet column sizes. No trial build (that would pull a million entries over the
  network).
- One-off metadata reads may run up to the maximum query time, not the 60 s default.
- The result reports the setup time.

After setup, every tool checks the predicted cost first. A big scope gets a **block sample** of whole row groups
(stated, with a margin), or the tool asks before reading more.

**Measured on the real S3 file** (`part_000`, about 1 billion rows, one shared 16-CPU / 128 GB HPC node, details and
raw logs in [HUGE_DATASETS.md](HUGE_DATASETS.md)):

| Step | Time |
|---|---|
| `setup_log_table` on the S3 URL (metadata only, nothing downloaded) | 1.97 s |
| `create_index(kind="search")` over all ~1B rows, built once (needs more than 64 GB of RAM) | 69.9 s |
| `search_logs` "error" over the **whole file** (30 minutes of data) through that index (median of 3) | 4.18 s |
| `search_logs` "error" over **one minute** of the file's 30, no index (exact scan, median of 3) | 2.88 s |

The two searches cover different scopes, so this is not a speed comparison.

## The base corpus and the loader

`scripts/load_base_corpus.py` downloads, converts and sets up. Each step is skipped when its output exists. `--force`
redoes it.

| log table | source | entries | span | columns (roles) |
|---|---|---|---|---|
| `bgl` | Loghub BGL (Blue Gene/L supercomputer) | 4,747,963 | 2005-06-03 to 2006-01-04 | `ts` (timestamp), `level`, `component`, `node` (host), `event_type`, `alert_label` (BGL's alert category, NULL for non-alerts), `message`, `entry_id` (line number, order) |
| `openstack` | Loghub OpenStack (nova-api / -compute / -scheduler) | 207,636 | 2017-05-14 to 2017-05-17, with gaps | `ts`, `level`, `component`, `service`, `request_id` (trace), `tenant_id`, `user_id`, `instance_id`, `client_ip`, `http_method`, `http_path`, `status`, `response_bytes`, `latency_s`, `anomaly_instance` (one of the 4 labelled anomalous VMs), `source_file`, `message` |

Parsing notes:
- OpenStack logs a traceback as many lines with the same time, process and component. The loader joins them, so a
  stack trace counts once (207,820 raw lines → 207,636 entries).
- A few hundred malformed BGL lines (a missing node name, stray text) are parsed by anchoring on the event type.
  Lines that still fail keep only their message, so whole-corpus counts stay complete.
- Row groups hold 50,000 entries, so sampled estimates can spread across the whole period.
- `bgl` timestamps are real instants from BGL's epoch column, shown in `America/Los_Angeles`, BGL's local time
  (see [Time zones](#time-zones)). `openstack` is in UTC. Rerunning the loader converts a `bgl` file from an older
  loader and fixes the zone of an older table.

Data licence: Loghub is research-use only and needs a citation: Zhu et al., *Loghub: A Large Collection of System Log
Datasets for AI-driven Log Analytics*, ISSRE 2023. For BGL, also Oliner & Stearley, DSN 2007.

## Team ownership

`count_logs`, `search_logs`, `survey`, `trend` and `locate_occurrences` can group and filter by **team**. Team is
derived: a log table has it when ownership rules cover its components (or services). The rules live in
`extractor.ownership`.

**The shipped rules are a stand-in.** We did not have the challenge's own team-ownership table, so a fresh database
starts with a fictional platform organisation we wrote,
[`src/serenedb_extractor/data/ownership.csv`](../src/serenedb_extractor/data/ownership.csv). Answers and
`describe_logs` say when a team comes from the stand-in. Replace it with the supplied table (see below).

| team | owns (BGL component / OpenStack component / TextBench service) |
|---|---|
| Node OS | BGL `KERNEL`: compute-node kernel, memory and cache faults, interrupts, core dumps |
| HPC Applications | BGL `APP`: user jobs and the I/O daemon (ciod) |
| Control System | BGL `MMCS`, `BGLMASTER`, `CMCS` |
| Hardware Reliability | BGL `HARDWARE`, `MONITOR`, `DISCOVERY` |
| Interconnect | BGL `LINKCARD`, `SERV_NET` |
| Cloud API | OpenStack `nova.osapi_compute.*`, `nova.api.*`, `nova.metadata.*` |
| Compute Service | OpenStack `nova.compute.*`, `nova.conductor.*`, `oslo_service.*` |
| Virtualization | OpenStack `nova.virt.*` |
| Scheduling | OpenStack `nova.scheduler.*` |
| Identity & Access | OpenStack `keystonemiddleware.*` |
| Storefront, Checkout & Payments, Fulfilment, Catalog & Recommendations, Platform | TextBench (OpenTelemetry demo) services |

A rule is `(log_table pattern, role, value pattern, team)`. Patterns are case-insensitive. `%` matches any text,
everything else is literal, `_` included (`SERV_NET` matches only `SERV_NET`). The most specific rule wins: an exact
name beats a pattern, then the longer fixed text wins. Between rules on the same value, one naming the log table
exactly (`bgl`) beats a table pattern (`bgl%`). With the stand-in, every BGL and OpenStack entry maps to a team.
Entries no rule covers are in team "Unassigned".

### Importing and editing the ownership table

Ask the agent ("use the ownership table in ~/Downloads/teams.csv"), or call the tools yourself:

| call | what it does |
|---|---|
| `show_team_ownership()` | the rules by team, where each came from (imported file, set by hand, stand-in), the latest changes, and per log table the entries per team plus the components no rule covers |
| `edit_team_ownership(action="import", csv_path="teams.csv")` | import a CSV. Headers are matched loosely: `dataset`/`log_table`/`table`, `component`/`service`/`pattern`, `team`/`owner`, optional `role` and `area`/`description`. Separator `,` `;` tab or `\|`. `log_table="bgl"` names the log table when the file has no such column. |
| `mode="replace"` (default) / `"merge"` / `"replace_all"` | replace the rules of the log tables the file covers (others stay) / add and update only / drop every other rule |
| `edit_team_ownership(action="set", rules=[{"log_table": "bgl", "component": "KERNEL", "team": "Kernel"}])` | add or change single rules |
| `edit_team_ownership(action="remove", team="Kernel")` or `rules=[...]` | remove a team's rules, or single rules |
| `edit_team_ownership(action="export", csv_path="/Users/me/ownership.csv")` | write the rules to a file to edit and import again. Needs a full path to a `.csv`/`.tsv` file (a relative one is refused). Replaces an existing file only with `overwrite=True`. With `dry_run=True` it only says what it would write |
| `edit_team_ownership(action="reset")` | back to the stand-in |
| `dry_run=True` | show the change without making it |

Every change reports what was added, changed and removed, then the affected log tables' coverage. A component the
file misses shows up at once, not silently as "Unassigned". Changes are logged in
`extractor.ownership_changes`. After the first import or edit, a restart never adds the stand-in back.

## Configuration

| variable | meaning | default |
|---|---|---|
| `SERENEDB_READER_URL` | connection URL for every query. Should be a SELECT-only role | **required** |
| `SERENEDB_WRITER_URL` | connection for setup, index builds and catalog writes. A role that owns only the `extractor` schema | the reader URL (single-role mode, with a one-time warning) |
| `LOGS_HOST_DIR` / `LOGS_CONTAINER_DIR` | the mounted logs folder on this machine and where SereneDB sees it (e.g. `~/logs` → `/logs`) | unset. Set both or neither |
| `SERENEDB_ALLOW_SQL` | `1` lets `run_sql` work in single-role mode | off |
| `SERENEDB_SOURCE_DIRS` | comma-separated folders on SereneDB's disk that may be read in place (see [Safety](#safety)) | unset: any folder that is not private |

Built-in limits (not configurable in this prototype):

- Query timeout: 60 s by default, 600 s at most. A timed-out query is cancelled in SereneDB, and the result says what
  timed out and how to narrow it. A run the user approved at a predicted cost gets a longer timeout, up to the
  maximum. Anything predicted to take longer is not offered as "run anyway".
- Survey sample: about 100,000 entries after filters.
- Result sizes: survey 30 templates, extract_params 10 values per parameter, get_context 10 entries before and after
  (messages cut at about 500 characters), search_logs and run_sql 50 rows. Each can be raised per call up to 10×
  (run_sql up to 500 rows). Every cut result says so ("showing 30 of 412").

Everything the extractor stores (log table definitions, the template catalog, indexes) lives in the `extractor`
schema. Your own data is never modified.

## Running SereneDB in Docker

```sh
docker run -d --name serenedb \
  --platform linux/amd64 \
  -e SERENEDB_HOST_AUTH_METHOD=trust \
  -p 127.0.0.1:7890:7890 \
  -v ~/logs:/logs:ro \
  serenedb/serenedb@sha256:6d41ac6577e797289158786a2015ba8fbd6875feadb5c491518e166c011058c9
```

- **Image:** the digest is the `serenedb/serenedb:latest` of 2026-10-18 the extractor was built and tested against
  (also used by `scripts/test-db.sh`). Newer images may differ.

- **Apple Silicon / arm64:** the pinned image has no arm64 build. Emulated (`--platform linux/amd64`) it is slow and
  may crash. On arm64 use `serenedb/serenedb:26.09.2`, a native build (multi-arch digest
  `sha256:f9681a19f7f1290836e8ab200f0b1907dbe2c8380102a09f043a5c44e3ffa2b2`), without `--platform`. The team's
  benchmark reruns of this version ran on it. Drop the flag on an x86-64 host too.
- **Bind to localhost** (`-p 127.0.0.1:7890:7890`) unless you set up passwords and network access on purpose.
  SereneDB speaks the Postgres wire protocol on port 7890.
- **Logs mount:** mount your logs folder **read-only** (`:ro`) and set `LOGS_HOST_DIR=$HOME/logs` and
  `LOGS_CONTAINER_DIR=/logs`. Then use paths on your machine, and SereneDB reads the files in place. Structured files
  outside the mount are streamed in and copied. Raw text logs are always parsed and copied (multi-line entries
  joined).
- SereneDB reads remote Parquet/JSON/CSV (`https://…`, `s3://…`) in place. The extractor downloads nothing.
- CSV: give `format_hint="csv"` when the name does not end in `.csv` or `.tsv`. A copied CSV's separator is detected
  (`,`, `;`, tab or `|`), standard quoting applies, and every column is kept, a repeated name getting a suffix
  (`level`, `level_1`). A file with its own `filename` or `file_row_number` column cannot be read in place (SereneDB
  adds those columns). The tool says so, and a copy works.

For tests, `scripts/test-db.sh` starts (or reuses) a pinned container on `127.0.0.1:17890` and prints the
`SERENEDB_TEST_URL` (see [Running the tests](#running-the-tests)).

## Reader and writer roles

Two roles let SereneDB itself, not just the extractor, enforce what each connection may do:

- **reader**: runs every query. Read access to the `extractor` schema only, no writes (but see the note on
  container files below).
- **writer**: runs setup, index builds and catalog writes. Owns the `extractor` schema and nothing else.

Give the extractor a **database of its own** (below: `logs_extractor`), not `postgres`. The writer needs `CREATE` on
it, and a dedicated database keeps that privilege away from everything else. Log files are read through views in that
database wherever they are. Only existing SereneDB tables you want to analyze must live in it.

As an admin (the `postgres` user of your container):

```sql
CREATE DATABASE logs_extractor;
CREATE ROLE extractor_writer LOGIN PASSWORD 'change-me-writer';
CREATE ROLE extractor_reader LOGIN PASSWORD 'change-me-reader';

-- the writer creates (and so owns) the extractor schema on first start
GRANT CREATE ON DATABASE logs_extractor TO extractor_writer;

-- only if you analyze existing tables: the writer needs to read them (log tables are views over them)
-- GRANT SELECT ON my_app_logs TO extractor_writer;
```

Connect the server once (any question will do). The first answer may be a permission error naming
`SERENEDB_READER_URL`, since the reader cannot yet read the new tables. Then grant access, as `extractor_writer` or
the admin:

```sql
GRANT USAGE ON SCHEMA extractor TO extractor_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA extractor TO extractor_reader;
```

**Re-run the `GRANT SELECT ON ALL TABLES IN SCHEMA` after setting up each new log table.** SereneDB accepts
`ALTER DEFAULT PRIVILEGES` but does not yet apply it to new objects. Until then the answer names the refused
connection and points here, e.g.
"SereneDB refused this to the role in SERENEDB_READER_URL: permission denied for view lt_web. Grant it access as in
the "Reader and writer roles" section of docs/reference.md: …". The reader reads log files through the writer's
views and needs no file access. Make neither role a superuser.

The extractor runs `CREATE SCHEMA IF NOT EXISTS extractor` at start-up, which SereneDB checks against the database
even when the schema exists. Hence `CREATE` on the database. It also lets the writer create other schemas there (hence
the dedicated database). The extractor never creates anything outside `extractor`.

Checked against the pinned test image: setup, survey, index build, text search and `run_sql` all work with the two
roles once granted.

**Why this matters (the `run_sql` backstop).** `run_sql` runs the assistant's own SQL. The extractor checks it
first (one read-only statement, only `extractor` tables, allowlisted functions), but the database role is the real
guard against writes or reads beyond its grants. One gap remains: in the SereneDB version tested, **any role can call
file-reading table functions** (`read_text`, `read_parquet`, …) on container paths, and that cannot be revoked. So
`run_sql` refuses every table function and every non-`extractor` relation, and the logs mount should be read-only and
hold only logs.

### Single-role mode

With only `SERENEDB_READER_URL` set, one connection does everything, unlimited by SereneDB. A session's first
result says so once. `run_sql` is off unless `SERENEDB_ALLOW_SQL=1`. Fine for a local container with your own logs.
Use two roles for anything shared.

## Passwords

Anything passed as `-e …URL=postgresql://user:password@…` lands in plain text in your shell history and in Claude
Code's MCP configuration. The extractor connects through libpq (via psycopg), so leave the password out of the URL
and use libpq's own mechanisms:

- a password file: `~/.pgpass` (or the file named by `PGPASSFILE`), mode `0600`, one line per role:

  ```text
  localhost:7890:logs_extractor:extractor_reader:the-reader-password
  localhost:7890:logs_extractor:extractor_writer:the-writer-password
  ```

- or a connection service file (`~/.pg_service.conf`, or `PGSERVICEFILE`) with a section per role, and URLs like
  `postgresql:///?service=extractor_reader`.


## Private S3 / HTTP sources

Credentials are configured **in SereneDB**, never given to the extractor. The extractor never receives, stores or
echoes them. If SereneDB can't read a source, you get a plain-language message.

```sql
CREATE SECRET logs_s3 (
    TYPE s3,
    KEY_ID 'AKIA…',
    SECRET '…',
    REGION 'eu-west-3',
    SCOPE 's3://my-log-bucket'
);
```

`CREATE SECRET` lasts until SereneDB restarts. `CREATE PERSISTENT SECRET` survives restarts but is stored
unencrypted. Other types (`http`, `gcs`, `r2`, `azure`) work the same way. See SereneDB's Secrets Manager docs.

## Indexes

**No index is ever built unless you ask for one.** Big sources first show an estimated size and build time (from a
trial build on a sample). You can also ask for just the estimate.

- **Filter index**: the timestamp, level, service, component and trace fields. `describe_logs` then lists each
  field's distinct values (and `find_values` lookups) exactly and instantly from the index. Counts, surveys, trends
  and rankings still read the entries.
- **Search index**: the message text plus the same fields and the host. It serves `search_logs`, makes text search
  fast and enables fuzzy search (finding misspellings). Only the message, timestamp and filtered fields must be
  in the index, so it works when some fields are JSON paths. It matches **whole words only**: it
  does not find `disk` inside `diskfull`. When a plain scan is affordable, the scan is used instead (exact substring
  matching). Every answer from the index says "whole words only".

Indexes live in the `extractor` schema next to their log table.

## Time zones

Each log table has its own time zone: the one its zoneless timestamps were written in. Setup uses the zone you give
(`timezone`), else the line format's own zone, else UTC. The `bgl` line format's zone is `America/Los_Angeles`, since
Blue Gene/L logs record US Pacific local time. Timestamps are stored as real instants (the loader's `bgl` takes them
from BGL's epoch column). For a source that already has real instants (a type with a time zone), the zone only sets
how times are shown, and setup and `describe_logs` say so.

Setup refuses a timestamp column that mostly holds no times. Text times, time types and Unix epoch numbers (seconds,
or milliseconds when that large) count. Reading is lenient: a non-time value gives an entry without a time, not a
failed query.

Results show times in the log table's zone unless a tool gets `timezone`. Zoneless times you pass are read in that
zone too, so dates mean what they mean in the log. Outside UTC, every result says so, and times carry their UTC
offset (`2005-06-03 16:17:40-07:00`). `run_sql` runs in the zone of the log tables it reads (UTC when they differ), so
timestamps print with their offset and `date_trunc`, `::date` and time literals follow the log's clock.
`ts AT TIME ZONE 'UTC'` gives UTC. A copied log table keeps its zone. To change it, set it up again under another
name.

## Safety

The tools read only log and data files. A local or container path needs a log or data extension (`.log .txt
.out .err`, `.parquet .pq`, `.json .jsonl .ndjson`, `.csv .tsv`, text ones optionally `.gz`). A `format_hint` does not
lift this. Hidden files and folders (`~/.ssh`, `~/.aws`), system locations (`/etc`, `/proc`, `/sys`, `/dev`, `/root`,
the keychains) and `..` that leaves the logs folder are refused, also after following links on this machine.
Wildcards are allowed only in the file name, which must start with a plain character (`part_*.parquet`, not
`*.parquet`, which would also match hidden files). With `SERENEDB_SOURCE_DIRS` set, files on SereneDB's disk are read
in place only from those folders. The extractor can't check links there, so set it to be sure. Tables in system
schemas (`pg_catalog`, `information_schema`, `pg_*`) and in the `extractor` schema can't be set up as log tables. The
ownership export writes only `.csv`/`.tsv` files and replaces one only with `overwrite=True`. Import reads only
`.csv`/`.tsv`/`.txt` files. Remote URLs are unaffected. `run_sql` has its own limits (see
[Known limits](#known-limits) and [Reader and writer roles](#reader-and-writer-roles)).

## Running the tests

```sh
bash scripts/test-db.sh            # starts/reuses the sdb-test container and prints SERENEDB_TEST_URL
export SERENEDB_TEST_URL=postgresql://postgres@localhost:17890/postgres
uv run pytest
```

Tests that need the database are marked `db` and skipped when `SERENEDB_TEST_URL` is not set. They use a dedicated
database, `SERENEDB_TEST_DB` (default `extractor_test`, created if missing), and drop and recreate the `extractor`
schema there. They refuse to reset a database whose name does not start with `extractor_test`. The test container
runs without passwords, so `scripts/test-db.sh` binds it to `127.0.0.1` only.

## Known limits

This is a prototype:

- **Sources are static snapshots.** Log tables are never refreshed or appended to. Files read in place must not
  change after setup.
- **Remote raw text is not supported.** Remote sources must be Parquet, JSON or CSV. Raw text logs must be local.
- **One log table holds one application's logs.** Template catalogs are not shared between log tables.
- **`run_sql` is restricted:** one read-only statement (SELECT, WITH, set operations or EXPLAIN). Only tables and
  views in the `extractor` schema, always schema-qualified (`extractor.lt_<name>`). Only allowlisted functions
  (string, regex, date/time, math, aggregates, window functions, casts, JSON). No table functions. No column lists on
  CTEs or aliases (`WITH r(n) AS …` is refused, write `SELECT 1 AS n` inside instead). Results cut at 50 rows by
  default.
- **Sampling only for a single Parquet file.** Block samples need one in-place Parquet file. Multi-file globs, JSON,
  CSV and copied tables are counted exactly, or the tool asks first when that exceeds the time budget.
- **Index builds are capped at the server's maximum query time** (600 s by default). A longer build is cancelled,
  leaving no index. `create_index` with `dry_run` warns when its estimate is longer.
- **Catalog writes are single-process.** Survey results, merges and renames are serialized within one server
  process. Concurrent writers to one catalog are not supported.
- **Timings under emulation are not representative.** Estimates and test timings from the amd64 image on an arm64
  machine are slower than native.
- **The shipped ownership table is a fictional stand-in** until the supplied one is imported with
  `edit_team_ownership`. Its rules are keyed by log table name patterns (`bgl%`, `openstack%`, `textbench%`). A log
  table with another name has no team until rules cover it.
- **Evidence records grow without limit** in `extractor.evidence` (one row per tool call). Clear the table when it
  gets large.
- **Gap detection needs an affordable timestamp scan.** When that is too expensive (a huge remote source over a
  long period), `trend` says gaps were not checked.
- **TextBench timings are from one file at commit `6cad141`** on a shared HPC node
  ([HUGE_DATASETS.md](HUGE_DATASETS.md)). Multi-file sources (`part_{000..009}`) work but were not timed, and later
  changes on `main` were not re-timed there.
- **A search index over 1 billion rows needs more than 64 GB of RAM.** The database server ran out of memory at
  64 GB and finished at 128 GB.
