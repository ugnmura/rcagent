# SereneDB Extractor — Design

*Status: approved through a design session on 2026-10-17. Glossary: [`CONTEXT.md`](../../../CONTEXT.md). Decisions: [`docs/adr/`](../../adr/). Items marked **(builder's call)** or **(Claude's call)** were not decided by the owner and may be revisited.*

## 1. Intent

People need answers from large volumes of logs: "what failed and why", "what keeps going wrong", "what should we worry about". Plain `GROUP BY message` fails because the same error is logged with different parameters (`timeout after 3021ms` vs `timeout after 45ms`), so every occurrence becomes its own group.

The SereneDB Extractor is an **MCP server** that lets an agent point SereneDB at logs (local or remote, up to tens of billions of entries), group entries into **templates**, pull out their **parameters**, follow them over time, and look at the entries around specific **occurrences** — and then explain the findings to people **in plain language**.

It is a **prototype**.

### Who it serves

Three audiences ask about the same logs and need different evidence:

- **Engineer** — what failed, in which component, what happened just before and after; a possible cause and the next check.
- **Team lead** — which problems recur, how often, which components are involved, over a stated period; what to investigate first.
- **Manager** — which observed problems deserve attention first and what should happen next; short, prioritized, built only on measured frequency and affected components.

### Core principles

1. **Natural language is the whole point.** End users never need to know tools, SQL, regexes or parameter syntax. Answers lead with descriptions ("the *timeout calling payments* error"). Template IDs may appear in brackets as handles — engineers get IDs and the exact query on request, team leads IDs at most, managers none. Estimates, assumptions and refusals are always in plain words.
2. **Never present an estimate as a measurement.** Every sampled number carries its method and margin all the way to the user.
3. **Never invent.** No financial loss, downtime or customer impact unless the logs measure it; no "new" or "+∞%" from missing data.
4. **Be careful with cost.** Nothing expensive runs without a prediction; nothing big gets built or copied without approval; remote data is never downloaded.

## 2. Goals, non-goals, anti-goals

**Goals**
- Point at a log source (local file/files, HTTP/S3 URL, or existing table) and analyze it with no ETL for structured data.
- Group entries into templates robustly, including word-valued parameters.
- Cheap first look (survey) on any size of data; exact, targeted follow-ups (investigation) where affordable.
- Answer the three audience scenarios end to end.

