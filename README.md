# serenedb-extractor

An MCP server that turns log data into answers for three people who ask about the same logs:

- an **engineer** investigating an error: what failed, in which component, what happened just before and after,
  a possible cause and the next check;
- a **team lead** looking at recurring problems: how often, which components and teams, the trend, and what to
  investigate first;
- a **manager** deciding what to prioritise: a short, ranked list of observed risks with an owner and a next
  action each.

[SereneDB](https://serenedb.com) does the searching and the counting. The AI assistant (Claude Code, or any MCP
client) picks the tools, reads the evidence they return and explains it in plain language. No evidence, no
claim: every statement about the logs in an answer cites the query that produced it.

```
question ──▶ agent picks tools ──▶ SereneDB searches / counts ──▶ evidence [Q7] ──▶ answer + recommendation
             (descriptions say       (full text, exact counts,      (queries, filters,      (facts, hypotheses,
              when to use each)       trends, nearby events)          truncation, margins)    next steps per role)
```

It is a prototype built for the *Making Sense of Logs* challenge (National AI Hackathon 2026, SereneDB track).

- **Worked investigation:** [docs/worked-investigation.md](docs/worked-investigation.md) answers one question
  per role on the base corpus, citing every number. The full tool calls, results and queries are in
  [docs/worked-investigation-transcript.md](docs/worked-investigation-transcript.md).
- **How the parts fit:** [CONTEXT.md](CONTEXT.md) (glossary) and [docs/adr/](docs/adr/) (decisions).

## Quick start (from a clean checkout)

