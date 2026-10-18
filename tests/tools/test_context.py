"""get_context and template tags (#14), at the MCP tool seam."""

import re

import pytest

from tests.conftest import call, container_parquet, first_occurrence
from tests.fixtures.data import FX
from tests.fixtures.data_t14 import CTX

pytestmark = pytest.mark.db


@pytest.fixture
async def fx_lt(mcp, db_url):
    path = container_parquet(db_url, "t14_fx", FX)
    await call(mcp, "setup_log_table", name="fx", source=path)
    return path


@pytest.fixture
async def ctx_lt(mcp, db_url):
    path = container_parquet(db_url, "t14_ctx", CTX)
    out = await call(mcp, "setup_log_table", name="ctxfx", source=path)
    assert "Set up log table" in out, out
    await call(mcp, "survey", log_table="ctxfx")
    return path


async def _occ(mcp, text: str) -> str:
    return first_occurrence(await call(mcp, "search_logs", log_table="ctxfx", text=text, order="oldest", limit=1))


async def test_trace_scope_shows_cause(mcp, ctx_lt):
    occ = await _occ(mcp, "refused")
    out = await call(mcp, "get_context", log_table="ctxfx", occurrence=occ)
    assert "pool exhausted" in out and "other-service" not in out and "→" in out and "±5 min" in out
    assert out.startswith("How this was measured: ")


async def test_everything_scope(mcp, ctx_lt):
    occ = await _occ(mcp, "refused")
    assert "other-service" in await call(mcp, "get_context", log_table="ctxfx", occurrence=occ, scope="everything")


async def test_wider_window(mcp, ctx_lt):
    occ = await _occ(mcp, "refused")
    narrow = await call(mcp, "get_context", log_table="ctxfx", occurrence=occ, window_minutes=0.01)
    wide = await call(mcp, "get_context", log_table="ctxfx", occurrence=occ, window_minutes=10)
    assert "pool exhausted" not in narrow and "pool exhausted" in wide


async def test_absent_scope(mcp, fx_lt):
    occ = first_occurrence(await call(mcp, "search_logs", log_table="fx", text="disk"))
    assert "available scopes" in await call(mcp, "get_context", log_table="fx", occurrence=occ, scope=["host"])


async def test_long_entry_cut(mcp, ctx_lt):  # Review Focus 4
    occ = await _occ(mcp, "IllegalStateException")
    assert "…(cut)" in await call(mcp, "get_context", log_table="ctxfx", occurrence=occ)


async def test_tags_and_bad_occurrence(mcp, ctx_lt):
    assert "[T" in await call(mcp, "search_logs", log_table="ctxfx", text="refused")
    assert "occurrence" in (await call(mcp, "get_context", log_table="ctxfx", occurrence="garbage")).lower()


async def test_before_after_limits_and_default_service_host(mcp, ctx_lt):
    occ = await _occ(mcp, "refused")
    out = await call(mcp, "get_context", log_table="ctxfx", occurrence=occ, scope=["service", "host"], before=1, after=1)
    assert "checkout" in out and "pool exhausted" not in out


async def test_survey_and_get_context_both_registered(mcp_no_db):
    tools = {t.name: t for t in (await mcp_no_db.list_tools()).tools}
    assert "survey" in tools and "get_context" in tools
    assert tools["get_context"].annotations.readOnlyHint is True
    assert tools["survey"].annotations.readOnlyHint is False and tools["survey"].annotations.destructiveHint is False


def _template(tid: str, regex: str):
    from rcagent.catalog.models import Template

    return Template("t", tid, tid, regex, [], "", None, None, None, None)


def test_tags_trailing_whitespace_and_first_match():
    from rcagent.query.tags import tag_entries

    from rcagent.templating.regex import compile_template

    # The template's own regex allows edge whitespace (C1); tagging has no special case of its own.
    ts = [_template("T1", compile_template("disk full on <*>").regex), _template("T2", r".*")]
    assert tag_entries(ts, ["disk full on /dev/sda\n", "other", "disk full on x  "]) == ["T1", "T2", "T1"]


def test_tags_bad_regex_is_logged_not_silent(caplog):
    from rcagent.query.tags import tag_entries

    with caplog.at_level("WARNING"):
        assert tag_entries([_template("T9", "(unclosed"), _template("T2", "x")], ["x"]) == ["T2"]
    assert "T9" in caplog.text


def test_tags_linear_time_on_long_line_with_adjacent_placeholders():
    import time

    from rcagent.query.tags import tag_entries

    t = _template("T1", r"(\S+)(\S+)(\S+)(\S+)(\S+)x")
    start = time.monotonic()
    assert tag_entries([t], ["a" * 10_000]) == [None]
    assert time.monotonic() - start < 2


