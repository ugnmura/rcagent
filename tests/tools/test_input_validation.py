"""Round 3 input fixes: list filters on plain columns, run_sql limits on huge values and timeouts, search
text that can't be searched, a fuzzy search whose index went away, search index needs, find_values'
index header, oversized occurrence IDs, survey sample sizes."""

import re
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from serenedb_extractor.catalog.models import FieldRoles, LogTable
from serenedb_extractor.catalog.store import CatalogStore
from serenedb_extractor.errors import UserFacingError
from serenedb_extractor.query.filters import MAX_FILTER_VALUES, Filters
from serenedb_extractor.query.guard import SqlRejected, check_read_only
from serenedb_extractor.query.occurrence import decode_occurrence
from serenedb_extractor.setup.indexes import spec
from serenedb_extractor.tools.lookup import FUZZY_NEEDS_INDEX
from serenedb_extractor.tools.sql import _timeout
from tests.conftest import call, container_parquet
from tests.fixtures.data import FX

# FX plus two plain columns that are no role: a text rack and a numeric http code.
R3 = f"""
SELECT *, 'r' || (hash(message) % 3)::VARCHAR AS rack,
  CASE WHEN level = 'ERROR' THEN 503 ELSE 200 END AS http_code
FROM ({FX})
"""


def _lt(**over: object) -> LogTable:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    base = dict(
        name="x", source="/tmp/x.parquet", source_format="parquet", mode="in_place", relation="extractor.lt_x",
        roles=FieldRoles(message="message", timestamp="ts"), filter_index_name=None, search_index_name=None,
        row_count=None, timezone="UTC", created_at=now, roles_updated_at=now,
    )
    base.update(over)
    return LogTable(**base)  # type: ignore[arg-type]


# --- 1. list filters on plain columns ---


def test_column_filters_keep_lists_as_text():
    f = Filters.from_dict({"node": ["x", "R22"], "status": [200, 503], "code": 404, "ok": True, "level": [1.0]})
    assert f.columns == {"node": ["x", "R22"], "status": ["200", "503"], "code": "404", "ok": "true"}
    assert f.level == ["1"]


def test_filter_value_lists_are_capped():
    Filters.from_dict({"node": [str(i) for i in range(MAX_FILTER_VALUES)]})
    with pytest.raises(UserFacingError, match=r"lists 1,001 values; at most 1,000"):
        Filters.from_dict({"node": [str(i) for i in range(MAX_FILTER_VALUES + 1)]})


@pytest.fixture
async def r3(mcp, db_url):
    path = container_parquet(db_url, "r3inp_fx", R3)
    out = await call(mcp, "setup_log_table", name="r3", source=path)
    assert "Set up log table" in out, out
    return path


def _total(out: str) -> int:
    m = re.search(r"([\d,]+) (?:matching )?entr", out)
    assert m, out
    return int(m.group(1).replace(",", ""))


@pytest.mark.db
async def test_list_filter_on_a_column_matches(mcp, r3):
    one = await call(mcp, "count_logs", log_tables=["r3"], filters={"rack": "r1"})
    both = await call(mcp, "count_logs", log_tables=["r3"], filters={"rack": ["nope", "r1"]})
    assert "rack in ('nope', 'r1')" in both, both
    assert _total(both) == _total(one) > 0, (one, both)
    codes = await call(mcp, "count_logs", log_tables=["r3"], filters={"http_code": [200, 503]})
    assert _total(codes) == 5000, codes
    errors = await call(mcp, "count_logs", log_tables=["r3"], filters={"http_code": 503})
    assert _total(errors) == 3030, errors
    found = await call(mcp, "search_logs", log_table="r3", filters={"http_code": [503]}, text="disk full")
    assert "30 matching entries (exact)" in found, found


@pytest.mark.db
async def test_empty_list_filter_on_a_column_is_explained(mcp, r3):
    out = await call(mcp, "search_logs", log_table="r3", filters={"rack": ["nope", "nada"]})
    assert "rack in ('nope', 'nada') matched nothing" in out and "r1" in out, out


# --- 2. run_sql: huge values from small input, timeouts ---


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT repeat('a', 100000000)",
        "SELECT lpad('a', 100000000, 'b')",
        "SELECT rpad('a', 100000000, 'b')",
        "SELECT printf('%100000000d', 1)",
        "SELECT format('{:>100000000}', 'a')",
    ],
)
def test_value_builders_are_refused(sql):
    with pytest.raises(SqlRejected, match="isn't allowed in run_sql"):
        check_read_only(sql)


def _ctx(max_s: float = 300.0) -> SimpleNamespace:
    settings = SimpleNamespace(max_timeout_s=max_s, default_timeout_s=30.0)
    db = SimpleNamespace(effective_timeout=lambda t: 30.0 if t is None else min(t, max_s))
    return SimpleNamespace(settings=settings, db=db)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf"), -1, 0])