You need Docker, [uv](https://docs.astral.sh/uv/) and Claude Code.

```sh
git clone https://github.com/ugnmura/serenedb-extractor && cd serenedb-extractor
uv sync

# 1. SereneDB, with a folder for logs mounted read-only (drop --platform on an x86-64 host)
mkdir -p ~/logs
docker run -d --name serenedb --platform linux/amd64 -e SERENEDB_HOST_AUTH_METHOD=trust \
  -p 127.0.0.1:7890:7890 -v ~/logs:/logs:ro \
  serenedb/serenedb@sha256:6d41ac6577e797289158786a2015ba8fbd6875feadb5c491518e166c011058c9

# 2. the base corpus: downloads BGL + OpenStack from Zenodo (~60 MB), converts to Parquet (~30 s),
#    sets up the log tables `bgl` and `openstack` read in place (~1 s)
export SERENEDB_READER_URL=postgresql://postgres@localhost:7890/postgres
export LOGS_HOST_DIR=~/logs LOGS_CONTAINER_DIR=/logs
uv run python scripts/load_base_corpus.py

# 3. connect Claude Code to the server
claude mcp add serenedb-extractor \
  -e SERENEDB_READER_URL=$SERENEDB_READER_URL -e SERENEDB_ALLOW_SQL=1 \
  -e LOGS_HOST_DIR=$HOME/logs -e LOGS_CONTAINER_DIR=/logs \
  -- uv run --directory "$PWD" serenedb-extractor
```

Then start `claude` in this folder and ask, as each role:

```text
/engineer What failed on BGL on 11 June 2005, and what happened just before?
/team-lead Which problems keep recurring across BGL and OpenStack, and what should we look at first?
/manager What should we prioritise from these logs?
```

`/engineer`, `/team-lead` and `/manager` are project slash commands (`.claude/commands/`). Outside this folder
the same role prompts are served by the MCP server as `/mcp__serenedb-extractor__engineer` (and `team-lead`,
`manager`). You can also just ask in your own words. `/mcp` lists the server with its 18 tools and 3 prompts.

This quick start runs SereneDB with no passwords on 127.0.0.1 and one connection for everything ("single-role
mode"). For anything shared, use a reader and a writer role and keep passwords out of URLs: see
[Reader and writer roles](#reader-and-writer-roles) and [Passwords](#passwords).

No mount? Pass `--docker-cp serenedb` to the loader: it copies the two Parquet files into the container
(`/data/loghub`) and sets the tables up from there.

## The base corpus and the loader

`scripts/load_base_corpus.py` is the loader. It downloads, converts and sets up; every step is skipped when
its output already exists, and `--force` redoes it.

| log table | source | entries | span | columns (roles) |
|---|---|---|---|---|
| `bgl` | Loghub BGL (Blue Gene/L supercomputer) | 4,747,963 | 2005-06-03 to 2006-01-04 | `ts` (timestamp), `level`, `component`, `node` (host), `event_type`, `alert_label` (BGL's alert category, NULL for non-alerts), `message`, `entry_id` (line number, order) |
| `openstack` | Loghub OpenStack (nova-api / -compute / -scheduler) | 207,636 | 2017-05-14 to 2017-05-17, with gaps | `ts`, `level`, `component`, `service`, `request_id` (trace), `tenant_id`, `user_id`, `instance_id`, `client_ip`, `http_method`, `http_path`, `status`, `response_bytes`, `latency_s`, `anomaly_instance` (one of the 4 labelled anomalous VMs), `source_file`, `message` |

Parsing notes:
- A traceback in OpenStack is logged as many lines with the same time, process and component. The loader
  joins those lines into one entry, so a stack trace counts once (207,820 raw lines → 207,636 entries).
- A few hundred malformed BGL lines (a missing node name, stray text) are parsed by anchoring on the event
  type. Lines that still don't parse are kept with only their message, so whole-corpus counts stay complete.
- Row groups hold 50,000 entries, so sampled estimates can spread across the whole period.
- `bgl` timestamps are real instants taken from BGL's epoch column. The table is shown in `America/Los_Angeles`,
  the local time BGL logs (see [Time zones](#time-zones)); `openstack` is in UTC. Running the loader again
  converts a `bgl` file written by an older loader and corrects the zone of a table set up before this.

Data licence: Loghub is research-use only and needs a citation: Zhu et al., *Loghub: A Large Collection of
System Log Datasets for AI-driven Log Analytics*, ISSRE 2023. For BGL, also Oliner & Stearley, DSN 2007.

## Team ownership

`count_logs`, `search_logs`, `survey`, `trend` and `locate_occurrences` can group and filter by **team**. Team
is a derived field: a log table gets one when ownership rules cover its components (or services). The rules live
in `extractor.ownership`.

**The shipped rules are a stand-in.** The challenge supplies its own team-ownership table, which we did not have,
so a fresh database starts with a fictional platform organisation we wrote,
[`src/serenedb_extractor/data/ownership.csv`](src/serenedb_extractor/data/ownership.csv). Answers and
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

A rule is `(log_table pattern, role, value pattern, team)`. Patterns are case-insensitive; `%` matches any text
and everything else is literal, `_` included (`SERV_NET` matches only `SERV_NET`). The most specific rule wins: an
exact name beats a pattern, then the pattern with the longer fixed text; between rules on the same value, one
naming the log table exactly (`bgl`) beats one naming a table pattern (`bgl%`). With the stand-in, every BGL and
OpenStack entry maps to a team. Entries no rule covers are in team "Unassigned".

### Importing and editing the ownership table

Ask the agent ("use the ownership table in ~/Downloads/teams.csv"), or call the tools yourself:

| call | what it does |
|---|---|
| `show_team_ownership()` | the rules by team, where each came from (imported file, set by hand, stand-in), the latest changes, and per log table the entries per team plus the components no rule covers |
| `edit_team_ownership(action="import", csv_path="teams.csv")` | import a CSV. Headers are matched loosely: `dataset`/`log_table`/`table`, `component`/`service`/`pattern`, `team`/`owner`, optional `role` and `area`/`description`; `,` `;` tab or `\|` separated. `log_table="bgl"` names the log table when the file has no such column. |
| `mode="replace"` (default) / `"merge"` / `"replace_all"` | replace the rules of the log tables the file covers (others stay) / add and update only / drop every other rule |
| `edit_team_ownership(action="set", rules=[{"log_table": "bgl", "component": "KERNEL", "team": "Kernel"}])` | add or change single rules |
| `edit_team_ownership(action="remove", team="Kernel")` or `rules=[...]` | remove a team's rules, or single rules |
| `edit_team_ownership(action="export", csv_path="/Users/me/ownership.csv")` | write the rules to a file to edit and import again. Needs a full path (a relative one is refused); says when it replaced a file; with `dry_run=True` it only says what it would write |
| `edit_team_ownership(action="reset")` | back to the stand-in |
| `dry_run=True` | show the change without making it |

Every change reports what was added, changed and removed, then the coverage of the affected log tables, so a
component the file misses shows up at once instead of silently counting as "Unassigned". Changes are logged in
`extractor.ownership_changes`; after the first import or edit the stand-in is never added back on a restart.

## Tools

The agent chooses tools from their descriptions, which all follow one pattern: what the tool does, when to
use it, its inputs and what it returns. The server instructions add a "which tool for which question" guide.
Every result starts with **How this was measured** (exact or estimated, period, filters, sample, index,
time zone). It says when a list is cut ("showing the 25 largest of 31,482 groups"), and it ends with an **evidence
footer** (see below).

| tool | use it for | main inputs | returns |
|---|---|---|---|
| `describe_logs` | orientation: tables, fields, time range, value spellings; **start here** | `log_table`, `find_values={"level": "err"}` | per table: field roles (incl. team), entry count, time range, context scopes, top values (exact when affordable) |
| `count_logs` | **aggregation**: how many, per team / component / level / day, over one or **all** log tables | `group_by` (≤3 of team, component, level, host, service, any column, `time:<n>m\|h\|d`), `filters`, `text`, `start`/`end` | per table the total and each group's count and share; a cut keeps the largest groups; a combined line for shared values; exact unless marked |
| `search_logs` | **full-text search**: the actual entries matching words and/or filters in a time window | `text`, `fuzzy`, `filters`, `start`/`end`, `order`, `limit` | total matches, then up to 50 entries (time, fields, team, message, template tag, occurrence ID); says when cut |
| `get_context` | nearby events before and after one entry | `occurrence` (from search/locate), `scope` (same trace / host / everything), `window_minutes`, `before`/`after` | the entries in time order, the occurrence marked → |
| `survey` | which kinds of messages (templates) occur, with counts | `filters`, `start`/`end`, `exclude`, `limit` | templates ranked by count with share, components, teams and an example; exact or a stated sample; `NEW TO CATALOG` marks a template seen for the first time (not a problem that started now) |
| `locate_occurrences` | exact counts of chosen templates by where and when | `templates` (T-ids), `group_by` (team, host, `time:1h` …) | per template the total and per-group counts with example occurrence IDs |
| `trend` | rising, falling, new or persistent: a period against the one before | `start`, `end`, `templates` (default: the period's own largest, found by a survey and saved to the catalog), `bucket` hour\|day, `exact` (default: every entry counted when that fits the time budget, else a stated sample) | per template the counts per bucket, change, presence, components and teams; refuses to call anything new across gaps |
| `extract_params` | the values inside a template (nodes, status codes, latencies) | `template`, `by` | top values per parameter; min / p50 / p95 / max for numbers |
| `rank_problems` | **what to look at first**: the warning-and-worse problems ranked by a stated, measured score | `start`, `end`, `log_tables`, `min_level` warning\|error\|fatal\|critical, `filters`, `limit` | per problem its score (0-18) and the points behind it: exact entries and levels, change against the preceding period, days (or hours) present, distinct hosts, components and owning team |
| `show_evidence` | the queries and results behind any earlier answer | `ids` (Q-handles) | the tool call, every query with its time and row count, the result |
| `show_team_ownership` | who owns what, and whether the teams are official | `log_table`, `coverage` | rules by team, their source, recent changes, entries per team and components without a team |
| `edit_team_ownership` | import the supplied ownership CSV, fix a team, export the rules | `action` import\|set\|remove\|export\|reset, `csv_path`/`csv_text`, `mode`, `rules`, `team`, `dry_run` | the rules added, changed and removed, then coverage |
| `inspect_source` | look at a new source before setting it up | `source`, `format_hint` | columns, samples, size, proposed roles |
| `setup_log_table` | register a source (Parquet/JSON/CSV that SereneDB can reach is read in place; a file only on this machine is copied; raw text is parsed and copied) | `name`, `source` (several files: `part_{000..009}.parquet`), `roles`, `format_hint`, `timezone` | roles, entries, files, size, setup time (copies too), index estimates |
| `create_index` / `drop_index` | build an index for repeated questions; remove it after the investigation | `log_table`, `kind` filter\|search, `dry_run` | size and build time (estimated with `dry_run`) |
| `rename_parameter` | a clearer name for a template parameter | `template`, `old_name`, `new_name` | the template |
| `run_sql` | last resort: one read-only SQL statement (e.g. latency percentiles) | `sql`, `limit` | rows, cut to 50; cost-checked first |

Shared inputs: `start`/`end` are ISO times (end exclusive) in `timezone` (default: the log table's own zone). A
local time that happens twice (the night clocks go back) is refused with the two UTC offsets to choose from; one
that does not exist (the night clocks go forward) is explained. `filters` is `{"role or column": value or
[values]}`. When a step would read too much, it answers **TOO EXPENSIVE** with the predicted cost and options;
`confirmed_cost` runs it once the user agrees.

Time buckets (`time:1h`, `time:1d`, `time:7d`, trend's `bucket`): an hour is a real hour labelled with its UTC
offset, so the night clocks go back has two 01:00 hours (`01:00-07:00` and `01:00-08:00`); a day is a local calendar
day (23 or 25 hours across a clock change); weeks and other multi-day buckets start on a Monday. When a grouping is
cut, the largest groups are kept and shown in reading order ("showing the 25 largest of 31,482 groups").

Occurrence IDs (from `search_logs` and `locate_occurrences`, for `get_context`):

| source | ID | note |
|---|---|---|
| Parquet / JSON / CSV file read in place | `<file>#<n>`, e.g. `/logs/bgl.parquet#222715` | the bare file name (`bgl.parquet#222715`) also works. `n` is a position SereneDB gives: the row for Parquet, but not a line number for JSON (a byte offset) or CSV |
| copied (raw text, or a file only on this machine) | `e:<n>` | a file's own `entry_id` column is kept as `source_entry_id` |
| database table | `pk:<value>` | when the table has an order column |

## Roles: different questions, evidence and actions

The three prompts (`/engineer`, `/team-lead`, `/manager`, and the MCP prompts of the same names) change what
is gathered and what is recommended, not only how long the answer is:

| | engineer | team lead | manager |
|---|---|---|---|
| asks | what failed, where, what happened just before and after | what recurs, how often, which teams, trend | what deserves attention first |
| evidence | quoted messages, one node's or request's timeline, nearby events (`search_logs`, `get_context`) | exact counts by team and level, trends against the preceding period, spread over hosts (`count_logs`, `survey`, `trend`, `locate_occurrences`, `rank_problems`) | a measured ranking: severity, change, persistence, spread, share (`rank_problems`), plus counts by team (`count_logs`) |
| detail | template IDs and queries on request | template IDs at most | descriptions only |
| recommends | one concrete next diagnostic check and what each outcome means | what to investigate first, assigned to the owning team, plus runners-up | 3-5 ranked risks, each with an owning team and a next action; a closing line on what the logs don't measure |

### How "what first" is decided

`rank_problems` makes the order measured and checkable instead of the agent's judgement. For each log table it
surveys the entries at warning level or above in the period, maps each finding to the broadest template the
catalog already has for it (so its IDs and counts agree with `trend`), and counts every candidate exactly over
the period and the preceding one. Each gets points from fixed thresholds:

| factor | 3 | 2 | 1 | 0 |
|---|---|---|---|---|
| severity (counted twice) | fatal / critical | error / severe / failure | warning | — |
| change against the preceding period | new, or +50% or more | +10% to +50% | within ±10%, or not comparable (the data does not cover both periods, or has a gap) | falling |
| persistence: share of whole days with data that it appears in (hours for a period under two days, or when fewer than 3 whole days have data; not judged, 0 points, when even hours give fewer than 3) | 75% or more | 40% or more | 10% or more | less |
| spread: distinct hosts (else services, else components) | 100 or more | 10 or more | 2 or more | one |
| share of the entries ranked | 10% or more | 1% or more | 0.1% or more | less |

Severity is the level most of a problem's entries have: fatal or critical (also crit, emerg, alert, panic) 3;
error, severe or failure 2; warning 1. `min_level` (warning, error, fatal or critical) chooses which levels are
ranked. A gap in the data is 3 or more hours, or a whole day, with no entries at all; buckets in a gap are left out
of persistence, and nothing is called new across one. Ties go to the problem with more entries.

The result shows each problem's points next to the numbers that earned them. The score orders what to look
at first. It is not a risk, impact or cost figure, and it counts entries, not incidents. A single-node storm
scores low on spread even when it holds most entries, so the manager prompt tells the agent to bring such
items in from the other tools and say why.

All three share the answer rules: plain language; no evidence, no claim (a `[Q]` citation after every statement
about the logs: numbers, times, quoted messages, nodes, teams, trends); measured
facts, hypotheses and unknowns kept apart and labelled; estimates always given with their margin; entries
are not incidents; nothing invented (no impact, downtime or cost unless the logs measure it); and an
**Evidence** section at the end listing every `[Q]` handle cited, with its query.

## Evidence: no evidence, no claim

Every tool result ends with a footer like this:

```text
Evidence [Q46]: the queries that produced this result. Cite [Q46] next to numbers taken from it; show_evidence(['Q46']) gives every query in full and the result again.
  Q46.5 (0.08 s, 16 row(s)): SELECT k0, k1, count(*) AS n FROM (SELECT 1 AS one, coalesce(((CASE WHEN ("component")::varchar ILIKE 'KERNEL' THEN 'Node OS' …
  plus 8 metadata lookups (columns, Parquet statistics) to plan the cost (show_evidence lists them)
```

The server records every query a tool call ran (with its parameters filled in, its time and row count),
together with the call's arguments and result, in `extractor.evidence` under a handle (`Q46`). Answers cite
the handle next to every statement about the logs, not only numbers: a time, a quoted message, a node, a team, a
trend, "new" or "absent" (`it started at 17:17:44 PDT on node R30-M0-N9-C:J16-U01 [Q5]`). A sentence without a
handle must be a labelled hypothesis, a recommendation, or a statement of what the logs do not show. The answer's
**Evidence** section lists every handle it cited with what it measured and its main query, and `show_evidence`
returns the full record for checking. Failed calls keep their
evidence too, so a timeout shows which query ran for how long.

## Large datasets: TextBench (remote Parquet, 1 billion rows per file)

Point setup at the URL; nothing is downloaded:

```text
set up https://public-pme.s3.eu-west-3.amazonaws.com/text_bench/part_000.parquet as a log table called textbench
```

Several files are one log table: `…/text_bench/part_{000..009}.parquet` covers the first five hours (10 files,
10 billion rows). Roles are proposed from the OpenTelemetry column names (`Timestamp`, `Body`,
`SeverityText`, `ServiceName`, `TraceId`), and teams come from `ServiceName` through the ownership table.

How setup stays fast on a remote source:
- it reads only metadata: the Parquet footer (row count, row groups, sizes) and 5 sample entries of the plain
  columns, leaving out the large attribute maps;
- it estimates index sizes from the Parquet column sizes, without the trial index build it uses for local
  sources (a trial would pull a million entries over the network);
- its one-off metadata reads may run up to the maximum query time instead of the 60 s default;
- the result reports how long setup took.

After setup, every tool checks the predicted cost first. A big scope is answered from a **block sample** of
whole row groups (said so, with a margin), or the tool asks before reading more.

## Passwords

Anything passed as `-e …URL=postgresql://user:password@…` ends up in your shell history and in Claude Code's MCP
configuration in plain text. The extractor connects through libpq (via psycopg), so leave the password out of the URL
and use libpq's own mechanisms instead:

- a password file: `~/.pgpass` (or the file named by `PGPASSFILE`), mode `0600`, one line per role:

  ```text
  localhost:7890:logs_extractor:extractor_reader:the-reader-password
  localhost:7890:logs_extractor:extractor_writer:the-writer-password
  ```

- or a connection service file (`~/.pg_service.conf`, or `PGSERVICEFILE`) with a section per role, and URLs like
  `postgresql:///?service=extractor_reader`.


## Running SereneDB in Docker

```sh
docker run -d --name serenedb \
  --platform linux/amd64 \
  -p 127.0.0.1:7890:7890 \
  -v ~/logs:/logs:ro \
  serenedb/serenedb@sha256:6d41ac6577e797289158786a2015ba8fbd6875feadb5c491518e166c011058c9
```

- **Image:** the digest above is the `serenedb/serenedb:latest` of 2026-10-18 that the extractor was built and tested
  against (the same one `scripts/test-db.sh` uses). Newer images may behave differently.

- **Apple Silicon / arm64:** the image has no arm64 build. `--platform linux/amd64` runs it under emulation, which
  works but is noticeably slower (slow start, slower queries). Leave the flag out on an x86-64 host.
- **Bind to localhost** (`-p 127.0.0.1:7890:7890`) unless you have set up passwords and network access on purpose.
  SereneDB speaks the Postgres wire protocol on port 7890.
- **Logs mount:** mount your logs folder **read-only** (`:ro`). Tell the extractor about the mapping with
  `LOGS_HOST_DIR=$HOME/logs` and `LOGS_CONTAINER_DIR=/logs`; you can then refer to files by their path on your
  machine and SereneDB reads them in place through the mount. Structured files outside the mount are streamed in and
  copied; raw text logs are always parsed and copied in (multi-line entries are joined).
- Remote Parquet/JSON/CSV (`https://…`, `s3://…`) is read in place by SereneDB; nothing is downloaded by the extractor.
- CSV: give `format_hint="csv"` when the file name does not end in `.csv` or `.tsv`. A copied CSV's separator is
  detected (`,`, `;`, tab or `|`), standard quoting applies, and every column is kept, a repeated name getting a
  suffix (`level`, `level_1`). A file with its own `filename` or `file_row_number` column cannot be read in place
  (SereneDB adds those columns); it is explained, and a copy works.

For the test suite, `scripts/test-db.sh` starts (or reuses) a pinned test container on `127.0.0.1:17890` and prints
the `SERENEDB_TEST_URL` to use (see [Running the tests](#running-the-tests)).

## Configuration

| variable | meaning | default |
|---|---|---|
| `SERENEDB_READER_URL` | connection URL used for every query; should be a SELECT-only role | **required** |
| `SERENEDB_WRITER_URL` | connection for setup, index builds and catalog writes; a role that owns only the `extractor` schema | the reader URL (single-role mode, with a one-time warning) |
| `LOGS_HOST_DIR` / `LOGS_CONTAINER_DIR` | the mounted logs folder on this machine and where SereneDB sees it (e.g. `~/logs` → `/logs`) | unset; set both or neither |
| `SERENEDB_ALLOW_SQL` | `1` lets `run_sql` work in single-role mode | off |

Built-in limits (not configurable in this prototype):

- Query timeout: 60 s by default, 600 s at most. A query that runs out of time is cancelled in SereneDB and the result
  says what timed out and how to narrow it. A run the user approved at a predicted cost gets a longer timeout, up to
  the maximum; anything predicted to take longer than that is not offered as "run anyway".
- Survey sample: about 100,000 entries after filters.
- Result sizes: survey 30 templates; extract_params 10 values per parameter; get_context 10 entries before and after,
  messages cut at about 500 characters; search_logs and run_sql 50 rows. Each can be raised per call up to 10× (run_sql
  up to 500 rows). Every cut result says so ("showing 30 of 412").

Everything the extractor stores (log table definitions, the template catalog, indexes) lives in the `extractor`
schema. Your own data is never modified.

## Reader and writer roles

Use two roles so that SereneDB itself, not just the extractor, enforces what each connection may do:

- **reader** — every query runs as this role. It is granted only read access to the `extractor` schema and cannot
  write (but see the note on container files below).
- **writer** — setup, index builds and catalog writes run as this role. It owns the `extractor` schema and nothing else.

Give the extractor a **database of its own** (below: `logs_extractor`) rather than `postgres`: the writer needs
`CREATE` on its database, and a dedicated database keeps that privilege away from everything else. Log files are
read through views in that database wherever the files are; only existing SereneDB tables you want to analyze have to
live in the same database.

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

Then connect the server once (any question will do; the first answer may be a permission error naming
`SERENEDB_READER_URL`, because the reader cannot read the tables that were just created) and give the reader
access, as `extractor_writer` or the admin:

```sql
GRANT USAGE ON SCHEMA extractor TO extractor_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA extractor TO extractor_reader;
```

**Re-run the `GRANT SELECT ON ALL TABLES IN SCHEMA` after setting up each new log table.** SereneDB accepts
`ALTER DEFAULT PRIVILEGES` but does not yet apply it to new objects, so a new log table is not readable by the reader
until granted. Until then the answer names the connection that was refused and points back here, e.g.
"SereneDB refused this to the role in SERENEDB_READER_URL: permission denied for view lt_web. Grant it access as in
the README's "Reader and writer roles" section: …". The reader reads log files through the writer's views, so it
needs no access to the files themselves. Do not make either role a superuser.

`CREATE` on the database is needed because the extractor runs `CREATE SCHEMA IF NOT EXISTS extractor` at start-up,
which SereneDB checks against the database even when the schema exists. It also lets the writer create other schemas
in that database (hence the dedicated database); the extractor itself never creates anything outside `extractor`.

This sequence was checked against the pinned SereneDB image used by the tests: setup, survey, index build, text search
and `run_sql` all work with the two roles once the grants are in place.

**Why this matters (the `run_sql` backstop).** `run_sql` lets the assistant run its own SQL. The extractor checks that
SQL before running it (one read-only statement, only `extractor` tables, an allowlist of functions), but the database
role is what really guarantees a query cannot write or read beyond what it was granted. Note one gap the roles do not
close: in the SereneDB version tested, **any role can call file-reading table functions** (`read_text`,
`read_parquet`, …) on paths inside the container, and that cannot be revoked. That is why `run_sql` refuses every
table function and every non-`extractor` relation, and why the logs mount should be read-only and contain only logs.

### Single-role mode

With only `SERENEDB_READER_URL` set, the same connection does everything and SereneDB enforces no limits on it. The
first result of a session says so once. `run_sql` is switched off in this mode unless you set `SERENEDB_ALLOW_SQL=1`.
This is fine for a local container with your own logs; use two roles for anything shared.

## Private S3 / HTTP sources

Credentials are configured **in SereneDB**, never given to the extractor. The extractor never receives, stores or
echoes them; if SereneDB can't read a source, you get a plain-language message.

```sql
CREATE SECRET logs_s3 (
    TYPE s3,
    KEY_ID 'AKIA…',
    SECRET '…',
    REGION 'eu-west-3',
    SCOPE 's3://my-log-bucket'
);
```

`CREATE SECRET` lasts until SereneDB restarts; `CREATE PERSISTENT SECRET` survives restarts but is stored
unencrypted. Other types (`http`, `gcs`, `r2`, `azure`) work the same way; see SereneDB's Secrets Manager docs.

## Indexes

**No index is ever built unless you ask for one.** Big sources show an estimated size and build time (from a trial
build on a sample) before anything is built; you can also ask for just the estimate.

- **Filter index** — the timestamp, level, service, component and trace fields. `describe_logs` then lists each
  field's distinct values (and `find_values` lookups) exactly and instantly from the index. Counts, surveys, trends
  and rankings still read the entries.
- **Search index** — the message text plus the same fields and the host. Serves `search_logs`: makes text search
  fast and enables fuzzy search (finding misspellings). Only the message, the timestamp and the fields a search
  filters on must be in the index, so it also works when some fields are JSON paths. It matches **whole words only**: a fragment like `disk` inside `diskfull` is not found.
  When a plain scan is affordable, the scan is used instead (exact substring matching); every answer that came from the
  index says "whole words only".

Indexes live in the `extractor` schema next to their log table.

## Time zones

Every log table has its own time zone: the zone its timestamps without one were written in. Setup reads them in
the zone you give (`timezone`), else in the line format's own zone where it has one, else in UTC. The `bgl` line
format's zone is `America/Los_Angeles`: Blue Gene/L logs record US Pacific local time. Timestamps are stored as
real instants; the loader's `bgl` takes them from BGL's epoch column. When a source's timestamps already are real
instants (a type with a time zone), the zone only sets how times are shown; setup and `describe_logs` say so.

Setup checks the timestamp role: a column that mostly holds no times is refused. Text times, time types and Unix
epoch numbers (seconds, or milliseconds when that large) are times. Timestamps are read leniently: a value that is
not a time makes an entry without a time, not a failed query.

Results show times in the log table's own zone unless a tool is given `timezone`, and times you pass without a zone
are read in that zone too, so dates mean the same as in the log itself. Outside UTC, every result says so and the
times of entries and periods carry their UTC offset (`2005-06-03 16:17:40-07:00`). `run_sql` runs in the zone of the
log tables it reads (UTC when they differ), so timestamps print with their offset and `date_trunc`, `::date` and time
literals follow the log's clock; `ts AT TIME ZONE 'UTC'` gives UTC. A copied log table keeps the zone it was read in;
set it up again under another name to change it.

## Running the tests

```sh
bash scripts/test-db.sh            # starts/reuses the sdb-test container and prints SERENEDB_TEST_URL
export SERENEDB_TEST_URL=postgresql://postgres@localhost:17890/postgres
uv run pytest
```

Tests that need the database are marked `db` and are skipped when `SERENEDB_TEST_URL` is not set. They use a dedicated
database, `SERENEDB_TEST_DB` (default `extractor_test`, created if missing), and drop and recreate the `extractor`
schema there; they refuse to reset a database whose name does not start with `extractor_test`. The test container runs
without passwords, which is why `scripts/test-db.sh` binds it to `127.0.0.1` only.

## Known limits

This is a prototype:

- **Sources are static snapshots.** Log tables are not refreshed or appended to; files read in place are assumed not to
  change after setup.
- **Remote raw text is not supported.** Remote sources must be Parquet, JSON or CSV; raw text logs must be local files.
- **One log table holds one application's logs**; template catalogs are not shared between log tables.
- **`run_sql` is restricted:** one read-only statement (SELECT, WITH, set operations or EXPLAIN); only tables and views
  in the `extractor` schema, always schema-qualified (`extractor.lt_<name>`); only allowlisted functions (string, regex,
  date/time, math, aggregates, window functions, casts, JSON); no table functions; no column lists on CTEs or aliases
  (`WITH r(n) AS …` is refused; write `SELECT 1 AS n` inside instead); results cut at 50 rows by default.
- **Sampling only for a single Parquet file.** Estimates from a block sample need one in-place Parquet file; for
  globs of several files, JSON, CSV and copied tables every entry in scope is read and counted exactly, or, when that is
  over the time budget, the tool asks before running it.
- **Index builds are capped at the server's maximum query time** (600 s by default): a build that runs longer is
  cancelled and no index is created; `create_index` with `dry_run` warns beforehand when its estimate is longer.
- **Catalog writes are single-process.** Survey results, merges and renames are serialized within one server
  process; several server processes writing the same catalog at the same time are not supported.
- **Timings under emulation are not representative.** Size and time estimates and test timings measured with the
  amd64 image on an arm64 machine are slower than on native hardware.
- **The shipped ownership table is a fictional stand-in** until the supplied one is imported with `edit_team_ownership`.
  Its rules are keyed by log table name patterns (`bgl%`, `openstack%`, `textbench%`); a log table with another
  name has no team until rules cover it.
- **Evidence records grow without limit** in `extractor.evidence` (one row per tool call); clear the table when it
  gets large.
- **Gap detection needs an affordable scan of the timestamp column.** When even that is too expensive (a huge
  remote source over a long period), `trend` says gaps were not checked.
- **The remote TextBench path was exercised over HTTP from a local server** (one file and a two-file
  `part_{000..001}` source); its timings against the real S3 bucket were not measured in this version.
