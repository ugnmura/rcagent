"""Round 4 limits: run_sql's guard against value growth (recursion, whole-column aggregates, adjacent
literals), grouping syntax it must allow, timeouts that answer on time, filter value caps, and
evidence ids shared by several server processes."""

import time

import pytest

from serenedb_extractor.errors import UserFacingError
from serenedb_extractor.query.filters import Filters
from serenedb_extractor.query.guard import SqlRejected, check_read_only
from tests.conftest import call

T = "extractor.lt_bgl"


# ---- 1. recursive CTEs may not build values ----------------------------------------------------------


@pytest.mark.parametrize(
    "grow",
    [
        "s || s",
        "concat(s, s)",
        "replace(s, 'x', 'xx')",
        "json_array(s, s)::varchar",
        "(s, s)::varchar",
        "[s, s]::varchar",
        "{'a': s, 'b': s}::varchar",
        "row(s, s)::varchar",
    ],
)
def test_recursive_cte_that_builds_values_is_refused(grow):
    sql = (
        f"WITH RECURSIVE r AS (SELECT 'x' AS s, 0 AS i UNION ALL SELECT {grow}, i + 1 FROM r WHERE i < 40) "
        "SELECT max(length(s)) FROM r"
    )
    with pytest.raises(SqlRejected, match="recursive"):
        check_read_only(sql)


def test_plain_recursive_counting_still_works():
    check_read_only("WITH RECURSIVE r AS (SELECT 1 AS n UNION ALL SELECT n + 1 FROM r WHERE n < 3) SELECT n FROM r")
    check_read_only(
        "WITH RECURSIVE r AS (SELECT 1 AS n UNION ALL SELECT n + 1 FROM r WHERE n IN (1, 2)) SELECT n, s[1] FROM r, "
        "(SELECT 'ab' AS s) q"
    )


# ---- 2. whole-column aggregates ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "sql,why",
    [
        (f"WITH k AS (SELECT string_agg(message, '') r FROM {T}) SELECT replace(m.message, 'a', k.r) FROM {T} m, k", "whole column"),
        (f"SELECT string_agg(message, '') OVER (ORDER BY entry_id ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) FROM {T}", "window"),
        (f"SELECT array_agg(message) FILTER (WHERE true) OVER (ORDER BY entry_id) FROM {T}", "window"),
        (f"SELECT list(message) OVER w FROM {T} WINDOW w AS (ORDER BY entry_id)", "window"),
        (f"SELECT array_to_string(array_agg(message), '') FROM {T}", "nest at most one"),
        (f"WITH k AS (SELECT list_aggr(list(message), 'string_agg', '') r FROM {T}) SELECT k.r FROM k", "nest at most one"),
        (f"WITH k AS (SELECT list(message)::varchar r FROM {T}) SELECT replace(m.message, 'a', k.r) FROM {T} m, k", "whole column"),
        (f"WITH k AS (SELECT string_agg(message, '') r FROM {T}) SELECT m.message || k.r FROM {T} m, k", "whole column"),
        (f"WITH k AS (SELECT string_agg(message, '') r FROM {T}) SELECT string_agg(k.r, '') FROM {T} m, k", "whole column"),
    ],
)
def test_whole_column_aggregates_cannot_feed_growth(sql, why):
    with pytest.raises(SqlRejected, match=why):
        check_read_only(sql)


@pytest.mark.parametrize(
    "sql",
    [
        f"SELECT level, count(*) FROM {T} GROUP BY level",
        f"SELECT string_agg(DISTINCT level, ',') FROM {T}",
        f"SELECT replace(message, 'a', 'b') FROM {T}",
        f"SELECT level || ' ' || component FROM {T}",
        f"SELECT quantile_cont(entry_id, 0.95), date_trunc('hour', ts) FROM {T} GROUP BY 2",
        f"WITH a AS (SELECT level, count(*) n FROM {T} GROUP BY level), b AS (SELECT level, max(ts) t FROM {T} "
        "GROUP BY level) SELECT * FROM a JOIN b USING (level)",
        f"SELECT level, row_number() OVER (PARTITION BY level ORDER BY ts), count(*) OVER (PARTITION BY level) FROM {T}",
        f"SELECT array_length(array_agg(DISTINCT level)) FROM {T}",
    ],
)
def test_normal_analytics_still_pass(sql):
    check_read_only(sql)


# ---- 3. adjacent string literals are one text ---------------------------------------------------------


def test_adjacent_literals_count_together():
    half = "a" * 60
    with pytest.raises(SqlRejected, match="longer than 100"):
        check_read_only(f"SELECT replace(message, 'a', '{half}'\n'{half}') FROM {T}")
    big = "x" * 600
    with pytest.raises(SqlRejected, match="longer than 1000"):
        check_read_only(f"SELECT '{big}'\n'{big}'")
    check_read_only(f"SELECT '{big}', '{big}'")  # two separate texts: each within the cap


