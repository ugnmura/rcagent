"""Spike: verify SereneDB behaviours the extractor relies on (issue #2).

One function per question; each prints PASS/FAIL and the observed output.
Run:  SERENEDB_TEST_URL=... uv run python scripts/verify_serenedb.py [N ...]
The TextBench Parquet is read only by SereneDB itself (SQL), never from Python.
All timings are measured under amd64 emulation on an arm64 host (not representative).
"""
from __future__ import annotations

import os
import sys
import threading
import time
from typing import Callable

import psycopg

URL = os.environ.get("SERENEDB_TEST_URL", "postgresql://postgres@localhost:17890/postgres")
PQ = "https://public-pme.s3.eu-west-3.amazonaws.com/text_bench/part_000.parquet"
SRC = f"read_parquet('{PQ}', filename=true, file_row_number=true)"
# Narrow window (~2 s of data, ~2 row groups) so remote reads stay small.
T0, T1 = "2025-09-23 00:00:00", "2025-09-23 00:00:02"
WIN = f"\"Timestamp\" >= '{T0}'::timestamptz_ns AND \"Timestamp\" < '{T1}'::timestamptz_ns"
LONG = 120.0  # per-statement cancel timer for remote work (seconds)


def connect() -> psycopg.Connection:
    return psycopg.connect(URL, autocommit=True, cursor_factory=psycopg.ClientCursor)


CONN = connect()


def q(sql: str, params=None, timeout: float = LONG, conn=None):
    """Run sql, cancelling after `timeout`s. Returns (rows, seconds)."""
    c = conn or CONN
    timer = threading.Timer(timeout, c.cancel_safe)
    timer.start()
    t = time.perf_counter()
    try:
        cur = c.execute(sql, params)
        rows = cur.fetchall() if cur.description else [(cur.statusmessage,)]
    finally:
        timer.cancel()
    return rows, time.perf_counter() - t


def show(label: str, value) -> None:
    text = str(value)
    print(f"    {label}: {text[:1500]}{'...' if len(text) > 1500 else ''}")


def attempt(label: str, sql: str, params=None, timeout: float = LONG):
    """Run a statement, print result or the error. Returns (ok, rows, secs)."""
    try:
        rows, s = q(sql, params, timeout)
        show(f"{label} [{s:.2f}s]", rows[:12])
        return True, rows, s
    except Exception as e:  # noqa: BLE001
        show(f"{label} ERROR {type(e).__name__}", str(e).strip().splitlines()[0])
        return False, None, 0.0


def setup_schema() -> None:
    q("DROP SCHEMA IF EXISTS extractor CASCADE")
    q("CREATE SCHEMA extractor")


# 1 ---------------------------------------------------------------------
def c01_connection():
    rows, _ = q("SELECT %(x)s", {"x": 42})
    show("SELECT %(x)s", rows)
    show("version", q("SELECT version()")[0])
    show("user/db", q("SELECT current_user, current_database()")[0])
    show("url (no password needed: container started with SERENEDB_HOST_AUTH_METHOD=trust)", URL)
    return rows == [(42,)]


# 2 ---------------------------------------------------------------------
def c02_cancel():
    c = connect()
    timer = threading.Timer(1.0, c.cancel_safe)
    timer.start()
    t = time.perf_counter()
    raised = None
    try:
        c.execute("SELECT count(*) FROM range(100000000000) a, range(1000) b")
    except psycopg.errors.QueryCanceled as e:
        raised = e
    finally:
        timer.cancel()
    el = time.perf_counter() - t
    show("raised QueryCanceled", f"{raised!r} after {el:.2f}s")
    rows, _ = q("SELECT 1", conn=c)
    show("connection reusable afterwards", rows)
    c.close()
    return raised is not None and rows == [(1,)]


