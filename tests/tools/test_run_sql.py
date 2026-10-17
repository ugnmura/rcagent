"""run_sql (#16): the read-only guard, limits and the plan-based cost check, at the MCP tool seam."""

import pytest

from serenedb_extractor.config import Settings
from serenedb_extractor.context import AppContext
from serenedb_extractor.errors import UserFacingError
from serenedb_extractor.query import cost
from serenedb_extractor.query.guard import SqlRejected, check_read_only
from serenedb_extractor.tools.sql import execute_user_sql
from tests.conftest import _client, call, container_parquet, token_of
from tests.fixtures.data import FX

pytestmark = pytest.mark.db

FILE = "t16_fx"


@pytest.fixture
async def fx_lt(mcp, db_url):
    path = container_parquet(db_url, FILE, FX)
    await call(mcp, "setup_log_table", name="fx", source=path)
    return path


@pytest.mark.parametrize(
    "ok,expect",
    [
        ("SELECT 41 + 1 AS answer", "answer\n---\n42\n"),
        ("WITH a AS (SELECT 7 AS v) SELECT v FROM a", "v\n---\n7\n"),
        ("EXPLAIN SELECT 1", "How this was measured: EXPLAIN only; the query was not run.\n"),
        ("SELECT 1 AS n UNION SELECT 2 AS n ORDER BY n", "n\n---\n1\n2\n"),
        ("SELECT count(*) AS n FROM extractor.log_tables", "n\n---\n0\n"),
        ("SELECT * FROM information_schema.tables", None),
    ],
)
async def test_allows(mcp, ok, expect):
    out = await call(mcp, "run_sql", sql=ok)
    if expect is None:  # information_schema is outside the extractor schema: refused (R49)
        assert "information_schema" in out and "only read" in out.lower()
        return
    assert "only read" not in out.lower()
    assert expect in out


async def test_measured_line_first(mcp):
    for sql in ("SELECT 1", "EXPLAIN SELECT 1", "SELECT 1 FROM (", "DELETE FROM extractor.templates"):
        out = await call(mcp, "run_sql", sql=sql)
        if "only read" not in out:
            assert out.startswith("How this was measured: "), out


@pytest.mark.parametrize(
    "bad",
    [
        "DELETE FROM extractor.templates",
        "SELECT 1; DROP TABLE x",
        "COPY extractor.templates TO '/tmp/x'",
        "SET threads = 1",
        "SELECT pg_terminate_backend(1)",
        "CREATE TABLE x (a int)",
        "WITH x AS (INSERT INTO extractor.templates DEFAULT VALUES RETURNING *) SELECT * FROM x",
        "ATTACH 'x.db' AS y",
        "SELECT set_config('a', 'b', false)",
        "EXPLAIN DELETE FROM extractor.templates",
        "",
        "SELECT 1 FROM (",
    ],
)
async def test_rejects(mcp, bad):
    assert "only read" in (await call(mcp, "run_sql", sql=bad)).lower()


@pytest.mark.parametrize("bad", ["UPDATE t SET a = 1", "TRUNCATE t", "DROP TABLE t", "SELECT 1 INTO x", "SELECT 1; SELECT 2"])
def test_guard_raises(bad):
    with pytest.raises(SqlRejected, match="only read-only queries are allowed"):
        check_read_only(bad)


def test_guard_returns_parsed_select():
    assert check_read_only("select 1 union all select 2") is not None


async def test_cut(mcp, fx_lt):
    out = await call(mcp, "run_sql", sql="SELECT * FROM extractor.lt_fx")
    assert "showing 50 of" in out


async def test_limit_small(mcp, fx_lt):
    out = await call(mcp, "run_sql", sql="SELECT * FROM extractor.lt_fx", limit=5)
    assert "showing 5 of" in out


async def test_expensive_plan_asks(mcp, fx_lt, monkeypatch):
    monkeypatch.setattr(cost, "BUDGET_SECONDS", 0.0)
    out = await call(mcp, "run_sql", sql="SELECT count(*) FROM extractor.lt_fx")
    assert "TOO EXPENSIVE" in out
    assert "Nothing was run" in out
    assert "plan" in out.lower()
    # confirming runs it
    again = await call(mcp, "run_sql", sql="SELECT count(*) FROM extractor.lt_fx", confirmed_cost=token_of(out))
    assert "5000" in again or "5,000" in again


async def test_cheap_query_runs(mcp, fx_lt):
    out = await call(mcp, "run_sql", sql="SELECT count(*) AS n FROM extractor.lt_fx")
    assert "5000" in out or "5,000" in out


async def test_sql_error_is_plain(mcp):
    out = await call(mcp, "run_sql", sql="SELECT * FROM no_such_table_xyz")
    assert "Traceback" not in out and "Something went wrong" not in out


