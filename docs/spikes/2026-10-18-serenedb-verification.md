# SereneDB verification spike (issue #2)

Produced by `scripts/verify_serenedb.py` against `serenedb/serenedb:latest` (PostgreSQL 18.3 / SereneDB 26.10.1, image digest pinned in `scripts/test-db.sh`), started by `scripts/test-db.sh`. Later tasks cite sections by number.

**Evidence tags.** Every finding carries one:
- **verified by script**: the script runs it; most checks assert the outcome, but those marked "observed" print numbers that the script does not assert (checks 7 and 9 only assert that each statement ran).
- **inferred**: concluded from timings or indirect evidence; not directly tested.
- **exploratory**: seen in manual runs that `verify_serenedb.py` does not reproduce.

**Timing caveat.** Every timing is measured under amd64 emulation on an arm64 host (Colima VM, 2 CPUs, 4 GiB), marked "(emulated)", and is not representative. Remote-read timings also include S3 latency and vary between cold and warm runs (see §8). The image has no linux/arm64 manifest, so `test-db.sh` runs it with `--platform linux/amd64` (controller ruling R14).

Script verdicts: checks 1-6, 8, 10-12 assert outcomes (`PASS`); checks 7 and 9 report `RAN-OK` (no error, numbers observed). Last full run of all 12 checks (before the fix-round assertions were tightened): 12 passed with no errors. After the fix round only the local checks and the cheap EXPLAIN check 6 were re-run (all pass); the remote checks 5, 7, 8 and 9 were not repeated.

## §1 Connection defaults
- Container `sdb-test`, host port 17890 -> container 7890. `SERENEDB_TEST_URL=postgresql://postgres@localhost:17890/postgres`. **verified by script**
- Default auth: the superuser `postgres` has no password and is trusted only on loopback inside the container. Through Docker's port mapping the connection is not loopback and fails with `password authentication failed for user "postgres"`. **exploratory** (seen on the first container; the script connects to the trust-configured one). `test-db.sh` therefore starts the container with `-e SERENEDB_HOST_AUTH_METHOD=trust` (supported by the image entrypoint, **exploratory**: read from `/entrypoint.sh`) and publishes the port on `127.0.0.1` only. Test container only; for real deployments set `POSTGRES_PASSWORD`. Note: the loopback-only bind applies to containers created from now on; the currently running `sdb-test` was created earlier and still publishes on all interfaces until recreated (`docker rm -f sdb-test && bash scripts/test-db.sh`).
- `psycopg.connect(url, autocommit=True, cursor_factory=psycopg.ClientCursor)` runs `SELECT %(x)s` with `{"x": 42}` -> `[(42,)]`. **verified by script**
- A `JSON` column arrives in Python already parsed (a `dict`), not a string. **verified by script**
- Startup under emulation took seconds to well under a minute; `test-db.sh` polls `SELECT 1` for up to 4 minutes. **exploratory**