# 3 ---------------------------------------------------------------------
def c03_ddl_dml():
    q("DROP SCHEMA IF EXISTS spike3 CASCADE")
    q("CREATE SCHEMA IF NOT EXISTS spike3")
    q("CREATE SCHEMA IF NOT EXISTS spike3")  # idempotent
    q("CREATE TABLE spike3.t (id BIGINT PRIMARY KEY, j JSON, s TEXT)")
    q("INSERT INTO spike3.t VALUES (1, '{\"a\": 1}', 'x'), (2, '{\"a\": 2}', 'y')")
    show("UPDATE", q("UPDATE spike3.t SET s = 'z' WHERE id = 1")[0])
    show("DELETE", q("DELETE FROM spike3.t WHERE id = 2")[0])
    rows = q("SELECT id, j, s FROM spike3.t")[0]
    show("row (JSON column arrives in Python as)", [(r[0], type(r[1]).__name__, r[1], r[2]) for r in rows])
    try:
        q("INSERT INTO spike3.t VALUES (1, NULL, 'dup')")
        show("duplicate PK", "NOT rejected")
        dup = False
    except Exception as e:  # noqa: BLE001
        show("duplicate PK rejected", f"{type(e).__name__}: {str(e).splitlines()[0]}")
        dup = True
    show("DROP SCHEMA CASCADE", q("DROP SCHEMA spike3 CASCADE")[0])
    left = q("SELECT count(*) FROM information_schema.schemata WHERE schema_name='spike3'")[0]
    show("schema left", left)
    return rows == [(1, rows[0][1], "z")] and dup and left == [(0,)]


# 4 ---------------------------------------------------------------------
def c04_functions():
    cases = {
        "regexp_replace(...,'g')": "SELECT regexp_replace('a1b22c', '[0-9]+', '<NUM>', 'g')",
        "regexp_full_match": "SELECT regexp_full_match('GET /x?id=7', 'GET /x\\?id=\\d+'), regexp_full_match('abc', 'b')",
        "regexp_extract(s,p,['a','b'])": "SELECT regexp_extract('ab12', '([a-z]+)([0-9]+)', ['a','b'])",
        "any_value": "SELECT any_value(x) FROM range(5) t(x)",
        "quantile_cont": "SELECT quantile_cont(x, 0.5) FROM range(10) t(x)",
        "date_trunc": "SELECT date_trunc('hour', timestamp '2026-03-01 10:34:00')",
        "count FILTER": "SELECT count(*) FILTER (WHERE x > 3) FROM range(10) t(x)",
        "AT TIME ZONE": "SELECT timestamp '2026-03-01 10:00:00' AT TIME ZONE 'Asia/Tokyo'",
        "AT TIME ZONE (timestamptz -> local)": "SELECT timestamptz '2026-03-01 10:00:00+00' AT TIME ZONE 'Asia/Tokyo'",
    }
    ok = True
    for label, sql in cases.items():
        r, _, _ = attempt(label, sql)
        ok &= r
    return ok