# ---- 4. grouping syntax ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "sql",
    [
        f"SELECT level, component, count(*) FROM {T} GROUP BY CUBE(level, component)",
        f"SELECT level, component, count(*) FROM {T} GROUP BY ROLLUP(level, component)",
        f"SELECT level, grouping(level), count(*) FROM {T} GROUP BY GROUPING SETS ((level), (component), ())",
        f"SELECT percentile_cont(0.95) WITHIN GROUP (ORDER BY entry_id) FROM {T}",
    ],
)
def test_grouping_syntax_is_allowed(sql):
    check_read_only(sql)


def test_group_is_still_not_a_function():
    with pytest.raises(SqlRejected, match="function group"):
        check_read_only('SELECT "group"(1)')


@pytest.mark.db
async def test_grouping_syntax_runs(mcp):
    for sql, expect in [
        ("SELECT name, grouping(name) AS g, count(*) AS n FROM extractor.log_tables GROUP BY CUBE(name)", "g | n"),
        ("SELECT name, count(*) AS n FROM extractor.log_tables GROUP BY ROLLUP(name)", "name | n"),
        ("SELECT name, count(*) AS n FROM extractor.log_tables GROUP BY GROUPING SETS ((name), ())", "name | n"),
        ("SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY row_count) AS p FROM extractor.log_tables", "p\n"),
    ]:
        out = await call(mcp, "run_sql", sql=sql)
        assert expect in out and "Not run" not in out, out


# ---- 5. a timeout answers on time even when SereneDB ignores the cancel ---------------------------------

SLOW = "SELECT (SELECT max(hash(i)) FROM range(4000000000) t(i)) > 0"


@pytest.mark.db
def test_timeout_answers_on_time_when_the_cancel_is_ignored(database, monkeypatch):
    import psycopg

    from serenedb_extractor import db as dbmod
    from serenedb_extractor.db import QueryTimeout

    def ignored(self, timeout=None):  # accepted, but the statement runs on (one huge step)
        return None

    monkeypatch.setattr(psycopg.Connection, "cancel_safe", ignored)
    began = time.monotonic()
    with pytest.raises(QueryTimeout, match="TIMEOUT after 1s"):
        database.read(SLOW, {}, timeout_s=1, what="x")
    took = time.monotonic() - began
    assert took < 1 + dbmod.CANCEL_TIMEOUT_S + dbmod.LATE_GRACE_S + 2, took
    assert database.read("SELECT 1", {}).scalar() == 1  # a fresh connection


@pytest.mark.db
def test_failed_cancel_cuts_the_connection_at_once(database, monkeypatch):
    import psycopg

    from serenedb_extractor.db import QueryTimeout

    def broken(self, timeout=None):
        raise psycopg.OperationalError("cancel refused")

    monkeypatch.setattr(psycopg.Connection, "cancel_safe", broken)
    began = time.monotonic()
    with pytest.raises(QueryTimeout):
        database.read(SLOW, {}, timeout_s=1, what="x")
    assert time.monotonic() - began < 3
    assert database.read("SELECT 1", {}).scalar() == 1


# ---- 6. filter values ----------------------------------------------------------------------------------


def test_filter_values_are_capped_and_nul_is_refused():
    with pytest.raises(UserFacingError, match="at most 1,000 fit in one value"):
        Filters.from_dict({"level": "x" * 5000})
    with pytest.raises(UserFacingError, match="at most 1,000 fit in one value"):
        Filters.from_dict({"host": ["ok", "y" * 1001]})
    with pytest.raises(UserFacingError, match="NUL character"):
        Filters.from_dict({"level": "ERR\x00OR"})
    with pytest.raises(UserFacingError, match="NUL character"):
        Filters.from_dict({"component": ["a", "b\x00"]})
    f = Filters.from_dict({"level": "x" * 1000, "host": ["a", "b"]})
    assert f.level == "x" * 1000 and f.host == ["a", "b"]


# ---- 7. evidence ids across server processes ------------------------------------------------------------


@pytest.mark.db
def test_evidence_ids_stay_unique_across_processes(database, db_url):
    from serenedb_extractor.catalog.schema import bootstrap
    from serenedb_extractor.evidence import EvidenceLog
    from tests.conftest import _reset_schema

    _reset_schema(db_url)
    bootstrap(database)
    a, b = EvidenceLog(database), EvidenceLog(database)  # two server processes on one database
    assert a.record("a_tool", {}, [], "a1").id == 1
    assert b.record("b_tool", {}, [], "b1").id == 2
    ra = a.record("a_tool", {}, [], "a2")  # a counted on to 2, which b took: it moves on
    assert ra.id == 3 and ra.handle == "Q3"
    rb = b.record("b_tool", {}, [], "b2")
    assert rb.id == 4
    assert a._persist and b._persist  # one duplicate does not turn storing off
    fresh = EvidenceLog(database)
    stored = {i: fresh.get(i) for i in (1, 2, 3, 4)}
    assert {i: (r.tool, r.result) for i, r in stored.items() if r} == {
        1: ("a_tool", "a1"), 2: ("b_tool", "b1"), 3: ("a_tool", "a2"), 4: ("b_tool", "b2")
    }
    assert a.get(3) is ra and b.get(2).result == "b1"