## §2 Cancelling a query
- `conn.cancel_safe()` from a `threading.Timer` raises `psycopg.errors.QueryCanceled` ("canceling statement due to user request") 1.0 s (emulated) after start for a very large cross join; the same connection then runs `SELECT 1`. **verified by script**
- It also cancelled remote Parquet scans at the 120 s, 200 s and 300 s timers. **exploratory** (manual runs; the script's check 8 only hit the 120 s case once, in an earlier version).
- **Cancel mechanism for T10: `cancel_safe` from a timer thread, no reconnect needed.** Fallback if it ever fails: close and reconnect.

## §3 DDL and DML
**verified by script.** `CREATE SCHEMA IF NOT EXISTS` (idempotent), `PRIMARY KEY` (duplicate -> `UniqueViolation`), `JSON` column, `UPDATE` (`UPDATE 1`), `DELETE` (`DELETE 1`), `DROP SCHEMA ... CASCADE` (schema gone afterwards).

## §4 SQL functions
**verified by script** (outputs compared with expected values; `any_value` and the `timestamp AT TIME ZONE` instant only checked to run): `regexp_replace(s, p, r, 'g')`, `regexp_full_match`, `regexp_extract(s, p, ['a','b'])` (a struct, a tuple in Python), `any_value`, `quantile_cont`, `date_trunc`, `count(*) FILTER (WHERE ...)`, `AT TIME ZONE`.
- `timestamptz AT TIME ZONE 'Asia/Tokyo'` returns a local `timestamp` (19:00 for 10:00 UTC). **verified by script.** `timestamp AT TIME ZONE 'Asia/Tokyo'` returns a `timestamptz` instant (shown in the session zone, UTC): **verified by script** that it runs; the PostgreSQL semantics are **inferred**.

## §5 Remote Parquet in place (core requirement: met)
`read_parquet('https://public-pme.s3.eu-west-3.amazonaws.com/text_bench/part_000.parquet', filename=true, file_row_number=true)` works inside SereneDB with no extension to install or load (**verified by script**, on a fresh server). The file was never fetched outside SereneDB.
- **File** (**verified by script**): 1,000,000,000 rows, 1,624 row groups (about 614,400 rows each), 40,991,166,725 bytes, written by ClickHouse 25.12.1. Entries are ordered by `Timestamp` (first row group starts at 2025-09-23 00:00:00 UTC; last ends about 00:29:24).
- **Columns:** `Timestamp` TIMESTAMPTZ_NS, `TimestampTime` TIMESTAMP WITH TIME ZONE, `TraceId`, `SpanId`, `SeverityText`, `ServiceName`, `Body` VARCHAR, `TraceFlags`, `SeverityNumber` UTINYINT, `ResourceAttributes`, `ScopeAttributes`, `LogAttributes` MAP(VARCHAR,VARCHAR), plus `file_row_number` BIGINT and `filename` VARCHAR. The script prints the first 12 columns (**verified by script**); the full list, including `ResourceSchemaUrl`, `ScopeSchemaUrl`, `ScopeName`, `ScopeVersion`, comes from a manual `DESCRIBE` (**exploratory**).
- **`SeverityText` is lowercase in the data**: in the 2 s window, `info` 771,915, `error` 156,150, `information` 154,268, `trace` 59,751, `warn` 1,240, `fatal` 325. **verified by script** (observed). `= 'ERROR'` returns 0 entries with no error, so the "seen: ..." hint (review focus 1) is needed. **verified by script** (asserted in check 8 only as count query success; the 0 vs non-zero contrast is observed).
- **`parquet_file_metadata(url)`**: `num_rows`, `num_row_groups`, `file_size_bytes`, `footer_size`, `created_by`, `format_version`, about 0.4 s (emulated). **verified by script**
- **`parquet_metadata(url)`** (one row per row group x column; 30,856 rows): `row_group_id`, `row_group_num_rows`, `row_group_bytes`, `path_in_schema`, `type`, `stats_min`, `stats_max`, `stats_min_value`, `stats_max_value`, `stats_null_count`, `total_compressed_size`, `total_uncompressed_size`, `compression`. **verified by script** (first 12 column names printed; the rest **exploratory**). There is **no `num_rows` column** here; use `row_group_num_rows`, or `num_rows` from `parquet_file_metadata`. Min/max stats are VARCHAR strings (e.g. `'2025-09-23 00:00:01.116880211+00'`). Nested columns appear as `LogAttributes, key_value, value`.
- **Compressed bytes per column (whole file)**, **verified by script** (top 8): `LogAttributes` values 12.5 GB, `Body` 9.1 GB, `ResourceAttributes` values 4.5 GB, `TraceId` 3.6 GB, `SpanId` 2.8 GB, `Timestamp` 2.0 GB; `SeverityText` 0.23 GB is **exploratory**.
- **psycopg gotcha** (**verified by script**): a plain `"Timestamp"` projection arrives fine (as microsecond `timestamptz`), but aggregates such as `max("Timestamp")` return nanosecond text that psycopg cannot parse (`DataError: microsecond must be in 0..999999`). Cast in SQL: `"Timestamp"::timestamptz` (or `::varchar`).

## §6 EXPLAIN (asserted)
**verified by script.**
- `EXPLAIN <query>` returns one text column `QUERY PLAN` with boxed ASCII nodes (`LIMIT`, `PROJECTION`, `FILTER`, `READ_PARQUET`, `RESERVOIR_SAMPLE`, `STREAMING_SAMPLE`, `IRESEARCH_SCAN`, ...). Each node has `~N rows` estimates (1,000,000,000 for the scan, about 200,000,000 after a filter). The plan has **no bytes, row-group counts or cost** (the script asserts none of those words appear). Row estimates are crude defaults, not statistics. T10 must compute bytes itself from `parquet_metadata`.
- **Predicate pushdown depends on the literal's type** (`Column Filter:` under `READ_PARQUET` means pushed into the scan):
  - `"Timestamp" >= timestamptz '...'` -> the column is wrapped in `CAST(Timestamp AS TIMESTAMP WITH TIME ZONE)` in a separate `FILTER` node: **not pushed down**.
  - `"Timestamp" >= '...'::timestamptz_ns` -> pushed down.
  - `"TimestampTime" >= timestamptz '...'` -> pushed down.
  - So time ranges on `Timestamp` must use `::timestamptz_ns` literals (or filter on `TimestampTime`). Never cast the column.
- That a non-pushed filter means no row-group pruning is **inferred** (see §7).

## §7 Sampling and row-group pruning (observed, not asserted)
Window used: 2 s of data (`2025-09-23 00:00:00` to `00:00:02`, 1,143,649 entries, about 2 row groups). Numbers are **verified by script** (observed) unless tagged.
- A pushed time range is fast: counting the 2 s window takes 0.4 s and a 100 ms window 0.4 s (55,982 entries) (emulated). **That this is row-group pruning (rather than just a fast scan of one or two groups) is inferred**: re-check owed by ticket #10 (cost check) with EXPLAIN / a controlled comparison.
- **Whole-file sampling reads the whole column.** `USING SAMPLE 0.01% (system)` on `Timestamp` over the whole file was cancelled after 300 s, and `reservoir(1000 ROWS)` on a real column over the whole file at 200 s (about 2 GB of compressed data to read). **exploratory** (manual runs, not in the script; the byte count is inferred from §5). Over `file_row_number` only (no column read) the reservoir takes 1 to 3 s (emulated) and is uniform (1000 entries spanning 140,091 to 997,445,086). **verified by script** (observed). Do not sample whole-file columns remotely; always bound by a time range first.
- **`USING SAMPLE` is applied before a `WHERE` in the same SELECT** (the filter is then not pushed down): `SELECT ... FROM tb WHERE <window> USING SAMPLE reservoir(1000 ROWS)` returned 1 entry in 17.6 s (emulated); it sampled 1000 entries of the whole file, then filtered. **verified by script** (observed). **Pattern that works: filter in an inner subquery, sample the subquery:** `SELECT ... FROM (SELECT * FROM tb WHERE <window>) USING SAMPLE reservoir(1000 ROWS)` -> 1000 entries in 0.35 s (emulated) spanning the whole window, filter pushed into `READ_PARQUET` (plan seen in EXPLAIN, **exploratory**).
- `system 1%` inside the window returned 10,240 entries in 0.43 s (emulated), `reservoir(1000 ROWS)` exactly 1000 in 0.35 s. **verified by script** (observed). That `system` works in vector-sized chunks, so granularity is coarse and entries are not independent, is **inferred**. Prefer `reservoir(N ROWS)` for exact sizes.

## §8 Filter first or sample first (decision: filter-first)
All inside the 2 s window (`SeverityText` lowercase). Timings are (emulated). Numbers are **verified by script** (observed) unless tagged.
- `count("SeverityText")`: 0.5 s, 1,143,649 entries.
- Filter `= 'error'` then `reservoir(1000)` of `Body`, written `FROM (SELECT * FROM tb WHERE <window> AND "SeverityText" = 'error') USING SAMPLE reservoir(1000 ROWS)`: 0.5 s, 1000 entries (156,150 matching entries exist). That `Body` is read only for the sampled/matching entries (late materialization) is **inferred** from the cost being about the same as reading `SeverityText` alone: re-check owed by ticket #10 (cost check) with EXPLAIN / a controlled comparison.
- Sample-first (reservoir of the window, then filter `error`): 0.4 s, 142 of 1000 sampled entries matched (121 to 143 across runs). That rare levels (`fatal`, 325 of 1,000,000 indexed entries in §9, about 0.03%) would then have almost no sampled hits is **inferred** (arithmetic from these counts, not tested).
- **Decision: filter-first.** Put level/service/time filters in the inner subquery, then `USING SAMPLE reservoir(N ROWS)`. It costs no more here and gives a full-size sample of the filtered population (the estimate scales from the filtered count, which a cheap `count(*)` gives exactly). The decision rests on the verified timings plus the inferred late-materialization claim; ticket #10's re-check can overturn the cost half but not the sample-size half.
- **Variance warning (exploratory):** in one earlier run the same `= 'error'` filter over this window did not finish within 120 s (cancelled), and later ran in 0.4 s; a 100 ms window took 11.7 s once and 1.3 s on repeat. Cause not isolated (S3 cold reads and the emulated CPU are likely). Cost model constants for remote reads must allow large cold/warm variance, and every remote query needs a timeout.

## §9 Inverted index over a view (observed, not asserted)
Numbers are **verified by script** (observed); every statement is asserted to run.
- `CREATE VIEW ... AS SELECT "Timestamp"::timestamptz AS ts, "SeverityText" AS sev, "Body" AS body FROM read_parquet(url, filename=true, file_row_number=true) LIMIT 1000000`, then `CREATE INDEX tb_idx ON <view> USING inverted(body extractor.log_dict, sev)`: build time **3.2 s** (emulated) for 1,000,000 entries (the first 2 row groups; includes the cold remote read).
- **Size on disk:** `SELECT pg_relation_size('extractor.tb_idx')` -> 21,785,501 bytes (20.7 MiB, about 22 bytes per entry). `pg_indexes_size('<view>')` returns 0 for views, so use `pg_relation_size(index)`.
- After `VACUUM (REFRESH_INDEX) extractor.tb_idx`, `SELECT count(*) FROM extractor.tb_idx` -> 1,000,000. (Whether the count would already be 1,000,000 without the refresh is **not tested**.)
- **Query the index by name** (`FROM extractor.tb_idx`), not the view. `ts_dict_agg` on the view fails: `ts_dict_agg() requires an inverted index scan in the same sub-query`.
- `SELECT unnest(ts_dict_agg(body)) AS t, unnest(ts_dict_count(body)) AS c FROM extractor.tb_idx` lists terms with document counts (top: `with` 278,037, `called` 276,411, `userid` 276,409, `info` 242,727). The same on the verbatim `sev` column returns exact value counts (`info` 674,541, `information` 136,177, `error` 135,163, `trace` 52,710, `warn` 1,084, `fatal` 325), a cheap way to list seen values for the review-focus-1 hint.
- `DROP INDEX extractor.tb_idx` works. A `LIMIT` in the view body is accepted and the index builds.

## §10 Text search dictionary and queries
**verified by script** (asserted: the phrase and Levenshtein counts of 100 of 300 entries).
- `CREATE TEXT SEARCH DICTIONARY extractor.log_dict AS split_text(case := 'lower') | normalize_tokens('en_US.UTF-8', accent := false) WITH (frequency, position)` works. `ts_lexize('extractor.log_dict', 'Connection REFUSED to 10.0.7.21:5432 café')` -> `['connection','refused','to','10.0.7.21','5432','cafe']`: dotted IPs stay whole, `host:port` splits on the colon.
- `@@ ts_phrase('connection refused')` and `@@ ts_levenshtein('conection', 2)` work on the **index relation** (`FROM extractor.d_idx WHERE body @@ ...`). On the base table they fail with `TSQUERY expression evaluated outside an '@@' match against an inverted-indexed column`. `EXPLAIN` on the index relation shows `IRESEARCH_SCAN`, while a base-table `ILIKE` does not use the index (printed, not asserted).
- `VACUUM (REFRESH_TABLE) <table>` before querying: the script issues it before every index query. That it is *required* for just-inserted entries (otherwise about 1 s background refresh) is from the docs and **not tested here**.

## §11 COPY to Parquet inside the container
**verified by script** (asserted: 1000 entries, `file_row_number` 0..999). `COPY (SELECT ...) TO '/tmp/x.parquet' (FORMAT PARQUET)` works (`COPY 1000`) and `read_parquet('/tmp/x.parquet', filename=true, file_row_number=true)` reads it back. The path is inside the SereneDB container, so `container_parquet()` in tests must use container paths and cannot read them from the host.

## §12 Streaming COPY
**verified by script** (asserted: 20,000 entries stored). `cursor.copy("COPY t (cols) FROM STDIN")` with `copy.write_row(...)`: 20,000 entries in 0.06 s (emulated), including a message with a tab, double quotes and a comma (round-trips intact), a `TIMESTAMPTZ` string and a JSON string.

## Operational notes for later tasks
- Test URL for every task: `export SERENEDB_TEST_URL=postgresql://postgres@localhost:17890/postgres` (printed by `bash scripts/test-db.sh`). The container `sdb-test` is left running.
- The script drops and recreates schemas `extractor` and `spike3`; it refuses to run against anything but `localhost:17890` unless `VERIFY_ALLOW_DESTRUCTIVE=1` is set.
- Remote queries on the TextBench file share one 2 CPU / 4 GiB VM; keep them bounded by a time window and a cancel timer.
- psycopg returns `JSON` as dict/list and `TIMESTAMPTZ` as aware UTC datetimes. **verified by script**