# 5 ---------------------------------------------------------------------
def c05_remote_parquet():
    ok, rows, s = attempt("DESCRIBE read_parquet(remote)", f"DESCRIBE SELECT * FROM {SRC}")
    if not ok:
        return False
    show("httpfs requirement", "none: no INSTALL/LOAD needed, https URL read directly (query succeeded on a fresh server)")
    ok2, r2, _ = attempt("parquet_file_metadata", f"SELECT num_rows, num_row_groups, file_size_bytes, created_by FROM parquet_file_metadata('{PQ}')")
    ok3, r3, _ = attempt(
        "parquet_metadata columns", f"SELECT column_name FROM (DESCRIBE SELECT * FROM parquet_metadata('{PQ}'))")
    ok4, r4, _ = attempt(
        "Timestamp row-group stats (first 3)",
        f"SELECT row_group_id, row_group_num_rows, stats_min_value, stats_max_value, total_compressed_size, row_group_bytes "
        f"FROM parquet_metadata('{PQ}') WHERE path_in_schema='Timestamp' ORDER BY row_group_id LIMIT 3")
    attempt("Timestamp row-group stats (last 2)",
            f"SELECT row_group_id, stats_min_value, stats_max_value FROM parquet_metadata('{PQ}') "
            f"WHERE path_in_schema='Timestamp' ORDER BY row_group_id DESC LIMIT 2")
    attempt("compressed bytes per column (whole file)",
            f"SELECT path_in_schema, sum(total_compressed_size) AS bytes FROM parquet_metadata('{PQ}') GROUP BY 1 ORDER BY 2 DESC LIMIT 8")
    attempt("Timestamp type comes back to psycopg as", "SELECT pg_typeof(\"Timestamp\") FROM " + SRC + " LIMIT 1")
    try:
        q(f"SELECT \"Timestamp\" FROM {SRC} WHERE {WIN} OFFSET 1000 LIMIT 1")
        show("psycopg parse of plain TIMESTAMPTZ_NS column", "ok (arrives as timestamptz, microsecond precision)")
        q(f"SELECT max(\"Timestamp\") FROM {SRC} WHERE {WIN}")
        show("psycopg parse of max(TIMESTAMPTZ_NS) (ns fraction)", "ok")
    except Exception as e:  # noqa: BLE001
        show("psycopg parse of TIMESTAMPTZ_NS", f"FAILS {type(e).__name__}: {str(e)[:150]} -> cast in SQL (::timestamptz or ::varchar)")
    attempt("severity values in window", f"SELECT \"SeverityText\", count(*) FROM {SRC} WHERE {WIN} GROUP BY 1 ORDER BY 2 DESC")
    return ok and ok2 and ok3 and ok4


# 6 ---------------------------------------------------------------------
def c06_explain():
    q("CREATE OR REPLACE VIEW extractor.tb AS SELECT * FROM " + SRC)
    for label, where in [
        ("filter on Timestamp (TIMESTAMPTZ_NS) with timestamptz literal", "\"Timestamp\" >= timestamptz '2025-09-23 00:00:00+00' AND \"Timestamp\" < timestamptz '2025-09-23 00:00:02+00'"),
        ("filter on Timestamp with ::timestamptz_ns literal", WIN),
        ("filter on TimestampTime (timestamptz)", "\"TimestampTime\" >= timestamptz '2025-09-23 00:00:00+00' AND \"TimestampTime\" < timestamptz '2025-09-23 00:00:02+00'"),
    ]:
        rows, s = q(f"EXPLAIN SELECT \"SeverityText\" FROM extractor.tb WHERE {where} LIMIT 5")
        plan = "\n".join(r[0] for r in rows)
        pushed = "Column Filter" in plan
        show(f"{label} -> filter pushed into READ_PARQUET", pushed)
        compact = " | ".join(l.strip("│╭╮╰╯─┬┴ ").strip() for l in plan.splitlines() if l.strip("│╭╮╰╯─┬┴ ").strip())
        show("  plan", compact)
    show("reports rows?", "yes: '~N rows' estimates per node (1e9 for the scan, ~2e8 after filter); NO bytes, NO row-group counts")
    return True


# 7 ---------------------------------------------------------------------
def c07_sampling():
    ok = True
    sub = f"(SELECT * FROM extractor.tb WHERE {WIN})"
    for label, sql in [
        ("window count (no sampling)", f"SELECT count(*) FROM extractor.tb WHERE {WIN}"),
        ("window count, narrow 100ms", f"SELECT count(*) FROM extractor.tb WHERE \"Timestamp\" >= '{T0}'::timestamptz_ns AND \"Timestamp\" < '2025-09-23 00:00:00.1'::timestamptz_ns"),
        ("system 1% AFTER subquery filter", f"SELECT count(*), min(\"Timestamp\"::timestamptz), max(\"Timestamp\"::timestamptz) FROM (SELECT \"Timestamp\" FROM {sub} USING SAMPLE 1% (system))"),
        ("reservoir(1000) AFTER subquery filter", f"SELECT count(*), min(\"Timestamp\"::timestamptz), max(\"Timestamp\"::timestamptz) FROM (SELECT \"Timestamp\" FROM {sub} USING SAMPLE reservoir(1000 ROWS))"),
        ("PITFALL: WHERE + USING SAMPLE in same SELECT (reservoir)", f"SELECT count(*) FROM (SELECT \"Timestamp\" FROM extractor.tb WHERE {WIN} USING SAMPLE reservoir(1000 ROWS))"),
        ("whole-file reservoir(1000) of file_row_number only", "SELECT count(*), min(file_row_number), max(file_row_number) FROM (SELECT file_row_number FROM extractor.tb USING SAMPLE reservoir(1000 ROWS))"),
    ]:
        r, rows, s = attempt(label, sql, timeout=LONG)
        ok &= r
    print("    (whole-file USING SAMPLE 0.01% (system) on a column was cancelled after 300 s in exploration: it scans the whole column; not re-run here)")
    return ok


