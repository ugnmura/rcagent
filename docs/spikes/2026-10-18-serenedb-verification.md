# SereneDB verification spike (issue #2)

Produced by `scripts/verify_serenedb.py` against `serenedb/serenedb:latest` (PostgreSQL 18.3 / SereneDB 26.10.1), started by `scripts/test-db.sh`.
Result: **12 of 12 checks pass**. Later tasks cite sections by number.

**Timing caveat:** every timing below was measured under amd64 emulation on an arm64 host (Colima VM, 2 CPUs, 4 GiB) and is not representative of real hardware. Remote-read timings also include S3 latency from this machine and vary a lot between cold and warm runs (see §8).

The image has no linux/arm64 manifest, so `test-db.sh` runs it with `--platform linux/amd64` (controller ruling R14).

## §1 Connection defaults
- Container `sdb-test`, host port 17890 -> container 7890. `SERENEDB_TEST_URL=postgresql://postgres@localhost:17890/postgres`.
- Default auth: the superuser `postgres` has no password and is trusted only on loopback inside the container. Through Docker's port mapping the connection is not loopback, so it fails with `password authentication failed for user "postgres"`. `test-db.sh` therefore starts the container with `-e SERENEDB_HOST_AUTH_METHOD=trust` (supported by the image entrypoint), which allows passwordless connections. Test container only; never for real deployments (set `POSTGRES_PASSWORD` there).
- `psycopg.connect(url, autocommit=True, cursor_factory=psycopg.ClientCursor)` runs `SELECT %(x)s` with `{"x": 42}` -> `[(42,)]`.
- The JSON type arrives in Python already parsed (a `dict`), not as a string.
- Cold start under emulation took well under a minute; `test-db.sh` polls `SELECT 1` for up to 4 minutes.

## §2 Cancelling a query
- `conn.cancel_safe()` from a `threading.Timer` raises `psycopg.errors.QueryCanceled` ("canceling statement due to user request") in the main thread, 1.0 s after start for a 1e14-row cross join. The same connection then runs `SELECT 1` fine.
- It also cancelled remote Parquet scans (observed at 120 s, 200 s and 300 s timers). **Cancel mechanism for T10: `cancel_safe` from a timer thread; no reconnect needed.** (Fallback if it ever fails: close and reconnect.)

## §3 DDL and DML
All work: `CREATE SCHEMA IF NOT EXISTS` (idempotent), `PRIMARY KEY` (duplicate -> `UniqueViolation`), `JSON` column, `UPDATE`, `DELETE`, `DROP SCHEMA ... CASCADE` (schema is gone afterwards). `UPDATE`/`DELETE` status messages are `UPDATE 1` / `DELETE 1`.

## §4 SQL functions
All run as written: `regexp_replace(s, p, r, 'g')`, `regexp_full_match`, `regexp_extract(s, p, ['a','b'])` (returns a struct, a tuple in Python), `any_value`, `quantile_cont`, `date_trunc`, `count(*) FILTER (WHERE ...)`, `AT TIME ZONE`.
- `timestamp AT TIME ZONE 'Asia/Tokyo'` returns a `timestamptz` (the instant, shown in the session zone, UTC); `timestamptz AT TIME ZONE 'Asia/Tokyo'` returns a local `timestamp`. Same as PostgreSQL.

## §5 Remote Parquet in place (core requirement: met)
`read_parquet('https://public-pme.s3.eu-west-3.amazonaws.com/text_bench/part_000.parquet', filename=true, file_row_number=true)` works inside SereneDB with no extension to install or load. The file was never fetched outside SereneDB.
- **File:** 1,000,000,000 rows, 1,624 row groups (about 614,400 rows each), 40,991,166,725 bytes, written by ClickHouse 25.12.1. Rows are ordered by `Timestamp` (2025-09-23 00:00:00 to about 00:29:24 UTC).
- **Columns:** `Timestamp` TIMESTAMPTZ_NS, `TimestampTime` TIMESTAMP WITH TIME ZONE, `TraceId`, `SpanId` VARCHAR, `TraceFlags` UTINYINT, `SeverityText` VARCHAR, `SeverityNumber` UTINYINT, `ServiceName`, `Body` VARCHAR, `ResourceSchemaUrl`, `ResourceAttributes` MAP(VARCHAR,VARCHAR), `ScopeSchemaUrl`, `ScopeName`, `ScopeVersion`, `ScopeAttributes` MAP, `LogAttributes` MAP, plus `file_row_number` BIGINT and `filename` VARCHAR.
- **`SeverityText` is lowercase in the data**: `info`, `error`, `information`, `trace`, `warn`, `fatal`. Filtering `= 'ERROR'` returns 0 rows with no error, so the "seen: ..." hint (review focus 1) is needed.
- **`parquet_file_metadata(url)`**: `num_rows`, `num_row_groups`, `file_size_bytes`, `footer_size`, `created_by`, `format_version`. About 0.4 s.
- **`parquet_metadata(url)`** (one row per row group x column; 30,856 rows here): `row_group_id`, `row_group_num_rows`, `row_group_bytes`, `row_group_compressed_bytes`, `path_in_schema`, `type`, `stats_min`, `stats_max`, `stats_min_value`, `stats_max_value`, `stats_null_count`, `total_compressed_size`, `total_uncompressed_size`, `compression`, `data_page_offset`, ... There is **no `num_rows` column** here; use `row_group_num_rows` per row group, or `num_rows` from `parquet_file_metadata`. Min/max stats are VARCHAR strings (e.g. `'2025-09-23 00:00:01.116880211+00'`). Nested columns appear as `LogAttributes, key_value, value`. Reading it takes under 1 s.
- **Compressed bytes per column (whole file):** `LogAttributes` values 12.5 GB, `Body` 9.1 GB, `ResourceAttributes` values 4.5 GB, `TraceId` 3.6 GB, `SpanId` 2.8 GB, `Timestamp` 2.0 GB, `SeverityText` 0.23 GB.
- **psycopg gotcha:** a plain `"Timestamp"` projection arrives fine (as microsecond `timestamptz`), but aggregates such as `max("Timestamp")` return nanosecond text that psycopg cannot parse (`DataError: microsecond must be in 0..999999`). Cast in SQL: `"Timestamp"::timestamptz` (or `::varchar`).