def test_timeout_must_be_a_positive_number(bad):
    with pytest.raises(UserFacingError, match="timeout_s must be"):
        _timeout(_ctx(), bad)  # type: ignore[arg-type]


def test_timeout_above_the_maximum_is_cut_and_said():
    t, note = _timeout(_ctx(), 1e308)  # type: ignore[arg-type]
    assert t == 300.0 and "timeout cut to 300 s, the server's maximum" in note
    assert _timeout(_ctx(), 12) == (12, "")  # type: ignore[arg-type]
    assert _timeout(_ctx(), None) == (30.0, "")  # type: ignore[arg-type]


@pytest.mark.db
async def test_run_sql_says_the_timeout_was_cut(mcp, r3):
    out = await call(mcp, "run_sql", sql="SELECT 1 AS one", timeout_s=1e308)
    assert "timeout cut to" in out and "one" in out, out


# --- 3. search text that can't be searched ---


@pytest.mark.db
async def test_nul_and_overlong_text_are_refused_plainly(mcp, r3):
    out = await call(mcp, "search_logs", log_table="r3", text="disk\u0000full")
    assert "NUL character" in out and "could not finish reading" not in out, out
    long = "a" * 1_000_001
    out = await call(mcp, "search_logs", log_table="r3", text=long)
    assert "1,000,001 characters long; at most 1,000" in out and long not in out, out[:500]
    out = await call(mcp, "count_logs", log_tables=["r3"], text="x\u0000")
    assert "NUL character" in out, out
    assert "matching" in await call(mcp, "search_logs", log_table="r3", text="a" * 1000)


# --- 4. a fuzzy search whose index went away ---


@pytest.mark.db
async def test_fuzzy_search_never_falls_back_to_an_exact_scan(mcp, r3, monkeypatch):
    await call(mcp, "create_index", log_table="r3", kind="search")
    assert "disk full on" in await call(mcp, "search_logs", log_table="r3", text="dsik full", fuzzy=True)
    # The index is dropped while the search runs: the catalog no longer lists its columns.
    monkeypatch.setattr(CatalogStore, "index_columns", lambda self, name: {})
    out = await call(mcp, "search_logs", log_table="r3", text="dsik full", fuzzy=True)
    assert FUZZY_NEEDS_INDEX in out and "exact search" not in out, out


# --- 5. a search index's needs ---


def test_search_index_message_matches_its_kind():
    roles = FieldRoles(message='"message"', timestamp="\"attrs\" ->> 'ts'")
    with pytest.raises(UserFacingError) as err:
        spec(roles, "search")
    assert "search index" in str(err.value) and "timestamp" in str(err.value) and "filter index" not in str(err.value)
    assert spec(FieldRoles(message='"message"', timestamp='"ts"'), "search") == [("message", True), ("ts", False)]
    with pytest.raises(UserFacingError, match="filter index"):
        spec(roles, "filter")


# --- 6. find_values through a filter index ---


@pytest.mark.db
async def test_find_values_header_names_the_index(mcp, r3):
    await call(mcp, "create_index", log_table="r3", kind="filter")
    out = await call(mcp, "describe_logs", log_table="r3", find_values={"service": "pay"})
    head = out.splitlines()[0]
    assert "no entry was scanned" in head and "index used: " in head and "no index used" not in head, head


# --- 7. oversized occurrence IDs ---


def test_occurrence_with_a_huge_number_is_refused_plainly():
    with pytest.raises(UserFacingError, match="No entry has the occurrence ID .* 5,000 digits"):
        decode_occurrence(_lt(), "x.parquet#" + "9" * 5000)
    with pytest.raises(UserFacingError, match="No entry has"):
        decode_occurrence(_lt(mode="copied"), "e:" + "1" * 19)
    where, params = decode_occurrence(_lt(), "x.parquet#" + "0" * 30 + "42")
    assert params["occ_row"] == 42
    with pytest.raises(UserFacingError, match="not an occurrence ID"):
        decode_occurrence(_lt(), "x.parquet#²")


@pytest.mark.db
async def test_get_context_with_a_huge_row_number(mcp, r3):
    out = await call(mcp, "get_context", log_table="r3", occurrence="r3inp_fx.parquet#" + "9" * 5000)
    assert "No entry has the occurrence ID" in out and "Exceeds" not in out, out[:400]


# --- 8. survey sample sizes ---


@pytest.mark.db
async def test_survey_sample_size_messages(mcp, r3):
    for bad in (0, -1):
        out = await call(mcp, "survey", log_table="r3", sample_size=bad)
        assert "sample_size is how many entries the survey looks at" in out and "A limit" not in out, out
    out = await call(mcp, "survey", log_table="r3", sample_size=999_999_999_999)
    assert "sample_size 999,999,999,999 is more than one survey looks at" in out, out[:1500]