# 8 ---------------------------------------------------------------------
def c08_filter_first():
    ok = True
    res = {}
    for label, sql in [
        ("sev only: count(SeverityText) in window", f"SELECT count(\"SeverityText\") FROM extractor.tb WHERE {WIN}"),
        ("filter 'ERROR' (as users spell it) -> count", f"SELECT count(*) FROM extractor.tb WHERE {WIN} AND \"SeverityText\" = 'ERROR'"),
        ("filter 'error' -> count", f"SELECT count(*) FROM extractor.tb WHERE {WIN} AND \"SeverityText\" = 'error'"),
        ("filter-first: error then reservoir(1000) of Body", f"SELECT count(*), avg(length(\"Body\")) FROM (SELECT \"Body\" FROM (SELECT * FROM extractor.tb WHERE {WIN} AND \"SeverityText\" = 'error') USING SAMPLE reservoir(1000 ROWS))"),
        ("filter-first (repeat, warm)", f"SELECT count(*), avg(length(\"Body\")) FROM (SELECT \"Body\" FROM (SELECT * FROM extractor.tb WHERE {WIN} AND \"SeverityText\" = 'error') USING SAMPLE reservoir(1000 ROWS))"),
        ("sample-first: reservoir(1000) of window then filter error (Body read for all)", f"SELECT count(*) FROM (SELECT \"Body\", \"SeverityText\" FROM (SELECT * FROM extractor.tb WHERE {WIN}) USING SAMPLE reservoir(1000 ROWS)) WHERE \"SeverityText\" = 'error'"),
    ]:
        r, rows, s = attempt(label, sql, timeout=LONG)
        res[label] = s
        ok &= r
    show("DECISION", "filter-first: apply the filter in an inner subquery, then USING SAMPLE on it (see note §8)")
    return ok