@pytest.mark.parametrize(
    "bad,named",
    [
        ("SELECT pg_read_file('/etc/passwd')", "pg_read_file"),
        ("SELECT pg_catalog.pg_read_file('/etc/passwd')", "pg_read_file"),
        ("SELECT pg_sleep(100)", "pg_sleep"),
        ("SELECT lo_export(1, '/tmp/x')", "lo_export"),
        ("SELECT dblink('host=x', 'select 1')", "dblink"),
        ("SELECT * FROM read_text('/etc/passwd')", "read_text"),
        ("SELECT read_text('/etc/passwd')", "read_text"),
        ("SELECT * FROM read_parquet('https://example.com/x.parquet')", "read_parquet"),
        ("SELECT * FROM glob('/etc/*')", ""),  # sqlglot can't parse GLOB as a function: refused as unreadable
        ("SELECT * FROM range(3)", "range"),
        ("SELECT * FROM generate_series(1, 3)", "generate_series"),
        ("SELECT * FROM extractor.log_tables, LATERAL read_text('/etc/passwd')", "read_text"),
        ("SELECT * FROM extractor.log_tables CROSS JOIN LATERAL read_parquet('https://example.com/x.parquet')", "read_parquet"),
        ("SELECT * FROM extractor.log_tables CROSS JOIN LATERAL harmless_looking_fn(name) f", "harmless_looking_fn"),
        ("SELECT * FROM extractor.log_tables, LATERAL unnest(ARRAY[1])", "unnest"),
        ("SELECT * FROM LATERAL (SELECT * FROM pg_catalog.pg_authid) s", "pg_authid"),
        ("SELECT * FROM pg_catalog.pg_authid", "pg_authid"),
        ("SELECT * FROM information_schema.tables", "information_schema"),
        ("SELECT * FROM log_tables", "log_tables"),
        ("SELECT * FROM other.extractor.log_tables", "other"),
        ("SELECT * FROM 'file.parquet'", "file.parquet"),
        ("SELECT nextval('s')", "nextval"),
        ("SELECT SETVAL('s', 1)", "setval"),
        ("SELECT \"SET_CONFIG\"('a', 'b', false)", "set_config"),
        ("SELECT Set_Config('a', 'b', false)", "set_config"),
        ("SELECT query_to_xml('select 1', true, true, '')", "query_to_xml"),
        ("SELECT table_to_xml('t', true, true, '')", "table_to_xml"),
        ("SELECT txid_current()", "txid_current"),
        ("SELECT * FROM extractor.log_tables WHERE name IN (SELECT pg_terminate_backend(1)::text)", "pg_terminate_backend"),
    ],
)
async def test_blocks_functions_and_relations(mcp, bad, named):
    out = await call(mcp, "run_sql", sql=bad)
    assert "only read" in out.lower(), out
    assert named.lower() in out.lower(), out


def test_lateral_subquery_over_allowed_tables_is_permitted():
    check_read_only("SELECT * FROM LATERAL (SELECT 1 AS a) s")
    check_read_only("SELECT * FROM extractor.log_tables l CROSS JOIN LATERAL (SELECT count(*) FROM extractor.templates t WHERE t.log_table = l.name) c")


def test_function_rule_allows_ordinary_functions():
    for ok in ("SELECT lower('A'), count(*), now(), coalesce(1, 2), regexp_extract('a1', '[0-9]')",
               "SELECT * FROM extractor.log_tables l JOIN extractor.templates t ON t.log_table = l.name"):
        check_read_only(ok)


def test_execution_helper_rejects_stacked_statements(database):
    # R50: even if the parser check were bypassed, the server refuses a second statement.
    with pytest.raises(UserFacingError):
        execute_user_sql(database, "SELECT 1; SELECT 2", None, "testing")
    assert execute_user_sql(database, "SELECT '%s' AS a", None, "testing").rows == [("%s",)]


def test_allow_sql_setting():
    base = {"SERENEDB_READER_URL": "postgresql://x@h/db"}
    assert Settings.from_env(base).allow_sql is False
    assert Settings.from_env({**base, "SERENEDB_ALLOW_SQL": "1"}).allow_sql is True
    assert Settings.from_env({**base, "SERENEDB_ALLOW_SQL": "0"}).allow_sql is False


async def test_single_role_refused(mcp_single_role):
    out = await call(mcp_single_role, "run_sql", sql="SELECT 1")
    assert "SERENEDB_ALLOW_SQL" in out and "SERENEDB_WRITER_URL" in out
    assert "How this was measured" not in out.split("Note:")[0]


async def test_single_role_allowed_by_env(db_url):
    env = {"SERENEDB_READER_URL": db_url, "SERENEDB_ALLOW_SQL": "1"}
    async for c in _client(lambda: AppContext.from_settings(Settings.from_env(env))):
        out = await call(c, "run_sql", sql="SELECT 5 AS five")
        assert out.startswith("How this was measured: ") and "five\n---\n5" in out