## §6 EXPLAIN
- `EXPLAIN <query>` returns one text column `QUERY PLAN` with boxed ASCII nodes (`LIMIT`, `PROJECTION`, `FILTER`, `READ_PARQUET`, `RESERVOIR_SAMPLE`, `STREAMING_SAMPLE`, `IRESEARCH_SCAN`, ...). Each node has `~N rows` estimates (1,000,000,000 for the full scan, about 200,000,000 after a filter). **No bytes, no row-group counts, no cost.** Row estimates are crude defaults, not statistics. T10 must compute bytes itself from `parquet_metadata`.
- **Predicate pushdown depends on the literal's type.** Plan node `READ_PARQUET` shows `Column Filter:` when the filter is pushed into the scan.
  - `"Timestamp" >= timestamptz '...'` -> the engine wraps the column in `CAST(Timestamp AS TIMESTAMP WITH TIME ZONE)` in a separate `FILTER` node: **not pushed down, no row-group pruning.**
  - `"Timestamp" >= '...'::timestamptz_ns` -> pushed down.
  - `"TimestampTime" >= timestamptz '...'` -> pushed down.
  - So time ranges on `Timestamp` must use `::timestamptz_ns` literals (or filter on `TimestampTime`). Never cast the column.

## §7 Sampling and row-group pruning
Window used: 2 s of data (`2025-09-23 00:00:00` to `00:00:02`, 1,143,649 rows, about 2 row groups).
- A pushed time range prunes row groups: counting the 2 s window takes 0.4 s, a 100 ms window 0.4 s (55,982 rows), versus minutes for a whole-file column scan.
- **Whole-file sampling reads the whole column.** `USING SAMPLE 0.01% (system)` on `Timestamp` over the whole file was cancelled after 300 s (about 2 GB of compressed data to read). `USING SAMPLE reservoir(1000 ROWS)` on a real column over the whole file was cancelled at 200 s. Over `file_row_number` only (no column read) it takes 1 to 3 s and is uniform (1000 rows spanning 140,091 to 997,445,086). Do not sample whole-file columns remotely; always bound by a time range first.
- **`USING SAMPLE` is applied before a `WHERE` in the same SELECT** (and the filter is then not pushed down): `SELECT ... FROM tb WHERE <window> USING SAMPLE reservoir(1000 ROWS)` returned 1 row in 17.6 s (it sampled 1000 rows of the whole file, then filtered). **Pattern that works: put the filter in an inner subquery and sample the subquery:** `SELECT ... FROM (SELECT * FROM tb WHERE <window>) USING SAMPLE reservoir(1000 ROWS)` -> 1000 rows in 0.35 s, spanning the whole window, filter pushed into `READ_PARQUET`.
- `system` vs `reservoir` inside the window: `system 1%` returned 10,240 rows in 0.43 s (vector-sized chunks, so granularity is coarse: not exact and not independent rows); `reservoir(1000 ROWS)` returned exactly 1000 rows in 0.35 s. Prefer `reservoir(N ROWS)` for exact sizes.