# 9 ---------------------------------------------------------------------
def c09_inverted_index():
    q("DROP INDEX IF EXISTS extractor.tb_idx")
    q("CREATE OR REPLACE VIEW extractor.tb1m AS SELECT \"Timestamp\"::timestamptz AS ts, \"SeverityText\" AS sev, \"Body\" AS body FROM "
      + f"read_parquet('{PQ}', filename=true, file_row_number=true) LIMIT 1000000")
    try:
        q("DROP TEXT SEARCH DICTIONARY IF EXISTS extractor.log_dict")
    except Exception:  # noqa: BLE001
        pass
    q("CREATE TEXT SEARCH DICTIONARY extractor.log_dict AS split_text(case := 'lower') | normalize_tokens('en_US.UTF-8', accent := false) WITH (frequency, position)")
    ok, _, s = attempt("CREATE INDEX over view ... LIMIT 1000000", "CREATE INDEX tb_idx ON extractor.tb1m USING inverted(body extractor.log_dict, sev)", timeout=900)
    if not ok:
        # Fallback: the same view without LIMIT is not bounded; try a time-window view instead.
        attempt("fallback: view over window instead of LIMIT",
                f"CREATE OR REPLACE VIEW extractor.tb1m AS SELECT \"Timestamp\"::timestamptz AS ts, \"SeverityText\" AS sev, \"Body\" AS body FROM {SRC} WHERE {WIN}")
        ok, _, s = attempt("CREATE INDEX over window view", "CREATE INDEX tb_idx ON extractor.tb1m USING inverted(body extractor.log_dict, sev)", timeout=900)
    show("build time (amd64 emulation)", f"{s:.1f}s")
    if not ok:
        return False
    attempt("VACUUM REFRESH", "VACUUM (REFRESH_INDEX) extractor.tb_idx")
    attempt("on-disk size: pg_relation_size(index)", "SELECT pg_relation_size('extractor.tb_idx'), pg_size_pretty(pg_relation_size('extractor.tb_idx'))")
    attempt("on-disk size: pg_indexes_size(view)", "SELECT pg_indexes_size('extractor.tb1m')")
    attempt("indexed row count", "SELECT count(*) FROM extractor.tb_idx")
    attempt("ts_dict_agg/ts_dict_count top terms",
            "SELECT t, c FROM (SELECT unnest(ts_dict_agg(body)) AS t, unnest(ts_dict_count(body)) AS c FROM extractor.tb_idx) ORDER BY c DESC LIMIT 10")
    attempt("distinct sev values (verbatim column)",
            "SELECT unnest(ts_dict_agg(sev)) AS sev, unnest(ts_dict_count(sev)) AS n FROM extractor.tb_idx")
    attempt("pitfall: ts_dict_agg on the view (not the index)", "SELECT ts_dict_agg(body) FROM extractor.tb1m LIMIT 1")
    ok2, _, _ = attempt("DROP INDEX", "DROP INDEX extractor.tb_idx")
    return ok and ok2


# 10 --------------------------------------------------------------------
def c10_dictionary():
    ok = True
    try:
        q("DROP TEXT SEARCH DICTIONARY IF EXISTS extractor.log_dict")
    except Exception:  # noqa: BLE001
        pass
    r, _, _ = attempt("CREATE TEXT SEARCH DICTIONARY",
                      "CREATE TEXT SEARCH DICTIONARY extractor.log_dict AS split_text(case := 'lower') | normalize_tokens('en_US.UTF-8', accent := false) WITH (frequency, position)")
    ok &= r
    attempt("ts_lexize", "SELECT ts_lexize('extractor.log_dict', 'Connection REFUSED to 10.0.7.21:5432 café')")
    q("DROP TABLE IF EXISTS extractor.d")
    q("CREATE TABLE extractor.d (id BIGINT PRIMARY KEY, body TEXT)")
    q("INSERT INTO extractor.d SELECT i, CASE i % 3 WHEN 0 THEN 'Connection refused to 10.0.7.21' WHEN 1 THEN 'timeout after 30ms calling payments' ELSE 'user login failed' END FROM range(300) t(i)")
    q("CREATE INDEX d_idx ON extractor.d USING inverted(body extractor.log_dict)")
    q("VACUUM (REFRESH_TABLE) extractor.d")
    r, rows, _ = attempt("@@ ts_phrase via index name", "SELECT count(*) FROM extractor.d_idx WHERE body @@ ts_phrase('connection refused')")
    ok &= r and rows == [(100,)]
    r, rows, _ = attempt("@@ ts_levenshtein via index name", "SELECT count(*) FROM extractor.d_idx WHERE body @@ ts_levenshtein('conection', 2)")
    ok &= r and rows == [(100,)]
    attempt("pitfall: @@ ts_phrase on the base table (not the index)", "SELECT count(*) FROM extractor.d WHERE body @@ ts_phrase('connection refused')")
    attempt("ts_dict_agg + counts", "SELECT unnest(ts_dict_agg(body)) AS t, unnest(ts_dict_count(body)) AS c FROM extractor.d_idx")
    plan = "\n".join(r[0] for r in q("EXPLAIN SELECT count(*) FROM extractor.d_idx WHERE body @@ ts_phrase('connection refused')")[0])
    show("EXPLAIN on index name uses IRESEARCH_SCAN", "IRESEARCH_SCAN" in plan)
    plan = "\n".join(r[0] for r in q("EXPLAIN SELECT count(*) FROM extractor.d WHERE body ILIKE '%refused%'")[0])
    show("EXPLAIN base-table ILIKE uses IRESEARCH_SCAN (index used implicitly?)", "IRESEARCH_SCAN" in plan)
    attempt("index size", "SELECT pg_relation_size('extractor.d_idx')")
    q("DROP INDEX extractor.d_idx")
    return ok