**Non-goals (prototype)**
- Merging or sharing catalogs across log tables; one log table holds one application's logs.
- Ownership / reference tables (who owns a service is the reader's job).
- Labels, notes or "noise" flags on templates.
- Catalog cleanup command.
- Count caching (see watch list).
- Installing or running SereneDB.
- Remote raw-text sources (remote sources must be structured).
- Refreshing or appending to log tables (sources are static snapshots).

**Anti-goals** — it fails even if it technically works when:
- it downloads or copies a huge remote dataset to answer one question;
- it builds a multi-GB index without asking;
- it reports "no errors" when a filter value simply didn't exist;
- a sampled estimate reaches a user as if it were an exact count;
- a manager summary contains impact the logs don't show;
- an end user has to speak in IDs and parameters to get an answer.

## 3. Constraints

- **Written in Python** (3.12+); ordinary dependencies, including compiled wheels, are fine. Driver: `psycopg[binary]` 3 (server-side cancel via `cancel_safe()`). Drain: `drain3`. SQL parsing: `sqlglot` (pure-Python tokenizer). MCP: official Python SDK (FastMCP). Packaged with `uv`, run as `uvx serenedb-extractor`.
- **MCP over stdio**, started by the client (`claude mcp add serenedb-extractor -- uvx serenedb-extractor`).
- **SereneDB runs in Docker** (`serenedb/serenedb`, Postgres wire protocol on 7890), operated by the user. The README documents the `docker run`, including the logs mount.
- SereneDB facts this design relies on (from its docs): PostgreSQL dialect; `read_parquet`/`read_csv`/`read_json` over local paths and `https://`/`s3://`; `parquet_file_metadata`/`parquet_metadata` (row counts, per-column compressed sizes, row-group stats); RE2 regex functions incl. `regexp_extract` with named groups; `USING SAMPLE` / `TABLESAMPLE` (reservoir, bernoulli, system); inverted indexes over tables **and over views on external files** (only postings stored); term dictionary (`ts_dict_*`) serving distinct values and facets of indexed keyword columns; roles and `GRANT`; `PRIMARY KEY`, `JSON`, `UPDATE`/`DELETE` on ordinary tables.

**Assumptions (Claude's calls)**
- **Log sources are static snapshots.** No refresh or append for copied tables; in-place globs are assumed not to change after setup. Row counts are read fresh from file metadata when cheap rather than trusted from `log_tables.row_count`.
- **Credentials for private S3/HTTP are configured in SereneDB by the user** (e.g. `CREATE SECRET`), documented in the README. The MCP never receives, stores or echoes credentials; access errors from `inspect_source` are turned into plain-language messages.
- **Time zone:** periods and buckets are computed in **UTC by default**; tools accept an optional time zone, and the model states which one it used. Zoneless raw-text timestamps are treated as UTC unless the user says otherwise at setup (the setup summary states the assumption).

## 4. Configuration

| setting | meaning | default |
|---|---|---|
| `SERENEDB_READER_URL` | connection for all queries; role with `SELECT` only | required |
| `SERENEDB_WRITER_URL` | connection for setup, indexes, catalog writes; role owning only `extractor` | = reader URL, with a one-time warning that the database is not enforcing limits |
| `LOGS_HOST_DIR` / `LOGS_CONTAINER_DIR` | mounted logs folder mapping (e.g. `~/logs` → `/logs`, mounted read-only) | unset (everything local is streamed) |
| query timeout | default / maximum per query | 60 s / server max **(Claude's call: 600 s)** |
| survey sample size | target sampled entries after filters | 100k |
| result limits | defaults, raisable per call up to a cap | see §8 |

## 5. Data model

All MCP state lives in the `extractor` schema; user data is never modified.

```sql
CREATE SCHEMA extractor;

CREATE TABLE extractor.log_tables (
    name               VARCHAR PRIMARY KEY,
    source             VARCHAR NOT NULL,      -- path, glob, URL or table name as given
    source_format      VARCHAR NOT NULL,      -- 'parquet' | 'json' | 'csv' | 'raw_text' | 'table'
    mode               VARCHAR NOT NULL,      -- 'in_place' | 'copied'
    relation           VARCHAR NOT NULL,      -- what tools query, e.g. 'extractor.lt_textbench'
    -- field roles: SQL expressions over the relation; NULL = role absent
    role_timestamp     VARCHAR,
    role_message       VARCHAR NOT NULL,
    role_level         VARCHAR,
    role_service       VARCHAR,
    role_host          VARCHAR,
    role_component     VARCHAR,
    role_trace         VARCHAR,
    role_order         VARCHAR,               -- tie-breaker / occurrence position, e.g. 'file_row_number'
    filter_index_name  VARCHAR,               -- NULL if none
    search_index_name  VARCHAR,               -- NULL if none
    row_count          BIGINT,
    next_template_no   INTEGER NOT NULL DEFAULT 1,
    created_at         TIMESTAMP NOT NULL,
    roles_updated_at   TIMESTAMP NOT NULL
);

CREATE TABLE extractor.templates (
    log_table          VARCHAR NOT NULL,
    template_id        VARCHAR NOT NULL,      -- 'T17'; assigned from next_template_no, never reused
    template           VARCHAR NOT NULL,      -- 'login failed for user <*> from <IP>'
    regex              VARCHAR NOT NULL,      -- anchored, one capture group per parameter
    params             JSON NOT NULL,         -- [{"pos":1,"name":"user","kind":"word"}, ...]
    example            VARCHAR NOT NULL,      -- one real entry; used for generalization checks
    first_seen         TIMESTAMP,
    last_seen          TIMESTAMP,
    last_estimate      BIGINT,
    last_estimate_at   TIMESTAMP,
    updated_at         TIMESTAMP NOT NULL,
    PRIMARY KEY (log_table, template_id)
);

CREATE TABLE extractor.template_redirects (
    log_table          VARCHAR NOT NULL,
    old_id             VARCHAR NOT NULL,
    new_id             VARCHAR NOT NULL,      -- always one hop; chains are rewritten
    merged_at          TIMESTAMP NOT NULL,
    PRIMARY KEY (log_table, old_id)
);
```

**Log table relations**

- *In place* (structured): `CREATE VIEW extractor.lt_<name> AS SELECT * FROM read_parquet('<source>')` (or `read_json`/`read_csv`). Kept as a plain `SELECT * FROM reader(literal)` so SereneDB treats it as a fast-path source (indexable, materializable).
- *Copied* (raw text, or structured files outside the mount):
  ```sql
  CREATE TABLE extractor.lt_<name> (
      entry_id    BIGINT PRIMARY KEY,
      source_file VARCHAR NOT NULL,
      line_start  INTEGER NOT NULL,
      line_end    INTEGER NOT NULL,
      ts          TIMESTAMP,
      level       VARCHAR,
      component   VARCHAR,
      message     VARCHAR NOT NULL       -- full entry incl. continuation lines
  );
  ```
  Inserted **sorted by timestamp**.

**Occurrence ID** — an opaque string the model passes between tools: `filename#file_row_number` for in-place sources, `e:<entry_id>` for copied tables, the primary key for existing tables. In-place IDs assume files are not replaced (acceptable for the prototype).

## 6. Flows

### 6.1 Setup

1. `inspect_source` reads only metadata and a small sample: format, files, row count and size (Parquet footers), per-column compressed sizes, columns/types, sample entries, **proposed field roles** (column names, types, sample values; SereneDB's OpenTelemetry names checked first), in-place vs copied and why, filter-index and search-index estimates.
2. The model presents this in plain language and asks the user to confirm or correct roles.
3. `setup_log_table` (approval) creates the relation, records roles, creates an empty catalog, and offers both indexes with their estimates — the **filter index** and the **search index** — each **default no**. No index is ever built without the user explicitly choosing it.
4. Re-running `setup_log_table` on an existing name updates field roles only.

Local paths: under the mount → translated and read by SereneDB; otherwise streamed in by the MCP (`COPY FROM STDIN` or batched inserts), which copies even structured files — setup says so, and above 1 GB says plainly that this is a full copy the mount would avoid. No hard size limit.

**Remote raw text is out of scope for the prototype**: remote sources must be structured (Parquet/JSON); raw text must be local, and is parsed in Python.

Raw text parsing **(builder's call on the parser)**: recognize common prefixes (ISO/syslog timestamps, level tokens, `[component]`); a line not starting with a recognized timestamp is a continuation of the previous entry.

Index estimates come from building a **trial index on a sample** (~1M entries), measuring it and scaling, then dropping it.

### 6.2 Survey

Inputs: log table, time range, filters, `exclude` (template IDs), sample size, limit.

1. **Scope and cost.** Resolve filters to field roles. Predict cost from row counts, row-group statistics (can the time range skip?), per-column compressed sizes (how many bytes does each filter read?), index presence, and sampling method. Refuse with reason + fix if too expensive.
2. **Filter, then sample** by default — small columns like level/service are cheap to scan even unsorted. Sample first (block sampling sized from the filter's estimated hit rate) only when the filter column itself is large, or if SereneDB turns out to read the message for every filtered row (see verify list). Reservoir for small scopes, block (`system`) sampling for huge ones.
3. **Mask in SQL**: a `regexp_replace` chain for generic value kinds (UUID, IP, hex, numbers, quoted strings, paths, URLs, emails — order matters, most specific first), then `GROUP BY masked` returning distinct masked strings with counts and an example, plus per-group service/component counts.
4. **Drain in the MCP** over the grouped masked strings (weighted by count) to merge word-level variation.
5. **Compile** each template to an anchored regex with one capture group per placeholder; name parameters heuristically (preceding label word: `user <*>` → `user`, `status=<*>` → `status`; else `<kind>_<n>`).
6. **Catalog write** (automatic): match against the catalog; a new template whose regex matches an existing template's example **generalizes it in place** (keeps the older ID and earliest first_seen); if it absorbs several, the oldest ID survives and the others get redirects. Update last_seen / last_estimate.
7. **Return** top templates: estimated count and share, estimated breakdown by service/component, one example, "new" flag (not previously in catalog), coverage line ("these 30 cover 96% of the sample").

`exclude` removes the listed templates' entries before sampling, surfacing rare templates hidden under noisy ones.

### 6.3 Investigation

- **`locate_occurrences`** — exact counts for one or more templates (required), optional `group_by` (any role or column, incl. time buckets), a few example occurrence IDs per group. One scan using `count(*) FILTER (WHERE regexp_full_match(...))` per template; prefilter on each template's fixed words (substring or search-index lookup) before the regex.
- **`extract_params`** — for one template: per parameter, top values with counts; min/p50/p95/max if numeric; optional breakdown by another parameter or column. Uses `regexp_extract(msg, regex, [names])`.
- **`trend`** — for several templates: counts per bucket over a period vs the preceding period of equal length; change %, **buckets present** ("13 of 14 days"), components affected. **Estimated by default** (sample per bucket); exact on request when the cost check allows. Checks the data's time range covers both periods; partial coverage is reported, and "new" is claimed only when the earlier period is fully covered.
- **`get_context`** — for one occurrence: entries within a **time window** (default ±5 min, widened on request) around it, filtered to a context scope (same values on chosen columns, e.g. trace, or service+host; or everything), ordered by timestamp then `role_order`; default N before/after = 10; optional extra filters (e.g. WARN+). Each entry tagged with its template. Available scopes are those whose columns exist.

### 6.4 General lookup

- **`search_logs`** — structured filters + text (search index if present, else scan via cost check); fuzzy only with a search index; results tagged with templates.
- **`run_sql`** — read-only escape hatch for questions other tools can't express (aggregating by arbitrary columns or JSON attributes). Reader role; `sqlglot` allows only SELECT/EXPLAIN; cost-checked via `EXPLAIN`; limits and timeout apply.

### 6.5 Value discovery (`describe_logs`)

Lists log tables with source, mode, roles, size, time range, indexes, available context scopes, catalog size, and **top values** of level/service/component:
- with a filter index: exact from the term dictionary;
- otherwise: from a small block sample, labelled as possibly incomplete.

Also supports a targeted lookup: values in one column like a given word (`SELECT DISTINCT col WHERE col ILIKE '%word%'` within the time range — reads that column only; cost-checked). Any tool whose filters match zero entries says which filter matched nothing, never "no errors".

## 7. Tools

Permissions: **read** runs freely; **auto-write** writes only to the catalog without asking; **approval** asks the user (MCP `destructiveHint`, read tools carry `readOnlyHint`).

| # | tool | permission | purpose |
|---|---|---|---|
| 1 | `inspect_source` | read | Look at a source; propose roles; estimates. |
| 2 | `setup_log_table` | **approval** | Create/update a log table; filter and search indexes offered (default no, explicit choice only). |
| 3 | `create_index` | **approval** | Build filter or search index; `dry_run` returns the estimate only. |
| 4 | `describe_logs` | read | Log tables, roles, time range, indexes, scopes, top values, value lookup. |
| 5 | `survey` | read + auto-write | Sampled templates with estimates and breakdown; catalog update; `exclude`. |
| 6 | `locate_occurrences` | read | Exact counts, `group_by`, example occurrences. |
| 7 | `extract_params` | read | Parameter values and stats for one template. |
| 8 | `trend` | read | Period comparison, presence, components; estimated by default. |
| 9 | `get_context` | read | Time-windowed, scoped neighbours of one occurrence. |
| 10 | `search_logs` | read | Filtered / text search for ad-hoc lookups. |
| 11 | `run_sql` | read | Read-only SQL escape hatch. |
| 12 | `rename_parameter` | auto-write | Rename a template parameter in the catalog. |

Tools that take template IDs resolve them through the catalog, follow redirects automatically and say so ("T18 was merged into T17"); unknown IDs get a helpful error naming the closest current template.

## 8. Results

- **Default limits** (raisable per call up to a cap **(Claude's call: 10×)**): survey 30 templates; extract_params top 10 values per parameter; get_context 10 before / 10 after, messages cut at ~500 chars; search_logs / run_sql 50 rows. Every result says when it was cut ("showing 30 of 412").
- **Every result opens with "How this was measured"**: exact or sampled, sample size and method, period, filters, index used.
- **Estimates are never bare numbers**: always `≈48,000 (estimated from a 100k sample, ±2%)`. Templates too rare to estimate reliably are marked so.
- **Cheaper first, then ask.** When the cost check predicts a query is too expensive, the tool walks a ladder of cheaper strategies before giving up: (1) use a filter/search index if present; (2) prefilter on each template's fixed words; (3) switch exact → estimated (labelled); (4) cheaper sampling with a wider, stated margin. If a rung fits, it runs and says what it did ("an exact count would read ~2 TB, so this is estimated from a sample, ±3%"). It **never silently narrows the user's scope** (period, services) — that changes the question and is always asked. If no rung fits, it asks with the estimate: `TOO EXPENSIVE: needs ~2 TB read, ~20 min. Run it, narrow it, or build a search index (≈X GB)?` Running anyway is an approval path: query tools accept a `confirmed_cost` argument carrying the approved estimate **(Claude's call on the mechanism)**, and the timeout for a confirmed run is raised to cover the estimate.
- **Clear timeouts**: the query is cancelled in SereneDB (Postgres cancel request) and the tool returns `TIMEOUT after 60s: <what> — <how to narrow>`.

## 9. Server instructions and prompts

**Server instructions** (sent on connect) encode the principles: start with `describe_logs`; survey before investigating; infer scope from the user's words, ask in plain language only for what can't be inferred, state assumptions; never present an estimate as exact; never invent impact; check value spellings via `describe_logs`; IDs only as bracketed handles scaled to audience.

**MCP prompts** — `engineer`, `team-lead`, `manager`. They take **no parameters**; the model infers log table, period and focus from the conversation and asks for anything missing.

- **engineer**: survey ERRORs (and WARNs if few) → choose relevant templates → `locate_occurrences` by component/time → `get_context` on 2–3 occurrences at the narrowest scope → `extract_params` where it helps. Answer: actual error messages, events before/after, a possible cause **marked as a hypothesis**, the next check.
- **team-lead**: survey over the period → `trend` for top templates vs preceding period → components from the survey breakdown (exact via `locate_occurrences` if affordable). Answer: recurring problems ranked by presence, frequency and change; components involved; what to investigate first and why. Ownership is left to the reader.
- **manager**: same evidence, condensed. Rank by, in order: **severity** (FATAL > ERROR > WARN), **trend** (rising/new > stable), **persistence** (buckets present), **spread** (components affected), **volume** (share). No numeric risk score. Each item states which criteria placed it. When estimates' margins overlap and decide the order, say "roughly equal" or resolve with exact counts. Answer: 3–5 items with measured frequency, trend, components and a next action; an explicit line on what the logs do not measure. Impact follow-ups are answered only with measured counts plus "not in the data".

## 10. Internal components (not tools)

Cost estimator · timeout & cancel · SQL guard · masker · Drain merger · regex compiler · parameter namer · sampler · catalog writer · ID resolver · source sniffer · role detector · raw log parser · path mapper · index estimator · result formatter. (Responsibilities as described in §6–8.)

## 11. Safety

- Two database roles: **reader** (`SELECT` on log relations and `extractor`) for every query; **writer** (owns only `extractor`) for setup, indexes and catalog writes.
- `sqlglot` guard on `run_sql` as a second layer.
- MCP tool annotations decide what needs user approval.

## 12. Verify during build

These were not verifiable from docs and change the implementation if false:

1. `USING SAMPLE`/`TABLESAMPLE` over a view on remote Parquet still benefits from row-group skipping and doesn't read everything to sample.
2. After a filter, SereneDB reads the message column only for sampled rows (late materialization) — decides filter-first vs sample-first (§6.2).
3. SereneDB honours the Postgres wire-protocol cancel request (no documented `statement_timeout`).
4. `filename` + `file_row_number` are available and stable through the view for occurrence IDs and context lookups.
5. Index behaviour on copied raw-log tables, and filter-index size/build time at scale.
6. `PRIMARY KEY`, `JSON`, `UPDATE`/`DELETE` on ordinary `extractor` tables (documented; confirm in Docker image).

## 13. Watch list

- **Exact trends too slow, and do filter combinations repeat?** If both, add a count cache (an hourly granularity was considered; minute-level would be computed live; half-hour time zones can't be rolled up from hours).
- **Filters on copied tables slow?** Consider ENUM types for few-valued columns (judged unnecessary given SereneDB's string compression).
- **Survey quality on block samples** (clustered by time/service).

## 14. Benchmark — definition of done

The prototype is done when it performs well on a reproducible benchmark over **Loghub-2.0 BGL and OpenStack** (raw text, copied path; annotated with ground-truth templates — BGL 320 templates / 4.6M lines, OpenStack 48 / 208k) and a **scale suite on TextBench `part_000.parquet`** (`https://public-pme.s3.eu-west-3.amazonaws.com/text_bench/part_000.parquet`, in place). Datasets are fetched by scripts, not committed.

| layer | checks | ground truth | scoring |
|---|---|---|---|
| A. Templating | our templates vs true templates | Loghub-2.0 labels | grouping accuracy, parsing accuracy, template F1 |
| B. Facts | `locate_occurrences`, `trend`, `extract_params`, `get_context` return correct numbers/entries | derived by scripts from labelled data | exact match for exact counts; within stated margin for estimates |
| C. Scenarios | Claude + MCP answers engineer / team-lead / manager questions correctly and by the rules | Q&A per persona per dataset, derived by scripts from labels (plus BGL alert labels for "what failed"); hand-written only where labels can't answer; owner reviews a sample | automatic fact checks + LLM-judge rubric (estimates labelled, nothing invented, cause marked as hypothesis, plain language, IDs scaled to audience) |
| D. Scale | TextBench in place | — | per-tool timing, **predicted vs actual cost**, sampling behaviour, index estimate vs actual, answers to §12 |

Scenario runs use Claude headless (`claude -p` with the MCP configured), recording answers and tool calls, so the benchmark also reports tool usage and refusal rates.

**Edge cases** (starting list): misspelled / rare service and level values; filter matching nothing; period partly or wholly outside the data; multi-line entries; generalization and merges across repeated surveys; refusal, cheaper-ladder and approval paths; ranking ties within margin; timeouts; vague questions needing inference vs a follow-up question.

## 15. Left to the builder

Project layout, module boundaries, test strategy, the raw-text prefix grammar, masking regex specifics and ordering, Drain parameters (similarity threshold, depth), cost thresholds' exact numbers, the text of server instructions and prompts (within §9), output formatting details (within §8), and benchmark sizing (number of questions per persona, judge model and rubric wording, within §14).