## §8 Filter first or sample first (decision: filter-first)
All inside the 2 s window, `SeverityText` lowercase:
- Selecting only `SeverityText` (`count("SeverityText")`): 0.5 s, 1,143,649 rows.
- Filter `= 'error'` then `reservoir(1000)` of `Body`, written as `FROM (SELECT * FROM tb WHERE <window> AND "SeverityText" = 'error') USING SAMPLE reservoir(1000 ROWS)`: 0.5 s, 1000 rows (156,150 matching rows exist). `Body` is not read for non-matching rows (late materialization), so the cost is about the same as reading `SeverityText` alone.
- Sample-first (reservoir of the window, then filter `error`): 0.4 s, but only 142 of 1000 sampled rows matched, so rare levels (`fatal` is 0.03%) would have almost no sampled hits.
- **Decision: filter-first.** Put level/service/time filters in the inner subquery, then `USING SAMPLE reservoir(N ROWS)`. It costs no more and gives a full-size sample of the filtered population (the estimate then scales from the filtered count, which is exact from a cheap `count(*)`).
- **Variance warning:** in one run the same `= 'error'` filter over this window did not finish within 120 s (cancelled), and later ran in 0.4 s; a 100 ms window took 11.7 s once and 1.3 s on repeat. Cause not isolated (S3 cold reads and the emulated CPU are likely). Cost model constants for remote reads must allow large cold/warm variance, and every remote query needs a timeout.

## §9 Inverted index over a view
- `CREATE VIEW ... AS SELECT "Timestamp"::timestamptz AS ts, "SeverityText" AS sev, "Body" AS body FROM read_parquet(url, filename=true, file_row_number=true) LIMIT 1000000` followed by `CREATE INDEX tb_idx ON <view> USING inverted(body extractor.log_dict, sev)` works. Build time **3.2 s** for 1,000,000 rows (first 2 row groups; emulated; cold remote read included).
- **Size on disk:** `SELECT pg_relation_size('extractor.tb_idx')` -> 21,785,501 bytes (20.7 MiB, about 22 bytes per row for `Body` with the dictionary plus `sev` verbatim). `pg_indexes_size('<view>')` returns 0 for views, so use `pg_relation_size(index)`. `pg_indexes` also lists the index with its full `WITH` options.
- After `VACUUM (REFRESH_INDEX) extractor.tb_idx`, `SELECT count(*) FROM extractor.tb_idx` -> 1,000,000.
- **Query the index by name** (`FROM extractor.tb_idx`), not the view. `ts_dict_agg` on the view fails: `ts_dict_agg() requires an inverted index scan in the same sub-query`.
- `SELECT unnest(ts_dict_agg(body)) AS t, unnest(ts_dict_count(body)) AS c FROM extractor.tb_idx` lists terms with document counts (top: `with` 278,037, `called` 276,411, `userid` 276,409, `info` 242,727). The same on the verbatim `sev` column returns exact value counts (`info` 674,541, `information` 136,177, `error` 135,163, `trace` 52,710, `warn` 1,084, `fatal` 325), a cheap way to list seen values for the review-focus-1 hint.
- `DROP INDEX extractor.tb_idx` works.
- A `LIMIT` inside the view body is accepted (the view is then a "generic" or limited source, still indexed fine here).

## §10 Text search dictionary and queries
- `CREATE TEXT SEARCH DICTIONARY extractor.log_dict AS split_text(case := 'lower') | normalize_tokens('en_US.UTF-8', accent := false) WITH (frequency, position)` works. `ts_lexize('extractor.log_dict', 'Connection REFUSED to 10.0.7.21:5432 café')` -> `['connection','refused','to','10.0.7.21','5432','cafe']`: dotted IPs stay whole, `host:port` splits on the colon.
- `@@ ts_phrase('connection refused')` and `@@ ts_levenshtein('conection', 2)` both work on the **index relation** (`FROM extractor.d_idx WHERE body @@ ...`) and returned the expected 100 of 300 rows. On the base table they fail: `TSQUERY expression evaluated outside an '@@' match against an inverted-indexed column`. A plain `ILIKE` on the base table does not use the index.
- `EXPLAIN` on the index relation shows `IRESEARCH_SCAN` with `Index: <name>`, the phrase parts, and `Output: row-count only` when only `count(*)` is needed.
- `VACUUM (REFRESH_TABLE) <table>` makes just-inserted rows searchable immediately (otherwise about 1 s background refresh).

## §11 COPY to Parquet inside the container
`COPY (SELECT ...) TO '/tmp/x.parquet' (FORMAT PARQUET)` works (status `COPY 1000`), and `read_parquet('/tmp/x.parquet', filename=true, file_row_number=true)` reads it back with `file_row_number` starting at 0. The path is inside the SereneDB container, so `container_parquet()` in tests must use container paths and cannot read them from the host.

## §12 Streaming COPY
`cursor.copy("COPY t (cols) FROM STDIN")` with `copy.write_row(...)` works: 20,000 rows in 0.06 s, including a message with a tab, double quotes and a comma (round-trips intact), a `TIMESTAMPTZ` string and a JSON string.

## Operational notes for later tasks
- Test URL for every task: `export SERENEDB_TEST_URL=postgresql://postgres@localhost:17890/postgres` (printed by `bash scripts/test-db.sh`). The container `sdb-test` is left running.
- Remote queries on the TextBench file share one 2 CPU / 4 GiB VM; keep them bounded by a time window and a cancel timer.
- Python 3.12 psycopg returns `JSON` as dict/list, `TIMESTAMPTZ` as aware datetimes in UTC (session zone), `regexp_extract` struct as tuple.
