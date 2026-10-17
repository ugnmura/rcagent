# SereneDB Extractor MCP Server — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the 12-tool MCP server (plus 3 prompts) that lets an agent set up log tables in SereneDB, survey them into templates, investigate templates exactly or by estimate, and explain results in plain language.

**Architecture:** A FastMCP stdio server over a thin `Database` layer (psycopg, reader + writer connections, timeout → server-side cancel). Internal modules (catalog, templating, query, setup, formatting) sit behind the tools. Tests use two seams only: **the MCP tool boundary** (an in-memory MCP client calls tools against a real SereneDB in Docker) and **pure templating functions** (masking, regex compiling, Drain merge).

**Tech Stack:** Python 3.12+, `uv`, `mcp` (FastMCP), `psycopg[binary]` 3, `drain3`, `sqlglot`, `pytest`, `pytest-asyncio`.

**Spec:** `docs/superpowers/specs/2026-10-17-serenedb-extractor-design.md` (glossary `CONTEXT.md`, ADRs `docs/adr/`). Tracker: spec issue #1; each task below is one ticket (#2–#19) with the same blockers. The benchmark (spec §14) is a separate, later plan.

## Global Constraints

- Python ≥ 3.12; package `serenedb-extractor`, import package `serenedb_extractor`, console script `serenedb-extractor`; runnable as `uvx serenedb-extractor`. MCP over stdio only.
- Env: `SERENEDB_READER_URL` (required), `SERENEDB_WRITER_URL` (defaults to reader + one-time warning), `LOGS_HOST_DIR` / `LOGS_CONTAINER_DIR` (optional mount mapping; both or neither).
- Query timeout default 60 s, max 600 s. Survey sample size default 100,000. Result limits raisable per call up to 10× the default.
- Default result limits: survey 30 templates; extract_params 10 values per parameter; get_context 10 before / 10 after, messages cut at 500 chars; search_logs / run_sql 50 rows. Every cut result says `showing X of Y <noun>`.
- Every tool result begins with `How this was measured: `.
- Estimates always render as `≈48,000 (estimated from a 100k sample, ±2%)`; never bare numbers. Fewer than 10 sampled hits → `too rare to estimate reliably: N sampled hits`.
- No index is ever built unless the call explicitly requests it.
- Never download remote data in Python; remote raw text is rejected; remote sources must be Parquet/JSON.
- All MCP state in schema `extractor`; user data never modified.
- Tool annotations: read tools `readOnlyHint=True`; `setup_log_table`, `create_index` `destructiveHint=True`; `survey`, `rename_parameter` `readOnlyHint=False, destructiveHint=False`.
- UTC by default; time-taking tools accept `timezone` (IANA); results state the zone used.
- Template IDs `T<n>` from `log_tables.next_template_no`, never reused.
- Every failure reaches the model as one plain-language line, never a traceback.

## Review Focus

