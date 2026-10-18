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
    assert "reads up to ~" in out and "needs ~" not in out  # a full-scan bound, not a prediction of the read
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


# Fix round 2: scope-aware relations, a function allowlist, TABLE in any form, parser limits (R56, R61).
BYPASSES = [
    "SELECT * FROM (WITH pg_authid AS (SELECT 1) SELECT 1) a, pg_authid",
    "WITH x AS (WITH pg_tables AS (SELECT 1) SELECT 1) SELECT * FROM pg_tables",
    "SELECT * FROM extractor.log_tables WHERE EXISTS (WITH pg_settings AS (SELECT 1) SELECT 1) OR 1 IN (SELECT 1 FROM pg_settings)",
    "SELECT coalesce(NULL, (TABLE pg_database))",
    "SELECT array_length([(TABLE pg_authid)])",
    "SELECT 'x' IN (TABLE pg_namespace)",
    "SELECT * FROM (TABLE pg_tables) t",
    "SELECT 1 WHERE 'x' = (TABLE pg_authid)",
    "SELECT 1 AS a UNION ALL (TABLE pg_namespace)",
    "SELECT generate_series(1, 3)",
    "SELECT range(3)",
    "SELECT current_setting('search_path')",
    "SELECT getenv('HOME')",
    "SELECT csv_scan('/etc/hostname')",
    "SELECT \"Read_Text\"('/etc/passwd')",
    "SELECT main.read_text('/etc/passwd')",
    "SELECT U&\"\\0072ead_text\"('/etc/hostname')",
    "SELECT * FROM U&\"\\0072ead_text\"('/etc/hostname')",
    "SELECT CASE WHEN 1=1 THEN read_text('/etc/passwd') END",
    "SELECT row_number() OVER (ORDER BY read_blob('/etc/passwd'))",
    "SELECT " + "(" * 2000 + "1" + ")" * 2000,
    "SELECT 1 FROM " + "(SELECT 1 FROM " * 600 + "extractor.log_tables" + ") a" * 600,
]


@pytest.mark.parametrize("bad", BYPASSES)
def test_guard_blocks_bypass(bad):
    with pytest.raises(SqlRejected):
        check_read_only(bad)


@pytest.mark.parametrize("bad", BYPASSES[:6] + BYPASSES[9:12])
async def test_bypass_not_executed(mcp, bad):
    out = await call(mcp, "run_sql", sql=bad)
    assert "only read" in out.lower(), out


@pytest.mark.parametrize(
    "ok",
    [
        "WITH a AS (SELECT 1 AS v), b AS (SELECT v FROM a) SELECT * FROM b",
        "SELECT * FROM (WITH c AS (SELECT 1 AS v) SELECT v FROM c) s",
        "WITH RECURSIVE r AS (SELECT 1 AS n UNION ALL SELECT n + 1 FROM r WHERE n < 3) SELECT n FROM r",
        "SELECT lower(name), upper(name), length(name), substr(name, 1, 2), replace(name, 'a', 'b'), trim(name), concat(name, 'x') FROM extractor.log_tables",
        "SELECT regexp_full_match(name, 'a.*'), regexp_extract(name, '(a)', 1), regexp_replace(name, 'a', 'b') FROM extractor.log_tables",
        "SELECT date_trunc('hour', created_at), extract(epoch FROM created_at), strftime(created_at, '%Y'), CAST(created_at AS date) FROM extractor.log_tables",
        "SELECT count(*), count(DISTINCT name), sum(row_count), avg(row_count), min(name), max(name), quantile_cont(row_count, 0.5), approx_count_distinct(name), any_value(name), string_agg(name, ',') FROM extractor.log_tables",
        "SELECT name, row_number() OVER (ORDER BY name), lag(name) OVER (ORDER BY name), rank() OVER (ORDER BY name) FROM extractor.log_tables",
        "SELECT coalesce(name, 'x'), nullif(name, ''), greatest(1, 2), least(1, 2), abs(-1), round(1.5), floor(1.5), ceil(1.5) FROM extractor.log_tables",
        "SELECT json_extract_string('{\"a\": 1}', '$.a'), '{\"a\": 1}'::json ->> 'a'",
        "SELECT name FROM extractor.log_tables WHERE name LIKE '50%' AND row_count IN (1, 2) AND NOT (name IS NULL) ORDER BY name LIMIT 5",
        "SELECT CAST(1 AS varchar(10)), 1::numeric(10, 2)",
    ],
)
def test_allowlisted_queries_pass(ok):
    check_read_only(ok)


@pytest.mark.parametrize("name", ["pg_read_file", "generate_series", "current_setting", "read_text", "getenv"])
def test_function_rejection_names_it(name):
    with pytest.raises(SqlRejected, match=f"function {name} isn't allowed in run_sql"):
        check_read_only(f"SELECT {name}('x')")


async def test_allowed_functions_run(mcp):
    out = await call(mcp, "run_sql", sql="SELECT upper('ab') AS u, regexp_extract('a12', '[0-9]+') AS d, coalesce(NULL, 3) AS c")
    assert "u | d | c\n--- | --- | ---\nAB | 12 | 3" in out, out


@pytest.mark.parametrize(
    "bad",
    [
        "SELECT 'pg_authid'::regclass",
        "SELECT CAST('pg_authid' AS regclass)",
        "SELECT 'pg_authid'::pg_catalog.regclass",
        "SELECT 'pg_authid'::\"regclass\"",
        "SELECT 'pg_authid'::REGCLASS::oid",
        "SELECT 'upper'::regproc",
        "SELECT CAST('upper' AS regprocedure)",
        "SELECT 'text'::regtype",
        "SELECT 'public'::regnamespace",
        "SELECT 'postgres'::regrole",
        "SELECT '+'::regoper",
        "SELECT regclass 'pg_authid'",
        "SELECT 'simple'::regconfig",
        "SELECT '{pg_authid}'::_regclass",
        "SELECT '{pg_authid}'::pg_catalog._regclass",
        "SELECT '{text}'::\"_regtype\"",
        "SELECT '{pg_authid}'::__REGCLASS",
        "SELECT '{pg_authid}'::regclass[]",
    ],
)
def test_reg_casts_rejected(bad):
    with pytest.raises(SqlRejected, match="reg"):
        check_read_only(bad)


def test_reg_prefix_names_that_are_not_types_still_work():
    check_read_only("SELECT regexp_extract(name, 'a') AS region FROM extractor.log_tables")


def test_refusals_name_the_real_reason():
    import pytest

    from serenedb_extractor.query.guard import SqlRejected, check_read_only

    with pytest.raises(SqlRejected, match="one statement at a time"):
        check_read_only("SELECT 1; DROP TABLE extractor.lt_x")
    with pytest.raises(SqlRejected, match="changes data"):
        check_read_only("WITH x AS (DELETE FROM extractor.lt_x RETURNING *) SELECT * FROM x")
    check_read_only("SELECT timezone('UTC', ts) FROM extractor.lt_x")  # read-only: allowed
    check_read_only("SELECT 'a;b' FROM extractor.lt_x;")  # a ; inside a string, and a trailing one, are fine