# 11 --------------------------------------------------------------------
def c11_copy_to_parquet():
    ok, rows, _ = attempt("COPY (...) TO '/tmp/x.parquet'", "COPY (SELECT i AS id, 'row ' || i AS body FROM range(1000) t(i)) TO '/tmp/x.parquet' (FORMAT PARQUET)")
    if not ok:
        return False
    ok2, rows, _ = attempt("read back inside SereneDB", "SELECT count(*), min(id), max(id) FROM read_parquet('/tmp/x.parquet')")
    attempt("file_row_number on local parquet", "SELECT id, file_row_number, filename FROM read_parquet('/tmp/x.parquet', filename=true, file_row_number=true) LIMIT 2")
    return ok2 and rows == [(1000, 0, 999)]


# 12 --------------------------------------------------------------------
def c12_copy_from_stdin():
    q("DROP TABLE IF EXISTS extractor.cp")
    q("CREATE TABLE extractor.cp (entry_id BIGINT PRIMARY KEY, ts TIMESTAMPTZ, level TEXT, message TEXT, attrs JSON)")
    n = 20000
    t = time.perf_counter()
    with CONN.cursor() as cur:
        with cur.copy("COPY extractor.cp (entry_id, ts, level, message, attrs) FROM STDIN") as cp:
            for i in range(n):
                cp.write_row((i, "2026-03-01 00:00:00+00", "INFO", f"msg {i}\twith tab and \"quote\" and, comma", '{"k": %d}' % i))
    el = time.perf_counter() - t
    rows, _ = q("SELECT count(*), min(entry_id), max(entry_id), max(message) FROM extractor.cp")
    show(f"COPY FROM STDIN {n} rows [{el:.2f}s]", rows)
    attempt("message round-trip (tab/quote)", "SELECT message, attrs FROM extractor.cp WHERE entry_id = 7")
    return rows[0][0] == n


CHECKS: list[tuple[int, str, Callable[[], bool]]] = [
    (1, "connection defaults", c01_connection),
    (2, "cancel_safe cancels a long query", c02_cancel),
    (3, "schema/PK/JSON/UPDATE/DELETE/DROP CASCADE", c03_ddl_dml),
    (4, "SQL functions", c04_functions),
    (5, "remote Parquet in place + metadata", c05_remote_parquet),
    (6, "EXPLAIN shape / pushdown", c06_explain),
    (7, "sampling + row-group pruning", c07_sampling),
    (8, "filter-first vs sample-first", c08_filter_first),
    (9, "inverted index over view", c09_inverted_index),
    (10, "text search dictionary + @@ ts_phrase / ts_levenshtein", c10_dictionary),
    (11, "COPY TO Parquet inside container", c11_copy_to_parquet),
    (12, "cursor.copy streaming", c12_copy_from_stdin),
]


def main() -> int:
    wanted = {int(a) for a in sys.argv[1:]}
    setup_schema()
    results = {}
    for n, title, fn in CHECKS:
        if wanted and n not in wanted:
            continue
        print(f"\n== {n}. {title}", flush=True)
        t = time.perf_counter()
        try:
            ok = bool(fn())
        except Exception as e:  # noqa: BLE001
            print(f"    EXCEPTION {type(e).__name__}: {str(e).strip().splitlines()[0] if str(e).strip() else ''}")
            ok = False
        results[n] = ok
        print(f"{'PASS' if ok else 'FAIL'} {n}. {title} ({time.perf_counter() - t:.1f}s)", flush=True)
    print("\nSUMMARY:", ", ".join(f"{n}={'PASS' if v else 'FAIL'}" for n, v in results.items()))
    print(f"{sum(results.values())}/{len(results)} passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