1. **A filter value spelled differently from the data** (`error` vs `ERROR`) → "level='error' matched nothing (seen: ERROR, WARN, …)", never an empty "no errors". → Task 9 (#9).
2. **Literal regex metacharacters in log text** (`GET /api/v1/items?id=<NUM> (retry) [x]$`) compile to a regex that full-matches its own example. → Task 5 (#5).
3. **Raw entries with no timestamp** are kept and reported, never silently dropped from time-ranged answers. → Task 8 (#8) and Task 18 (#18).
4. **Very long entries** (10k-char stack traces) are matched in full but displayed cut at 500 chars with `…(cut)`. → Task 14 (#14).
5. **The same template found by two surveys** stays one catalog row with one ID. → Task 9 (#9).

## Test harness (shared; created in Task 3, extended where noted)

- `tests/conftest.py`
  - marker `db`; fixture `db_url` skips unless `SERENEDB_TEST_URL` is set.
  - fixture `mcp` (async): drops and recreates schema `extractor`, builds the server with a real `AppContext` on `db_url`, yields an in-memory client from `mcp.shared.memory.create_connected_server_and_client_session`. Variants: `mcp_single_role` (settings from the reader URL only), `mcp_short_timeout` (default timeout 1 s), `mcp_no_db` (context factory raises if called — listing tools/prompts must not touch the database).
  - helper `async def call(client, tool: str, **args) -> str` → the tool's text result.
  - helper `container_parquet(db_url, name, select_sql) -> str` → runs `COPY (<select_sql>) TO '/tmp/<name>.parquet' (FORMAT PARQUET)` inside SereneDB (spike §11), returns the container path.
  - output parsers for tests: `ids_in(out) -> list[str]`, `id_of(out, template_text) -> str`, `first_occurrence(out) -> str`, `token_of(out) -> str` (the `confirmed_cost=` value).
- `tests/fixtures/data.py` — deterministic `SELECT … FROM range(n)` generators:
  - `FX` (5,000 rows, 2026-03-01..02; columns `ts, level, service, component, trace_id, message`): `timeout after <NUM>ms calling payments` × 3,000 (service `payments`, level `ERROR`), `login failed for user <*>` × 1,500 (50 users, service `auth`, level `WARN`), `disk full on <PATH>` × 30 (service `checkout`, level `ERROR`), rest INFO noise.
  - `USERS` in three phase files: A (03-01) `login failed for user alice`, `login failed for admin bob`, `login failed for admin carol`; B (03-02) many users and admins; C (03-03) adds `disk full on /dev/sda1`.
  - `CTX`: trace `t-1` with `pool exhausted, 0/50 connections available` (WARN, `payments`) 2 s before `connection refused to 10.0.7.21:5432` (ERROR, `checkout`); `other-service` INFO lines between; one ERROR whose message is a 10,000-char stack trace.
  - `TREND` (2026-03-01..03-28): `T_RISE` doubles in 03-15..28 vs 03-01..14; `T_DAILY` every day; `T_ONCE` only 03-20.
- `tests/fixtures/bgl_sample.log`, `openstack_sample.log` (≈200 lines each from the Loghub-2k samples at `https://github.com/logpai/loghub`), `generic_with_stacktrace.log` (a banner line, then timestamped lines including `ERROR [payments] refund failed` followed by a 3-line `NullPointerException` trace).
- `scripts/test-db.sh` (Task 2) starts the container; integration tests run with `SERENEDB_TEST_URL` exported.

## Internal interfaces (names every task uses)

Defined by the task in brackets; later tasks import them, never redefine them.

- `config` [T3]: `ConfigError`; `Settings(reader_url, writer_url, single_role, logs_host_dir, logs_container_dir, default_timeout_s=60.0, max_timeout_s=600.0, sample_size=100_000, limit_cap=10)`; `Settings.from_env(env) -> Settings`.
- `db` [T3; cancel in T10]: `Rows(columns, rows)` with `dicts()`, `scalar()`; `QueryTimeout(seconds, what)`; `Database(settings)` with `settings`, `effective_timeout(requested) -> float`, `read(sql, params=None, timeout_s=None, what="") -> Rows`, `write(...)`, `copy_rows(table, columns, rows) -> int`, `close()`; `quote_ident(name)`; `validate_name(name)` (`^[a-z][a-z0-9_]{0,40}$`). Connections `autocommit=True`, `cursor_factory=psycopg.ClientCursor`, `%(name)s` params.
- `format` [T3; estimates T9; refusals T10]: `how_measured(kind, period, filters, sample, index_used, tz) -> str`; `clamp_limit(requested, default, cap) -> int`; `cut(items, limit, noun) -> (items, note | None)`; `shorten(text, max_chars=500) -> str`; `plain_error(exc) -> str`; `Measured(value, exact, sample_size=None, hits=None, margin_rel=None)`, `estimate(hits, sample_size, population) -> Measured` (margin_rel = 1.96·sqrt((1−p)/(n·p))), `render(m) -> str`; `refusal(reason, options) -> str`, `timeout_message(seconds, what, how_to_narrow) -> str`.
- `catalog` [T3 schema/models; T7 log tables; T9 templates new/known; T11 generalize/merge/redirect/rename]: `FieldRoles(message, timestamp=None, level=None, service=None, host=None, component=None, trace=None, order=None)` with `present()`; `LogTable(name, source, source_format, mode, relation, roles, filter_index_name, search_index_name, row_count, timezone, created_at, roles_updated_at)`; `Param(pos, name, kind)`; `Template(log_table, template_id, template, regex, params, example, first_seen, last_seen, last_estimate, last_estimate_at)`; `CandidateTemplate(template, regex, params, example, first_seen, last_seen, estimate)`; `UpsertResult(items: list[(Template, "new"|"generalized"|"known")], merged: dict[str, str])`; `Resolved(template, redirected_from)`; `UnknownLogTable`, `UnknownTemplate(template_id, closest)`; `schema.bootstrap(db)`; `CatalogStore(db)` with `create_log_table`, `get_log_table`, `list_log_tables`, `update_roles`, `set_index(name, kind, index_name)`, `templates(log_table)`, `upsert_survey_templates(log_table, found, observed_at)`, `resolve(log_table, template_id)`, `rename_parameter(log_table, template_id, old, new)`.
- `templating` [T4, T5, T6]: `MaskRule`, `MASK_RULES`, `PLACEHOLDER_CAPTURE`, `mask_py(text)`, `mask_sql(expr)`; `CompiledTemplate(regex, params, fixed_words)`, `compile_template(template)`; `MaskedGroup(masked, count, example, first_seen, last_seen, breakdown)`, `MergedTemplate(template, count, example, first_seen, last_seen, breakdown, members)`, `merge_groups(groups, sim_th=0.5, depth=4)`.
- `query.filters` [T7]: `TimeRange(start, end, tz="UTC")`, `parse_time_range(start, end, tz)`, `Filters(level, service, host, component, trace, columns)` with `from_dict`, `MissingRole(role)`, `build_where(lt, tr, f, known_columns) -> (sql, params)`, `diagnose_empty(db, lt, tr, f, known_columns) -> list[str]`.
- `query.stats` / `query.cost` / `query.sampling` [T10]: `ScopeStats(total_rows, rows_in_range, bytes_by_column, time_skippable, remote, has_filter_index, has_search_index)`, `collect(db, lt, tr)`; `Plan(exact, sampling, sample_rows, bytes, seconds, notes)` with `cost_token()`; `Decision(status: "run"|"ask", plan, message)`; `THROUGHPUT_BYTES_PER_S = {"remote": 100e6, "local": 500e6}`, `BUDGET_SECONDS = 30.0` (**Claude's call; tuned by the benchmark**); `decide(stats, columns, want_exact, sample_target, confirmed_cost, budget_s=None)` (`None` reads `BUDGET_SECONDS` at call time); `clause(plan) -> str`.
- `query.occurrence` [T10]: `encode_occurrence(lt, row) -> str` (`<filename>#<file_row_number>` in place, `e:<entry_id>` copied, `pk:<value>` table), `decode_occurrence(lt, occ) -> (where_sql, params)`.
- `query.tags` [T14]: `tag_entries(templates, messages) -> list[str | None]`.
- `query.guard` [T16]: `SqlRejected(reason)`, `check_read_only(sql) -> str`.
- `setup` [T7, T8, T17]: `ResolvedSource(kind, db_path, host_path, size_bytes)`, `RemoteRawTextUnsupported`, `resolve_source(source, settings, format)`; `propose_roles(columns, samples) -> (FieldRoles, evidence)`; `RawEntry(line_start, line_end, ts, level, component, host, message, attrs)`, `LINE_FORMATS`, `detect_line_format(lines)`, `parse_entries(lines, line_format, tz)`, `copy_raw(ctx, name, path, line_format, tz) -> int`; `IndexEstimate(kind, size_bytes, build_seconds, sample_rows, total_rows)`, `indexes.estimate(ctx, lt, kind, sample_rows=1_000_000)`, `indexes.build(ctx, lt, kind) -> str`.
- `context` [T3]: `AppContext(settings, db, store)`, `AppContext.from_settings(settings)` (bootstraps the schema once).
- `server` [T3; each tool task registers its tool]: `build_server(ctx_factory) -> FastMCP`, `call_tool(fn, **kw) -> str` (all errors → `plain_error`; one-time single-role note), `main()`.

**Copied-table schema deviation (builder's call, spec §5):** copied tables add `host VARCHAR` and `attrs JSON` so BGL's node and other parsed fields aren't lost.

**Parallel tickets touching the same file:** each tool task adds its own registration block in `server.py` and its own module under `tools/`; when two tasks modify the same module (e.g. `tools/lookup.py` by #10, #14, #16, #17), the later one rebases and keeps both changes.

---

### Task 2 (#2): Verify SereneDB behaviours

**Blocked by:** none.

**Files:** Create `scripts/test-db.sh`, `scripts/verify_serenedb.py`, `docs/spikes/2026-10-18-serenedb-verification.md`.

**Produces:** the spike note with numbered sections §1–§12 that later tasks cite; `scripts/test-db.sh` starting `serenedb/serenedb:latest` as `sdb-test` on host port 17890 and printing `SERENEDB_TEST_URL`.

- [ ] **Step 1:** Write `scripts/test-db.sh` (run container, wait until `SELECT 1` succeeds via psycopg, print the URL with the default credentials found in §1).
- [ ] **Step 2:** Write `scripts/verify_serenedb.py`, one function per question, each printing PASS/FAIL and observed output:
  1. connection defaults; `psycopg.connect(url, autocommit=True, cursor_factory=psycopg.ClientCursor)` runs `SELECT %(x)s`;
  2. a long query cancelled by `conn.cancel_safe()` from a timer thread raises `QueryCanceled` and the connection still works;
  3. `CREATE SCHEMA IF NOT EXISTS`, `PRIMARY KEY`, `JSON`, `UPDATE`, `DELETE`, `DROP SCHEMA … CASCADE`;
  4. `regexp_replace(…, 'g')`, `regexp_full_match`, `regexp_extract(s, p, ['a','b'])`, `any_value`, `quantile_cont`, `date_trunc`, `count(*) FILTER (WHERE …)`, `AT TIME ZONE`;
  5. `read_parquet('https://public-pme.s3.eu-west-3.amazonaws.com/text_bench/part_000.parquet', filename=true, file_row_number=true)` inside SereneDB only: columns/types, httpfs requirement, `parquet_file_metadata` / `parquet_metadata` fields (`num_rows`, `total_compressed_size`, `stats_min_value`, `stats_max_value`);
  6. `EXPLAIN` output shape (does it report rows/bytes?);
  7. `USING SAMPLE 0.01% (system)` vs `reservoir(1000 ROWS)` on that view: wall time; row-group pruning under a `Timestamp` range;
  8. filter `SeverityText = 'ERROR'` then reservoir sample, timed against selecting only `SeverityText` (late materialization of `Body`) → decision filter-first vs sample-first;
  9. `CREATE INDEX … USING inverted` over a view `… LIMIT 1000000`: build time, how to read on-disk size, `ts_dict_agg` / `ts_dict_count`, `DROP INDEX`;
  10. `CREATE TEXT SEARCH DICTIONARY extractor.log_dict AS split_text(case := 'lower') | normalize_tokens('en_US.UTF-8', accent := false) WITH (frequency, position)`, `@@ ts_phrase(...)`, `ts_levenshtein`;
  11. `COPY (SELECT …) TO '/tmp/x.parquet' (FORMAT PARQUET)` inside the container;
  12. `cursor.copy("COPY t FROM STDIN")` streaming rows.
- [ ] **Step 3:** Run `bash scripts/test-db.sh` then `uv run python scripts/verify_serenedb.py`; record results in the note, including the §8 decision and the cancel mechanism (fallback if §2 fails: close + reconnect).
- [ ] **Step 4:** Commit `git add scripts docs/spikes && git commit -m "spike: verify SereneDB behaviours (#2)"`. If §5 fails, stop and report — in-place remote Parquet is a core requirement.

---

### Task 3 (#3): Walking skeleton

**Blocked by:** none.

**Files:** Create `pyproject.toml`, `src/serenedb_extractor/{__init__,config,db,format,context,server}.py`, `src/serenedb_extractor/catalog/{__init__,models,schema,store}.py`, `src/serenedb_extractor/tools/{__init__,describe}.py`, `tests/conftest.py`, `tests/tools/test_skeleton.py`.

**Produces:** `config`, `db` (without cancel), `format` (T3 part), catalog schema + model types, `context`, `server`, `describe_logs` (empty state only), the test harness.

- [ ] **Step 1: Failing tests** (`tests/tools/test_skeleton.py`)

```python
@pytest.mark.db
async def test_describe_empty(mcp):
    out = await call(mcp, "describe_logs")
    assert out.startswith("How this was measured: ") and "no log tables yet" in out

@pytest.mark.db
async def test_bootstrap_idempotent(mcp):
    for _ in range(2):
        assert "no log tables yet" in await call(mcp, "describe_logs")

@pytest.mark.db
async def test_single_role_note_once(mcp_single_role):
    first, second = await call(mcp_single_role, "describe_logs"), await call(mcp_single_role, "describe_logs")
    assert "not enforcing read-only limits" in first and "not enforcing" not in second

@pytest.mark.db
async def test_unknown_log_table_plain(mcp):
    out = await call(mcp, "describe_logs", log_table="nope")
    assert "nope" in out and "Traceback" not in out

def test_config_errors():
    with pytest.raises(ConfigError, match="SERENEDB_READER_URL"): Settings.from_env({})
    with pytest.raises(ConfigError, match="LOGS_CONTAINER_DIR"):
        Settings.from_env({"SERENEDB_READER_URL": "x", "LOGS_HOST_DIR": "/tmp"})

async def test_annotations_registered(mcp_no_db):
    tools = {t.name: t for t in (await mcp_no_db.list_tools()).tools}
    assert tools["describe_logs"].annotations.readOnlyHint is True
```

- [ ] **Step 2:** `uv run pytest tests/tools/test_skeleton.py -v` → FAIL.
- [ ] **Step 3:** Implement: `pyproject.toml` (hatchling; deps `mcp`, `psycopg[binary]`, `drain3`, `sqlglot`; dev `pytest`, `pytest-asyncio` with `asyncio_mode = "auto"`; marker `db`; script `serenedb_extractor.server:main`); `Settings.from_env`; `Database` (reader/writer, `ClientCursor`, `effective_timeout`); `schema.bootstrap` (spec §5 DDL + `log_tables.timezone VARCHAR NOT NULL DEFAULT 'UTC'`); `format` T3 functions; `build_server` registering `describe_logs` (`readOnlyHint=True`); `call_tool`; `describe_logs` empty state.
- [ ] **Step 4:** Run with `SERENEDB_TEST_URL` → PASS.
- [ ] **Step 5:** Commit `git add -A && git commit -m "feat: walking skeleton (#3)"`.

---

### Task 4 (#4): Generic value masking

**Blocked by:** none.

**Files:** Create `src/serenedb_extractor/templating/{__init__,masking}.py`, `tests/templating/test_masking.py`, `tests/fixtures/bgl_sample.log`, `tests/fixtures/openstack_sample.log`.

**Produces:** `MaskRule`, `MASK_RULES` (order: URL `<URL>`, email `<EMAIL>`, UUID `<UUID>`, IPv4 with optional `:port` `<IP>`, absolute path `<PATH>`, hex `0x…` or ≥ 8 hex chars containing a digit `<HEX>`, quoted string `<STR>`, number `<NUM>`), `PLACEHOLDER_CAPTURE` (each placeholder and `<*>` → capture regex, e.g. `<NUM>` → `(-?\d+(?:\.\d+)?)`, `<*>` → `(\S+)`), `mask_py`, `mask_sql`. Only RE2/Python-common syntax (no lookaround, no backreferences).

- [ ] **Step 1: Failing tests**

```python
@pytest.mark.parametrize("raw,masked", [
    ("timeout after 3021ms for user 8812", "timeout after <NUM>ms for user <NUM>"),
    ("req 8f3a2c1e-9b4d-4e2a-8c1f-0a2b3c4d5e6f done", "req <UUID> done"),
    ("connect 10.0.4.12:5432 refused", "connect <IP> refused"),
    ("GET https://x.io/a?b=1 200", "GET <URL> <NUM>"),
    ("open /var/log/app.log failed", "open <PATH> failed"),
    ("addr 0x7ffde3a1 bad", "addr <HEX> bad"),
    ("user 'alice' not found", "user <STR> not found"),
    ("R02-M1-N0-C:J12-U11 ok", "R02-M1-N0-C:J12-U11 ok"),
])
def test_mask_py(raw, masked): assert mask_py(raw) == masked

@pytest.mark.db
def test_sql_equals_python(database):
    for raw in SAMPLES:   # inputs above + 20 lines from each Loghub fixture
        assert database.read(f"SELECT {mask_sql('%(m)s')}", {"m": raw}).scalar() == mask_py(raw)
```

(`database`: a bare `Database` on `db_url`; the only DB-backed test on this seam.)

- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `git commit -m "feat: generic value masking (#4)"` (after `git add`).

---

### Task 5 (#5): Template → regex compiler and parameter naming

**Blocked by:** none (uses `PLACEHOLDER_CAPTURE`; if #4 isn't merged yet, define the same dict locally and replace it on rebase).

**Files:** Create `src/serenedb_extractor/templating/regex.py`, `tests/templating/test_regex.py`.

**Produces:** `CompiledTemplate`, `compile_template`. Literal text escaped (RE2-compatible), whitespace runs → `\s+`, anchored `^…$`. Names: token before the placeholder ending in `=` or `:` → that key; else the preceding alphabetic word; else `<kind>_<n>` (`*` → `any`); duplicates get `_2`. `fixed_words`: literal fragments ≥ 4 chars, longest first, at most 3.

- [ ] **Step 1: Failing tests**

```python
def test_names_and_match():
    c = compile_template("login failed for user <*> from <IP>")
    assert [p.name for p in c.params] == ["user", "from"] and re.fullmatch(c.regex, "login failed for user bob from 10.0.0.7")
def test_key_value_names():   assert [p.name for p in compile_template("status=<NUM> len: <NUM>").params] == ["status", "len"]
def test_fallback_names():    assert [p.name for p in compile_template("<NUM> <NUM> done").params] == ["num_1", "num_2"]
def test_metachar_round_trip():                                          # Review Focus 2
    assert re.fullmatch(compile_template("GET /api/v1/items?id=<NUM> (retry) [x]$").regex, "GET /api/v1/items?id=42 (retry) [x]$")
def test_fixed_words():       assert compile_template("disk full on <*> after <NUM> retries").fixed_words[0] == "disk full on"
```

- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `git commit -m "feat: template regex compiler and parameter naming (#5)"`.

---

### Task 6 (#6): Drain merge of masked groups

**Blocked by:** none.

**Files:** Create `src/serenedb_extractor/templating/drain.py`, `tests/templating/test_drain.py`.

**Produces:** `MaskedGroup`, `MergedTemplate`, `merge_groups`. `drain3.TemplateMiner` with no masking instructions and `parametrize_numeric_tokens = False`; each group's masked string fed once; counts, first/last seen and breakdowns aggregated per cluster by group weight; example kept from the largest member; sorted by count desc.

- [ ] **Step 1: Failing tests**

```python
def test_word_variation_merges():
    (m,) = merge_groups([g("login failed for user alice", 5), g("login failed for user bob", 3), g("login failed for user carol", 2)])
    assert (m.template, m.count) == ("login failed for user <*>", 10)
def test_masked_tokens_survive(): assert merge_groups([g("timeout after <NUM>ms calling payments", 4)])[0].template == "timeout after <NUM>ms calling payments"
def test_breakdowns_summed():
    assert merge_groups([g("x a", 2, service={"checkout": 2}), g("x b", 1, service={"payments": 1})])[0].breakdown["service"] == {"checkout": 2, "payments": 1}
def test_shapes_stay_apart():     assert len(merge_groups([g("disk full on <PATH>", 1), g("cache miss for key <STR>", 1)])) == 2
```

- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `git commit -m "feat: drain merge of masked groups (#6)"`.

---

### Task 7 (#7): Set up a structured log table in place

**Blocked by:** #2, #3.

**Files:** Create `src/serenedb_extractor/setup/{__init__,paths,roles,sniff}.py`, `src/serenedb_extractor/query/{__init__,filters}.py`, `src/serenedb_extractor/tools/setup_tools.py`, `tests/tools/test_setup_structured.py`, `tests/fixtures/data.py`; modify `tools/describe.py`, `catalog/store.py`, `server.py`.

**Produces:** `inspect_source(ctx, source, format_hint=None, line_format=None) -> str`; `setup_log_table(ctx, name, source, roles=None, line_format=None, timezone="UTC", build_filter_index=False, build_search_index=False) -> str` (Parquet/JSON/table; raw text delegates to #8's `copy_raw` when present, else "raw text setup isn't available yet"); full `describe_logs(ctx, log_table=None, find_values=None, start=None, end=None, timezone="UTC") -> str`; `query.filters`; `setup.paths`; `setup.roles`; store log-table methods.

`propose_roles`: case-insensitive candidates, OpenTelemetry names first (`Timestamp`, `Body`, `SeverityText`, `ServiceName`, `TraceId`), then `ts|time|@timestamp`, `message|msg|log`, `level|lvl|severity`, `service|app`, `host|hostname|node|pod`, `component|logger|module`, `trace_id|request_id|req_id`; message falls back to the widest VARCHAR column; roles stored as quoted identifiers. In-place view: `CREATE VIEW extractor.lt_<name> AS SELECT * FROM read_parquet('<db_path>', filename=true, file_row_number=true)` (or `read_json`, per spike §5); `roles.order = 'file_row_number'`. `describe_logs` per log table: source, mode, roles (absent listed), row count, time range (Parquet stats when in place), `indexes: none` or names, context scopes (`trace`, then present of `service`/`host`, always `everything`), catalog size, top values of level/service/component from a 10k-row block sample labelled `(sampled — rare values may be missing)`; `find_values={"role_or_column", "like"}` → `SELECT DISTINCT … ILIKE` within the time range. Zero matches → `diagnose_empty` lines; a time range outside the data names the range the data covers.

- [ ] **Step 1: Failing tests** (`@pytest.mark.db`; `fx_path` = `container_parquet(db_url, "fx", FX)`; `fx_lt` = `fx_path` set up as `fx`)

```python
async def test_inspect_has_no_side_effects(mcp, fx_path):
    out = await call(mcp, "inspect_source", source=fx_path)
    assert "level: level" in out and "read in place" in out
    assert "no log tables yet" in await call(mcp, "describe_logs")

async def test_setup_and_describe(mcp, fx_path):
    await call(mcp, "setup_log_table", name="fx", source=fx_path)
    out = await call(mcp, "describe_logs", log_table="fx")
    assert "in place" in out and "host: absent" in out and "context scopes: trace, service, everything" in out
    assert "sampled — rare values may be missing" in out and "ERROR" in out

async def test_correct_roles(mcp, fx_path):
    await call(mcp, "setup_log_table", name="fx", source=fx_path)
    assert "updated field roles: component" in await call(mcp, "setup_log_table", name="fx", source=fx_path, roles={"component": "service"})

async def test_find_values(mcp, fx_lt):
    fv = lambda like: call(mcp, "describe_logs", log_table="fx", find_values={"role_or_column": "service", "like": like})
    assert "payments" in await fv("pay") and "no values like 'billing' in service" in await fv("billing")

async def test_time_range_outside_data(mcp, fx_lt):
    assert "data covers 2026-03-01" in await call(mcp, "describe_logs", log_table="fx", start="2030-01-01", end="2030-01-02")

async def test_remote_raw_rejected(mcp):
    assert "raw text" in (await call(mcp, "inspect_source", source="https://example.com/app.log")).lower()

async def test_filter_on_absent_role(mcp, fx_lt):
    out = await call(mcp, "describe_logs", log_table="fx", find_values={"role_or_column": "host", "like": "x"})
    assert "no host" in out.lower()
```

- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `git commit -m "feat: structured setup in place and describe_logs (#7)"`.

---

### Task 8 (#8): Set up raw text logs (copied)

**Blocked by:** #2, #3.

**Files:** Create `src/serenedb_extractor/setup/{rawlog,copy}.py`, `tests/tools/test_setup_raw.py`, `tests/fixtures/generic_with_stacktrace.log`; modify `tools/setup_tools.py`, `setup/paths.py` (create `resolve_source` here if #7 isn't merged; reconcile on rebase).

**Produces:** `RawEntry`, `LINE_FORMATS` (`generic`; `bgl` = `<Label> <Timestamp> <Date> <Node> <Time> <NodeRepeat> <Type> <Component> <Level> <Content>`; `openstack` = `<Logrecord> <Date> <Time> <Pid> <Level> <Component> \[<ADDR>\] <Content>`), `detect_line_format`, `parse_entries`, `copy_raw`. Field mapping: `Date`+`Time` (or `Time`) → `ts`, `Level` → `level`, `Component` → `component`, `Node` → `host`, `Content` → `message`, rest → `attrs`. A non-matching line continues the previous entry; lines before the first match form one entry with `ts=None`. Copy: `extractor.lt_<name>(entry_id, source_file, line_start, line_end, ts, level, component, host, message, attrs)`, sorted by `ts` (NULLs first), `entry_id` in that order, `roles.order = 'entry_id'`. Mounted path → SereneDB reads the lines (per spike) and Python parses them; else Python reads the host file. Structured local files outside the mount are read in Python and copied too. Size > 1 GB outside the mount → "this is a full copy; mounting the folder would avoid it".

- [ ] **Step 1: Failing tests** (`@pytest.mark.db`)

```python
async def test_stacktrace_joined_and_untimestamped_reported(mcp, tmp_path):   # Review Focus 3
    p = copy_fixture(tmp_path, "generic_with_stacktrace.log")
    out = await call(mcp, "setup_log_table", name="app", source=str(p))
    assert "copied" in out and "UTC" in out
    assert "1 entry has no timestamp" in await call(mcp, "describe_logs", log_table="app")

async def test_bgl_and_openstack_parse(mcp, tmp_path):
    for name in ("bgl", "openstack"):
        assert "copied" in await call(mcp, "setup_log_table", name=name, source=str(copy_fixture(tmp_path, f"{name}_sample.log")))
    assert "KERNEL" in await call(mcp, "describe_logs", log_table="bgl")
    assert "nova" in await call(mcp, "describe_logs", log_table="openstack")

async def test_structured_outside_mount_copied(mcp, tmp_path):
    p = tmp_path / "local.jsonl"
    p.write_text("\n".join(json.dumps({"ts": f"2026-03-01T00:00:{i:02d}", "level": "INFO", "msg": f"hello {i}"}) for i in range(50)))
    out = await call(mcp, "setup_log_table", name="local", source=str(p))
    assert "copied" in out and "outside the mounted folder" in out

async def test_large_file_warning(mcp, tmp_path):
    p = tmp_path / "big.log"; p.write_text("2026-03-01 00:00:00 INFO [x] start\n")
    os.truncate(p, 1_100_000_000)          # sparse, > 1 GB
    assert "full copy" in await call(mcp, "inspect_source", source=str(p))
```

- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `git commit -m "feat: raw text setup with multi-line entries; copied tables add host, attrs (#8)"`.

---

### Task 9 (#9): First survey

**Blocked by:** #4, #5, #6, #7.

**Files:** Create `src/serenedb_extractor/tools/survey.py`, `tests/tools/test_survey.py`; modify `format.py` (estimates), `catalog/store.py` (`templates`, `upsert_survey_templates` new/known, ID assignment), `server.py`.

**Produces:** `survey(ctx, log_table, start=None, end=None, filters=None, exclude=None, sample_size=None, limit=None, timezone="UTC", confirmed_cost=None) -> str` (`exclude` completed in #11, cost in #12); `Measured`, `estimate`, `render`; store new/known upsert.

Flow: `build_where` → population `count(*)` with the WHERE → one query over `USING SAMPLE reservoir(<sample_size> ROWS)` (filter-first; #12 refines): `SELECT <mask_sql(msg)>, <service>, <component>, count(*), any_value(<msg>), min(<ts>), max(<ts>) … GROUP BY 1,2,3` → `MaskedGroup`s → `merge_groups` → `compile_template` → `upsert_survey_templates` (identical template text = `known`; else `new` with the next `T<n>`) → output: `how_measured`, coverage line (`these 30 cover 96% of the sample`), per template: ID, template, `render(estimate)` and share, top 3 services/components with estimated shares (`payments ≈62%`), `shorten`ed example, `NEW` flag, `cut` note. No sampled rows → `diagnose_empty`.

- [ ] **Step 1: Failing tests** (`@pytest.mark.db`)

```python
async def test_finds_planted_templates(mcp, fx_lt):
    out = await call(mcp, "survey", log_table="fx")
    assert out.startswith("How this was measured: ")
    assert "timeout after <NUM>ms calling payments" in out and "login failed for user <*>" in out
    assert "≈" in out and "estimated from" in out and "NEW" in out and "cover" in out

async def test_breakdown(mcp, fx_lt):
    assert "payments ≈" in await call(mcp, "survey", log_table="fx")

async def test_second_survey_same_ids_no_duplicates(mcp, fx_lt):            # Review Focus 5
    a = await call(mcp, "survey", log_table="fx"); b = await call(mcp, "survey", log_table="fx")
    assert ids_in(a) == ids_in(b) and "NEW" not in b

async def test_rare_marked(mcp, fx_lt):
    assert "too rare to estimate reliably" in await call(mcp, "survey", log_table="fx", sample_size=200)

async def test_misspelled_level(mcp, fx_lt):                               # Review Focus 1
    out = await call(mcp, "survey", log_table="fx", filters={"level": ["error"]})
    assert "level='error' matched nothing" in out and "ERROR" in out and "no errors" not in out.lower()

async def test_limit_note(mcp, fx_lt):
    assert "showing 1 of" in await call(mcp, "survey", log_table="fx", limit=1)
```

- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `git commit -m "feat: first survey (#9)"`.

---

### Task 10 (#10): Cost check, timeouts and `search_logs`

**Blocked by:** #2, #7.

**Files:** Create `src/serenedb_extractor/query/{stats,cost,sampling,occurrence}.py`, `src/serenedb_extractor/tools/lookup.py`, `tests/tools/test_cost_search.py`; modify `db.py` (cancel), `format.py` (`refusal`, `timeout_message`), `tools/describe.py` (value lookup through `decide`), `server.py`.

**Produces:** `ScopeStats`, `collect`, `Plan`, `Decision`, `decide`, constants, `clause`, occurrence encode/decode, `Database` timeout via `conn.cancel_safe()` from a timer (or spike §2 fallback) raising `QueryTimeout`, and `search_logs(ctx, log_table, start=None, end=None, filters=None, text=None, fuzzy=False, order="newest", limit=None, timezone="UTC", confirmed_cost=None) -> str`.

`collect`: in-place Parquet from `parquet_metadata` (per-column compressed sizes; row groups overlapping the range → `rows_in_range`, `time_skippable`); copied tables from `count(*)` and average width × rows. `decide` ladder (spec §8): (1) columns covered by an index cost ≈ 0; (2) callers pass only the columns actually read; (3) exact over budget → estimated block sample sized to `sample_target`; (4) halve the fraction down to 1/8 with the wider margin noted; first fit → `run` with a note ("an exact count would read ~2.1 TB, so this is estimated from a sample"); none → `ask` via `refusal` with options run anyway (`confirmed_cost=<token>`), narrow period/services, build a search index; a `confirmed_cost` within 2× of the fresh plan → exact `run` with `seconds` as the timeout (clamped). Never narrows scope. `search_logs` without a search index: `<msg> ILIKE %(pattern)s`; `fuzzy` without one → "fuzzy search needs a search index (see create_index with dry_run)". Rows: timestamp, present roles, `shorten`ed message, occurrence ID. `lookup.SEARCH_SQL_SUFFIX = ""` is a documented test-only hook appended to the search WHERE.

- [ ] **Step 1: Failing tests** (`@pytest.mark.db`)

```python
async def test_search_exact(mcp, fx_lt):
    out = await call(mcp, "search_logs", log_table="fx", text="disk full")
    assert "disk full on" in out and "fx.parquet#" in out and "≈" not in out

async def test_fallback_to_estimate(mcp, fx_lt, monkeypatch):
    monkeypatch.setattr(cost, "THROUGHPUT_BYTES_PER_S", {"remote": 1.0, "local": 1e3})
    assert "estimated from a sample" in await call(mcp, "search_logs", log_table="fx", text="disk full")

async def test_ask_then_confirm(mcp, fx_lt, monkeypatch):
    monkeypatch.setattr(cost, "BUDGET_SECONDS", 0.0)
    ask = await call(mcp, "search_logs", log_table="fx", text="disk full")
    assert "TOO EXPENSIVE" in ask and "confirmed_cost=" in ask and "search index" in ask
    assert "disk full on" in await call(mcp, "search_logs", log_table="fx", text="disk full", confirmed_cost=token_of(ask))

async def test_timeout_cancels_and_recovers(mcp_short_timeout, fx_lt_short, monkeypatch):
    monkeypatch.setattr(lookup, "SEARCH_SQL_SUFFIX", " AND (SELECT count(*) FROM range(10000000000)) > 0")
    out = await call(mcp_short_timeout, "search_logs", log_table="fx", text="disk")
    assert out.startswith("TIMEOUT after 1s") and "narrow" in out
    monkeypatch.setattr(lookup, "SEARCH_SQL_SUFFIX", "")
    assert "disk full on" in await call(mcp_short_timeout, "search_logs", log_table="fx", text="disk full")

async def test_fuzzy_needs_index(mcp, fx_lt):
    assert "needs a search index" in await call(mcp, "search_logs", log_table="fx", text="dsik", fuzzy=True)

async def test_value_lookup_cost_checked(mcp, fx_lt, monkeypatch):
    monkeypatch.setattr(cost, "BUDGET_SECONDS", 0.0)
    assert "TOO EXPENSIVE" in await call(mcp, "describe_logs", log_table="fx", find_values={"role_or_column": "service", "like": "pay"})
```

(`fx_lt_short`: `fx_lt` set up through `mcp_short_timeout`.)

- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `git commit -m "feat: cost check, timeouts with cancel, search_logs (#10)"`.

---

### Task 11 (#11): Catalog evolution

**Blocked by:** #9.

**Files:** Create `src/serenedb_extractor/tools/catalog_tools.py`, `tests/tools/test_catalog_evolution.py`; modify `catalog/store.py`, `tools/survey.py` (`exclude`, redirect notes), `server.py`.

**Produces:** generalize/merge/redirect in `upsert_survey_templates`; `resolve`; store `rename_parameter`; tool `rename_parameter(ctx, log_table, template, old_name, new_name) -> str`.

Rules (ADR 0001): candidate regex full-matching existing examples (Python `re.fullmatch`) → the lowest-numbered matched template keeps its ID, takes the candidate's template/regex/params, keeps the earliest first_seen; others deleted with `template_redirects(old → survivor)`; redirects pointing at deleted IDs rewritten so every redirect is one hop. `resolve` follows one hop; tools note `T3 was merged into T2`; unknown → `UnknownTemplate` with `closest` (template whose regex matches the unknown ID's recorded example, else None). `exclude`: `AND NOT regexp_full_match(<msg>, %(x_i)s)` per resolved template.

- [ ] **Step 1: Failing tests** (`@pytest.mark.db`; `users_lt` = the three `USERS` phase files under one glob, set up as `users`)

```python
A, B, C = ("2026-03-01", "2026-03-02"), ("2026-03-02", "2026-03-03"), ("2026-03-03", "2026-03-04")

async def test_generalize_keeps_id(mcp, users_lt):
    a = await call(mcp, "survey", log_table="users", start=A[0], end=A[1])
    b = await call(mcp, "survey", log_table="users", start=B[0], end=B[1])
    assert id_of(a, "login failed for user alice") == id_of(b, "login failed for user <*>")

async def test_merge_redirect_and_note(mcp, users_lt):
    a = await call(mcp, "survey", log_table="users", start=A[0], end=A[1])          # bob and carol are separate templates
    await call(mcp, "survey", log_table="users", start=B[0], end=B[1])               # merges them
    carol = id_of(a, "login failed for admin carol")
    assert f"{carol} was merged into" in await call(mcp, "survey", log_table="users", exclude=[carol])

async def test_ids_never_reused(mcp, users_lt):
    for s, e in (A, B):
        await call(mcp, "survey", log_table="users", start=s, end=e)
    c = await call(mcp, "survey", log_table="users", start=C[0], end=C[1])
    assert id_of(c, "disk full on <PATH>") == "T4"

async def test_exclude_surfaces_rare(mcp, fx_lt):
    first = await call(mcp, "survey", log_table="fx", sample_size=500)
    noisy = [i for i in ids_in(first) if i != id_of(first, "disk full on <PATH>")] if "disk full" in first else ids_in(first)
    assert "disk full on <PATH>" in await call(mcp, "survey", log_table="fx", exclude=noisy, sample_size=500)

async def test_rename(mcp, fx_lt):
    tid = id_of(await call(mcp, "survey", log_table="fx"), "login failed for user <*>")
    assert "username" in await call(mcp, "rename_parameter", log_table="fx", template=tid, old_name="user", new_name="username")
    assert "invalid" in (await call(mcp, "rename_parameter", log_table="fx", template=tid, old_name="username", new_name="Bad Name")).lower()

async def test_unknown_id(mcp, fx_lt):
    assert "T99" in await call(mcp, "survey", log_table="fx", exclude=["T99"])
```

- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `git commit -m "feat: catalog generalization, merges, exclude, rename_parameter (#11)"`.

---

### Task 12 (#12): Cost-aware survey

**Blocked by:** #9, #10.

**Files:** Modify `tools/survey.py`; create `tests/tools/test_survey_cost.py`.

`survey` calls `collect` + `decide(columns=[message, filter columns], want_exact=False, sample_target=sample_size)`; the population comes from `count(*)` when `decide` prices it cheap, else from `rows_in_range`, stated as `population estimated`; sampling via `clause(plan)` (reservoir for small scopes, system for huge); filter-first or sample-first per spike §8; `ask` returns the refusal; `confirmed_cost` honoured; `QueryTimeout` surfaces as the timeout message.

- [ ] **Step 1: Failing tests** (`@pytest.mark.db`)

```python
async def test_population_estimated_when_expensive(mcp, fx_lt, monkeypatch):
    monkeypatch.setattr(cost, "THROUGHPUT_BYTES_PER_S", {"remote": 1.0, "local": 1e3})
    assert "population estimated" in await call(mcp, "survey", log_table="fx")

async def test_ask_then_confirm(mcp, fx_lt, monkeypatch):
    monkeypatch.setattr(cost, "BUDGET_SECONDS", 0.0)
    ask = await call(mcp, "survey", log_table="fx")
    assert "TOO EXPENSIVE" in ask
    done = await call(mcp, "survey", log_table="fx", confirmed_cost=token_of(ask))
    assert done.startswith("How this was measured: ") and "timeout after <NUM>ms calling payments" in done

async def test_sampling_stated(mcp, fx_lt):
    assert "reservoir" in (await call(mcp, "survey", log_table="fx")).splitlines()[0]

async def test_survey_timeout(mcp_short_timeout, fx_lt_short, monkeypatch):
    monkeypatch.setattr(survey_mod, "SURVEY_SQL_SUFFIX", " AND (SELECT count(*) FROM range(10000000000)) > 0")
    assert (await call(mcp_short_timeout, "survey", log_table="fx")).startswith("TIMEOUT after 1s")
```

(`survey_mod.SURVEY_SQL_SUFFIX = ""`: the same documented test-only hook as in #10.)

- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `git commit -m "feat: cost-aware survey (#12)"`.

---

### Task 13 (#13): Exact investigation — `locate_occurrences`, `extract_params`

**Blocked by:** #9, #10.

**Files:** Create `src/serenedb_extractor/tools/investigate.py`, `tests/tools/test_investigate.py`; modify `server.py`.

**Produces:** `locate_occurrences(ctx, log_table, templates, start=None, end=None, filters=None, group_by=None, examples_per_group=3, limit=None, timezone="UTC", confirmed_cost=None) -> str`; `extract_params(ctx, log_table, template, start=None, end=None, filters=None, by=None, limit=None, timezone="UTC", confirmed_cost=None) -> str`; `parse_group_by(lt, items, known_columns) -> list[(label, sql_expr)]` (role names, columns, `time:<n>m|h|d`).

`locate_occurrences`: ≥ 1 template else "say which templates — run a survey first"; prefilter `<msg> LIKE '%<first fixed word>%'` OR-combined; `count(*) FILTER (WHERE regexp_full_match(<msg>, %(r_i)s))` per template grouped by `group_by`; examples via `row_number() OVER (PARTITION BY … ORDER BY <ts>) <= examples_per_group` with `encode_occurrence`. `extract_params`: `regexp_extract(<msg>, %(regex)s, [names])`; top values per parameter; `NUM` kinds also min/p50/p95/max via `quantile_cont`; `by` breakdown. Both go through `decide`; estimated fallbacks rendered as estimates.

- [ ] **Step 1: Failing tests** (`@pytest.mark.db`; `fx_surveyed` = `fx_lt` + one survey; `ID_TIMEOUT`, `ID_LOGIN` parsed from its output)

```python
async def test_exact_by_service(mcp, fx_surveyed):
    out = await call(mcp, "locate_occurrences", log_table="fx", templates=[ID_TIMEOUT], group_by=["service"])
    assert "payments: 3,000" in out and "≈" not in out and "fx.parquet#" in out

async def test_time_bucket(mcp, fx_surveyed):
    assert "2026-03-01" in await call(mcp, "locate_occurrences", log_table="fx", templates=[ID_TIMEOUT], group_by=["time:1d"])

async def test_requires_template(mcp, fx_lt):
    assert "run a survey first" in await call(mcp, "locate_occurrences", log_table="fx", templates=[])

async def test_word_param(mcp, fx_surveyed):
    assert "showing 10 of 50" in await call(mcp, "extract_params", log_table="fx", template=ID_LOGIN)

async def test_numeric_param(mcp, fx_surveyed):
    out = await call(mcp, "extract_params", log_table="fx", template=ID_TIMEOUT)
    assert all(k in out for k in ("min", "p50", "p95", "max"))

async def test_param_by_service(mcp, fx_surveyed):
    assert "payments" in await call(mcp, "extract_params", log_table="fx", template=ID_TIMEOUT, by="service")
```

- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `git commit -m "feat: locate_occurrences and extract_params (#13)"`.

---

### Task 14 (#14): Context around an occurrence

**Blocked by:** #9, #10.

**Files:** Create `src/serenedb_extractor/query/tags.py`, `tests/tools/test_context.py`; modify `tools/investigate.py` (create it if #13 isn't merged), `tools/lookup.py` (tags in `search_logs`), `server.py`.

**Produces:** `get_context(ctx, log_table, occurrence, scope=None, window_minutes=5.0, before=10, after=10, filters=None) -> str`; `tag_entries(templates, messages)`.

Default scope: `trace` if present and non-null on the occurrence row, else present of `service`+`host`, else `everything`; a scope naming an absent role → error listing the available scopes. Window `[ts − w, ts + w]`; equality on scope expressions to the occurrence's values; plus `filters`; ordered by `(ts, roles.order)`; nearest `before`/`after`; occurrence marked `→`; each entry tagged `[T<n>]` by the first catalog template whose regex matches (else `—`); messages `shorten`ed; the result states the window (`±5 min`). Malformed occurrence → plain explanation mentioning "occurrence". `search_logs` rows gain the same tags.

- [ ] **Step 1: Failing tests** (`@pytest.mark.db`; `ctx_lt` = `CTX` set up as `ctxfx` and surveyed once; `OCC_REFUSED`, `OCC_STACKTRACE` taken via `first_occurrence` from `search_logs`)

```python
async def test_trace_scope_shows_cause(mcp, ctx_lt):
    out = await call(mcp, "get_context", log_table="ctxfx", occurrence=OCC_REFUSED)
    assert "pool exhausted" in out and "other-service" not in out and "→" in out and "±5 min" in out

async def test_everything_scope(mcp, ctx_lt):
    assert "other-service" in await call(mcp, "get_context", log_table="ctxfx", occurrence=OCC_REFUSED, scope="everything")

async def test_wider_window(mcp, ctx_lt):
    narrow = await call(mcp, "get_context", log_table="ctxfx", occurrence=OCC_REFUSED, window_minutes=0.01)
    wide = await call(mcp, "get_context", log_table="ctxfx", occurrence=OCC_REFUSED, window_minutes=10)
    assert "pool exhausted" not in narrow and "pool exhausted" in wide

async def test_absent_scope(mcp, fx_lt):
    occ = first_occurrence(await call(mcp, "search_logs", log_table="fx", text="disk"))
    assert "available scopes" in await call(mcp, "get_context", log_table="fx", occurrence=occ, scope=["host"])

async def test_long_entry_cut(mcp, ctx_lt):                                # Review Focus 4
    assert "…(cut)" in await call(mcp, "get_context", log_table="ctxfx", occurrence=OCC_STACKTRACE)

async def test_tags_and_bad_occurrence(mcp, ctx_lt):
    assert "[T" in await call(mcp, "search_logs", log_table="ctxfx", text="refused")
    assert "occurrence" in (await call(mcp, "get_context", log_table="ctxfx", occurrence="garbage")).lower()
```

- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `git commit -m "feat: get_context and template tags (#14)"`.

---

### Task 15 (#15): Trends

**Blocked by:** #9, #10.

**Files:** Create `src/serenedb_extractor/tools/trend.py`, `tests/tools/test_trend.py`; modify `server.py`.

**Produces:** `trend(ctx, log_table, templates=None, start=None, end=None, bucket="day", exact=False, filters=None, top_n=10, timezone="UTC", confirmed_cost=None) -> str`.

`templates=None` → top `top_n` catalog templates by `last_estimate`. A period is required (else "which period should I use?"). Preceding period of equal length; coverage vs the log table's time range — partial or no coverage → `limited comparison`; `new` only when the preceding period is fully covered and its count is 0. Estimated (default): per-bucket samples sized `max(2000, sample_size / buckets)`; exact: one scan with `count(*) FILTER` per template grouped by `date_trunc(bucket, <ts> AT TIME ZONE tz)`, through `decide`. Per template: period count, preceding count, change %, `N of M days|hours`, distinct components, compact series; the zone is stated.

- [ ] **Step 1: Failing tests** (`@pytest.mark.db`; `trend_lt` = `TREND` set up as `tr` and surveyed; `T_RISE`, `T_DAILY`, `T_ONCE` parsed from that survey)

```python
async def test_estimated_default(mcp, trend_lt):
    out = await call(mcp, "trend", log_table="tr", templates=[T_RISE], start="2026-03-15", end="2026-03-29")
    assert "≈" in out and "estimated" in out and "UTC" in out

async def test_exact_change_and_presence(mcp, trend_lt):
    out = await call(mcp, "trend", log_table="tr", templates=[T_RISE, T_DAILY, T_ONCE], start="2026-03-15", end="2026-03-29", exact=True)
    assert "+100%" in out and "14 of 14 days" in out and "1 of 14 days" in out

async def test_no_invented_new(mcp, trend_lt):
    out = await call(mcp, "trend", log_table="tr", templates=[T_DAILY], start="2026-03-01", end="2026-03-08", exact=True)
    assert "limited comparison" in out and " new" not in out.lower()

async def test_period_required(mcp, trend_lt):
    assert "which period" in (await call(mcp, "trend", log_table="tr", templates=[T_DAILY])).lower()
```

- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `git commit -m "feat: trend (#15)"`.

---

### Task 16 (#16): Read-only SQL escape hatch

**Blocked by:** #10.

**Files:** Create `src/serenedb_extractor/query/guard.py`, `tests/tools/test_run_sql.py`; modify `tools/lookup.py`, `server.py`.

**Produces:** `check_read_only` (sqlglot `read="postgres"`; exactly one statement; root `Select`, a set operation of selects, or `EXPLAIN` of one; rejects any DML/DDL node anywhere incl. data-modifying CTEs, `COPY`, `SET`, `ATTACH`, and `BLOCKED_FUNCTIONS = {"pg_cancel_backend", "pg_terminate_backend", "set_config"}`); `run_sql(ctx, sql, limit=None, timeout_s=None) -> str` (reader connection; non-EXPLAIN wrapped as `SELECT * FROM (<sql>) q LIMIT <limit+1>`; `EXPLAIN` first per spike §6 with a `decide`-style ask when over budget; table output with the cut note; rejections say "only read-only queries are allowed").

- [ ] **Step 1: Failing tests** (`@pytest.mark.db`)

```python
@pytest.mark.parametrize("ok", ["SELECT 1", "WITH a AS (SELECT 1) SELECT * FROM a", "EXPLAIN SELECT 1", "SELECT 1 UNION SELECT 2"])
async def test_allows(mcp, ok): assert "only read" not in (await call(mcp, "run_sql", sql=ok)).lower()

@pytest.mark.parametrize("bad", ["DELETE FROM extractor.templates", "SELECT 1; DROP TABLE x", "COPY extractor.templates TO '/tmp/x'",
                                 "SET threads = 1", "SELECT pg_terminate_backend(1)", "CREATE TABLE x (a int)",
                                 "WITH x AS (INSERT INTO extractor.templates DEFAULT VALUES RETURNING *) SELECT * FROM x"])
async def test_rejects(mcp, bad): assert "only read" in (await call(mcp, "run_sql", sql=bad)).lower()

async def test_cut(mcp, fx_lt): assert "showing 50 of" in await call(mcp, "run_sql", sql="SELECT * FROM extractor.lt_fx")

async def test_expensive_plan_asks(mcp, fx_lt, monkeypatch):
    monkeypatch.setattr(cost, "BUDGET_SECONDS", 0.0)
    assert "TOO EXPENSIVE" in await call(mcp, "run_sql", sql="SELECT count(*) FROM extractor.lt_fx")
```

- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `git commit -m "feat: run_sql with read-only guard (#16)"`.

---

### Task 17 (#17): Indexes

**Blocked by:** #7, #10.

**Files:** Create `src/serenedb_extractor/setup/indexes.py`, `tests/tools/test_indexes.py`; modify `tools/setup_tools.py` (offers, `create_index`), `tools/describe.py` (exact values via `ts_dict_agg`), `query/stats.py` (index flags), `tools/lookup.py` (`@@ ts_phrase`, fuzzy `ts_levenshtein`), `server.py`.

**Produces:** `IndexEstimate`, `indexes.estimate`, `indexes.build`, `create_index(ctx, log_table, kind, dry_run=False) -> str` (`destructiveHint=True`). Filter index: inverted over the present roles among timestamp, level, service, component, trace (verbatim). Search index: message with `extractor.log_dict` (spike §10) plus the filter columns. Name `<log_table>_<kind>_idx`. Estimates: trial index over `SELECT * FROM <relation> LIMIT n`, size per spike §9, scaled linearly, dropped. `inspect_source` and `setup_log_table` show both estimates when the source has ≥ 1M rows (else "small enough to search without an index"); nothing is built unless `build_*_index=True` or `create_index` without `dry_run`.

- [ ] **Step 1: Failing tests** (`@pytest.mark.db`)

```python
async def test_setup_builds_nothing_by_default(mcp, fx_path):
    await call(mcp, "setup_log_table", name="fx", source=fx_path)
    assert "indexes: none" in await call(mcp, "describe_logs", log_table="fx")

async def test_dry_run_then_build(mcp, fx_lt):
    assert "estimated" in (await call(mcp, "create_index", log_table="fx", kind="filter", dry_run=True)).lower()
    assert "indexes: none" in await call(mcp, "describe_logs", log_table="fx")
    await call(mcp, "create_index", log_table="fx", kind="filter")
    d = await call(mcp, "describe_logs", log_table="fx")
    assert "fx_filter_idx" in d and "sampled — rare values" not in d

async def test_search_index_enables_fuzzy(mcp, fx_lt):
    await call(mcp, "create_index", log_table="fx", kind="search")
    assert "disk full on" in await call(mcp, "search_logs", log_table="fx", text="dsik full", fuzzy=True)

async def test_index_lowers_cost(mcp, fx_lt, monkeypatch):
    monkeypatch.setattr(cost, "BUDGET_SECONDS", 0.001)
    fv = lambda: call(mcp, "describe_logs", log_table="fx", find_values={"role_or_column": "service", "like": "pay"})
    before = await fv()
    await call(mcp, "create_index", log_table="fx", kind="filter")
    assert "TOO EXPENSIVE" in before and "payments" in await fv()
```

- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `git commit -m "feat: index estimates, explicit builds, index-backed queries (#17)"`.

---

### Task 18 (#18): Surveys and investigations on raw logs

**Blocked by:** #8, #9, #13, #14.

**Files:** Create `tests/tools/test_raw_analysis.py`; modify what the tests expose (expected: `query/occurrence.py` for `e:` IDs on copied tables, `tools/survey.py` / `tools/trend.py` / `tools/investigate.py` for the untimestamped note).

When a survey, trend or locate has a time range and the log table has entries without a timestamp, the result adds `N entries in this log table have no timestamp and are outside any time range` (singular form for 1).

- [ ] **Step 1: Failing tests** (`@pytest.mark.db`; `bgl_lt`, `os_lt`, `app_lt` set up from the fixtures; `bgl_surveyed` adds one survey and exposes `ID_PARITY` for `instruction cache parity error corrected`)

```python
async def test_survey_raw(mcp, bgl_lt, os_lt):
    assert "instruction cache parity error corrected" in await call(mcp, "survey", log_table="bgl")
    assert "<NUM>" in await call(mcp, "survey", log_table="openstack")

async def test_exact_on_copied(mcp, bgl_surveyed):
    out = await call(mcp, "locate_occurrences", log_table="bgl", templates=[ID_PARITY], group_by=["host"])
    assert "e:" in out and "≈" not in out
    assert "≈" not in await call(mcp, "extract_params", log_table="bgl", template=ID_PARITY)

async def test_context_keeps_stacktrace(mcp, app_lt):
    occ = first_occurrence(await call(mcp, "search_logs", log_table="app", text="refund failed"))
    assert "NullPointerException" in await call(mcp, "get_context", log_table="app", occurrence=occ)

async def test_untimestamped_note(mcp, app_lt):                            # Review Focus 3
    out = await call(mcp, "survey", log_table="app", start="2026-10-17", end="2026-10-18")
    assert "1 entry in this log table has no timestamp" in out
```

- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement the fixes the tests expose. **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `git commit -m "feat: analysis on copied raw logs (#18)"`.

---

### Task 19 (#19): Prompts, server instructions, README

**Blocked by:** #11, #12, #13, #14, #15, #16, #17, #18.

**Files:** Create `src/serenedb_extractor/{instructions,prompts}.py`, `tests/tools/test_prompts.py`; modify `server.py`, `README.md`.

**Produces:** `SERVER_INSTRUCTIONS`, `ENGINEER_PROMPT`, `TEAM_LEAD_PROMPT`, `MANAGER_PROMPT`; prompts `engineer`, `team-lead`, `manager` registered with **no arguments**; `FastMCP(..., instructions=SERVER_INSTRUCTIONS)`.

Texts encode spec §1 and §9: infer log table, period and focus from the user's words; ask in plain language only for what's missing; state assumptions; start with `describe_logs`; survey before investigating; check value spellings; estimates stated with margin; never invent impact; IDs only as bracketed handles (engineer: IDs + query on request; team lead: IDs at most; manager: none); engineer workflow ending in a hypothesis plus next check; team-lead workflow with presence, change and components; manager ranking severity → trend → persistence → spread → volume, no numeric risk score, criteria stated per item, near-ties → "roughly equal" or exact counts, a closing line on what the logs do not measure, impact follow-ups answered with measured counts only. README: `uvx` install; `docker run` for SereneDB with `-v ~/logs:/logs:ro`; env vars; reader/writer role SQL; credentials via `CREATE SECRET`; `claude mcp add serenedb-extractor -e SERENEDB_READER_URL=… -- uvx serenedb-extractor`.

- [ ] **Step 1: Failing tests**

```python
async def test_twelve_tools_and_annotations(mcp_no_db):
    tools = {t.name: t for t in (await mcp_no_db.list_tools()).tools}
    assert set(tools) == {"inspect_source", "setup_log_table", "create_index", "describe_logs", "survey", "locate_occurrences",
                          "extract_params", "trend", "get_context", "search_logs", "run_sql", "rename_parameter"}
    assert tools["create_index"].annotations.destructiveHint and tools["setup_log_table"].annotations.destructiveHint
    assert tools["survey"].annotations.readOnlyHint is False and tools["trend"].annotations.readOnlyHint is True

async def test_prompts_without_arguments(mcp_no_db):
    prompts = {p.name: p for p in (await mcp_no_db.list_prompts()).prompts}
    assert set(prompts) == {"engineer", "team-lead", "manager"} and all(not p.arguments for p in prompts.values())

def test_manager_rules():
    m = MANAGER_PROMPT.lower()
    idx = [m.index(w) for w in ("severity", "trend", "persistence", "spread", "volume")]
    assert idx == sorted(idx) and "risk score" in m and "roughly equal" in m and "not measure" in m

def test_instructions():
    s = SERVER_INSTRUCTIONS.lower()
    assert all(k in s for k in ("describe_logs", "survey", "estimate", "never invent", "spelling"))
```

- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** Run the whole suite `uv run pytest -v` with `SERENEDB_TEST_URL` → PASS.
- [ ] **Step 5: Smoke test:** `claude mcp add serenedb-extractor -e SERENEDB_READER_URL=$SERENEDB_TEST_URL -- uv run --directory $(pwd) serenedb-extractor`; `/mcp` lists the 12 tools and 3 prompts.
- [ ] **Step 6:** Commit `git commit -m "feat: prompts, server instructions, README (#19)"`.
