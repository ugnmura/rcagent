"""run_sql (#16): the read-only guard, limits and the plan-based cost check, at the MCP tool seam."""

import pytest

from serenedb_extractor.query import cost
from serenedb_extractor.query.guard import SqlRejected, check_read_only
from tests.conftest import call, container_parquet, token_of
from tests.fixtures.data import FX

pytestmark = pytest.mark.db

FILE = "t16_fx"


@pytest.fixture
async def fx_lt(mcp, db_url):
    path = container_parquet(db_url, FILE, FX)
    await call(mcp, "setup_log_table", name="fx", source=path)
    return path


@pytest.mark.parametrize(
    "ok", ["SELECT 1", "WITH a AS (SELECT 1) SELECT * FROM a", "EXPLAIN SELECT 1", "SELECT 1 UNION SELECT 2"]
)
async def test_allows(mcp, ok):
    out = await call(mcp, "run_sql", sql=ok)
    assert "only read" not in out.lower()
    assert "1" in out


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