# C2 (final review): on a big in-place Parquet file the occurrence lookup reads only the row group
# that holds the row, so it is priced as that; a window that still doesn't fit asks with a token and
# only options that can help; a context is never sampled.
RG = """
SELECT TIMESTAMPTZ '2026-03-01 00:00:00+00' + i * INTERVAL '1 second' AS ts,
  CASE WHEN i % 2 = 0 THEN 'api' ELSE 'db' END AS service,
  'request ' || i::VARCHAR || ' handled by worker ' || (i % 13)::VARCHAR AS message
FROM range(20480) t(i) ORDER BY ts
"""


@pytest.fixture
async def rg_lt(mcp, db_url):
    import psycopg

    with psycopg.connect(db_url, autocommit=True) as conn:
        conn.execute(f"COPY ({RG}) TO '/tmp/c2_rg.parquet' (FORMAT PARQUET, ROW_GROUP_SIZE 2048)")  # type: ignore[call-overload]
    out = await call(mcp, "setup_log_table", name="rg", source="/tmp/c2_rg.parquet")
    assert "Set up log table" in out, out


def _budget_one_group(monkeypatch, database):
    """A budget of 1.5 row groups of the shown columns (10 s; well under the 600 s maximum): a full
    scan doesn't fit, one row group does."""
    from rcagent.catalog.store import CatalogStore
    from rcagent.query import cost
    from rcagent.query.filters import TimeRange
    from rcagent.query.stats import collect

    lt = CatalogStore(database).get_log_table("rg")
    st = collect(database, lt, TimeRange())
    shown = ["ts", "message", "service"]
    assert len(st.groups) == 10
    one = max(sum(g.bytes_by_column.get(c, 0) for c in shown) for g in st.groups)
    assert st.bytes_for(shown) > 3 * one
    monkeypatch.setitem(cost.THROUGHPUT_BYTES_PER_S, "local", one / 6.67)
    monkeypatch.setattr(cost, "BUDGET_SECONDS", 10.0)


async def test_lookup_priced_at_its_row_group_and_window_asks_with_a_token(mcp, rg_lt, database, monkeypatch):
    _budget_one_group(monkeypatch, database)
    occ = "/tmp/c2_rg.parquet#10000"
    out = await call(mcp, "get_context", log_table="rg", occurrence=occ, scope="everything")
    assert "TOO EXPENSIVE" in out and "confirmed_cost=" in out, out
    assert "the context of the occurrence" in out, out  # the window was priced, so the lookup ran
    assert "narrow it with a scope" not in out and "sample" not in out, out
    m = re.search(r"confirmed_cost=(\S+)", out)
    assert m, out
    token = m.group(1)
    ran = await call(mcp, "get_context", log_table="rg", occurrence=occ, scope="everything", confirmed_cost=token)
    assert "→" in ran and "request 10000 handled" in ran, ran


# Final review: where the occurrence lookup itself reads every entry (several Parquet files, a
# table's pk: IDs) and the window is over budget too, one confirmation covers both steps: the ask
# quotes their total once, and repeating the call with that token shows the context.
@pytest.fixture
async def glob_lt(mcp, db_url):
    import psycopg

    with psycopg.connect(db_url, autocommit=True) as conn:
        for part, lo in (("a", 0), ("b", 10240)):
            sql = RG.replace("range(20480)", f"range({lo}, {lo + 10240})")
            conn.execute(f"COPY ({sql}) TO '/tmp/c1_glob_{part}.parquet' (FORMAT PARQUET, ROW_GROUP_SIZE 2048)")  # type: ignore[call-overload]
    out = await call(mcp, "setup_log_table", name="globctx", source="/tmp/c1_glob_*.parquet")
    assert "Set up log table" in out, out


async def test_lookup_and_window_both_over_budget_take_one_token(mcp, glob_lt, database, monkeypatch):
    from rcagent.catalog.store import CatalogStore
    from rcagent.query import cost
    from rcagent.query.filters import TimeRange
    from rcagent.query.stats import collect

    lt = CatalogStore(database).get_log_table("globctx")
    full = collect(database, lt, TimeRange()).bytes_for(["ts", "message", "service"])
    monkeypatch.setitem(cost.THROUGHPUT_BYTES_PER_S, "local", full / 20.0)  # one full read: 20 s
    monkeypatch.setattr(cost, "BUDGET_SECONDS", 10.0)
    occ = "/tmp/c1_glob_b.parquet#100"
    args = dict(log_table="globctx", occurrence=occ, window_minutes=100_000)
    out = await call(mcp, "get_context", **args)
    assert "TOO EXPENSIVE" in out and "both steps" in out, out
    m = re.search(r"confirmed_cost=(\S+)", out)
    assert m, out
    ran = await call(mcp, "get_context", **args, confirmed_cost=m.group(1))
    assert "→" in ran and "request 10340 handled" in ran and "TOO EXPENSIVE" not in ran, ran
