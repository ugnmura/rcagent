# serenedb-extractor

An MCP server that lets an AI assistant (Claude Code, or any MCP client) answer questions about large
logs in plain language: "what failed and why", "what keeps going wrong", "what should we worry about".

It points [SereneDB](https://serenedb.com) at your logs (local files, HTTP/S3 Parquet or JSON, or an
existing table), groups entries that are the same message with different values into **templates**
(`timeout after 3021ms` and `timeout after 45ms` are one problem), pulls out their **parameters**,
follows them over time and shows what happened around individual **occurrences**. Cheap sampled
estimates come first; exact counts follow where they are affordable, and anything expensive is
predicted and asked about before it runs. Estimates are always labelled as estimates.

It is a **prototype**. SereneDB itself is not installed or run by this package: you run it in Docker.

## Quick start

1. Run SereneDB (see [Running SereneDB in Docker](#running-serenedb-in-docker)).
2. Create the reader and writer roles and a dedicated database for the extractor, as in
   [Reader and writer roles](#reader-and-writer-roles). Note that the reader's grant has to be **re-run after each new
   log table**. (For a quick local try with your own logs, you can skip this and use one URL; see
   [single-role mode](#single-role-mode).)
3. Put the passwords in a password file rather than in the URLs (see [Passwords](#passwords)), then add the server to
   Claude Code. **The package is not published yet**, so run it from a checkout of this repository:

   ```sh
   claude mcp add serenedb-extractor \
     -e SERENEDB_READER_URL=postgresql://extractor_reader@localhost:7890/logs_extractor \
     -e SERENEDB_WRITER_URL=postgresql://extractor_writer@localhost:7890/logs_extractor \
     -e LOGS_HOST_DIR=$HOME/logs -e LOGS_CONTAINER_DIR=/logs \
     -- uv run --directory /path/to/serenedb-extractor serenedb-extractor
   ```

   Once the package is published, the last line becomes `-- uvx serenedb-extractor`. The minimum is one URL:
   `claude mcp add serenedb-extractor -e SERENEDB_READER_URL=… -- uv run --directory /path/to/serenedb-extractor serenedb-extractor`.
4. In Claude Code, `/mcp` should list `serenedb-extractor` with its tools and the three prompts. Ask something like
   "set up the logs in ~/logs/app/*.parquet and tell me what's failing", or start from a prompt:
   `/mcp__serenedb-extractor__engineer`, `/mcp__serenedb-extractor__team-lead` or `/mcp__serenedb-extractor__manager`.

The server speaks MCP over stdio and is started by the client; there is nothing to keep running besides SereneDB.

### Passwords

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

## What you get

**Tools** (the assistant uses these; you never need to name them):

| tool | what it does |
|---|---|
| `inspect_source` | look at a file, URL or table without changing anything: columns, samples, proposed field roles |
| `setup_log_table` | set up a log table over a source with confirmed field roles (timestamp, message, level, service, …) |
| `create_index` | build a filter or search index, or estimate its size and build time (`dry_run`) |
| `describe_logs` | the log tables, their roles, time range and top values; look up how a value is spelled |
| `survey` | first look: the most common templates with estimated counts, shares, top services and an example each |
| `locate_occurrences` | exact counts of chosen templates, grouped by any field or time bucket, with example occurrences |
| `extract_params` | one template's parameter values: top values, and min/p50/p95/max for numbers |
| `trend` | templates over a period compared with the preceding period: per hour/day, change, presence, components |
| `get_context` | the entries just before and after one occurrence (same trace, else same service and host) |
| `search_logs` | find entries by fields and/or message text |
| `run_sql` | read-only SQL escape hatch over the extractor's tables (restricted; see [Known limits](#known-limits)) |
| `rename_parameter` | give a template parameter a better name, permanently |

**Prompts** (no arguments; the assistant infers the log table, period and focus from the conversation and asks
for what's missing):

- `engineer` — what failed, where, what happened just before and after, a possible cause (marked as a hypothesis) and the next check.
- `team-lead` — which problems recur over a period, how often, how that changed, which components, what to investigate first.
- `manager` — 3–5 prioritized items (severity, then trend, persistence, spread, volume), each with a next action, and
  a closing line on what the logs do not measure (customer impact, downtime, cost).

The server also sends instructions on connect: start by describing the logs, check value spellings, survey before
investigating, never present an estimate as exact, never invent impact, respect cost questions.

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
- Remote Parquet/JSON (`https://…`, `s3://…`) is read in place by SereneDB; nothing is downloaded by the extractor.

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

- **Filter index** — the timestamp, level, service, component and trace fields. Lists each field's distinct values
  exactly and answers filters (level = ERROR, service = payments) almost for free.
- **Search index** — the message text plus the same fields and the host. Makes text search fast and enables fuzzy
  search (finding misspellings). It matches **whole words only**: a fragment like `disk` inside `diskfull` is not found.
  When a plain scan is affordable, the scan is used instead (exact substring matching); every answer that came from the
  index says "whole words only".

Indexes live in the `extractor` schema next to their log table.

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
- **Remote raw text is not supported.** Remote sources must be Parquet or JSON; raw text logs must be local files.
- **One log table holds one application's logs**; template catalogs are not shared between log tables.
- **`run_sql` is restricted:** one read-only statement (SELECT, WITH, set operations or EXPLAIN); only tables and views
  in the `extractor` schema, always schema-qualified (`extractor.lt_<name>`); only allowlisted functions (string, regex,
  date/time, math, aggregates, window functions, casts, JSON); no table functions; no column lists on CTEs or aliases
  (`WITH r(n) AS …` is refused; write `SELECT 1 AS n` inside instead); results cut at 50 rows by default.
- **Timings under emulation are not representative.** Size and time estimates and test timings measured with the
  amd64 image on an arm64 machine are slower than on native hardware.
- Ownership of services or components is not tracked; who owns what is left to the reader.
