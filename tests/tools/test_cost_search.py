"""Cost check, timeouts with cancel, and search_logs (#10), at the MCP tool seam."""

import pytest

from serenedb_extractor.query import cost
from serenedb_extractor.tools import lookup
from tests.conftest import call, container_parquet, first_occurrence, token_of
from tests.fixtures.data import FX

pytestmark = pytest.mark.db

# Own file name so parallel agents writing /tmp/fx.parquet in the shared container don't collide;
# it still ends in "fx.parquet", which is what the occurrence-ID assertions look for.
FX_FILE = "t10_fx"


@pytest.fixture
async def fx_lt(mcp, db_url):
    path = container_parquet(db_url, FX_FILE, FX)
    await call(mcp, "setup_log_table", name="fx", source=path)
    return path


@pytest.fixture
async def fx_lt_short(mcp_short_timeout, db_url):
    path = container_parquet(db_url, FX_FILE, FX)
    out = await call(mcp_short_timeout, "setup_log_table", name="fx", source=path)
    assert "Set up log table" in out, out
    return path


async def test_search_exact(mcp, fx_lt):
    out = await call(mcp, "search_logs", log_table="fx", text="disk full")
    assert out.startswith("How this was measured: ")
    assert "disk full on" in out and "fx.parquet#" in out and "≈" not in out
    assert "30 matching entries (exact)" in out
    assert "service=checkout" in out and "level=ERROR" in out and "2026-03-0" in out


async def test_search_filters_order_and_cut(mcp, fx_lt):
    out = await call(mcp, "search_logs", log_table="fx", filters={"service": "auth"}, order="oldest", limit=5)
    assert "1,500 matching entries (exact)" in out and "showing 5 of 1,500 entries" in out
    assert "login failed for user" in out and "disk full" not in out
    lines = [ln for ln in out.splitlines() if "login failed" in ln]
    assert len(lines) == 5 and lines == sorted(lines)  # oldest first: timestamps lead each line


async def test_search_occurrence_id_finds_the_entry_again(mcp, fx_lt, database):
    from serenedb_extractor.catalog.store import CatalogStore
    from serenedb_extractor.query.occurrence import decode_occurrence

    out = await call(mcp, "search_logs", log_table="fx", text="disk full", limit=1)
    occ = first_occurrence(out)
    lt = CatalogStore(database).get_log_table("fx")
    where, params = decode_occurrence(lt, occ)
    msg = database.read(f"SELECT message FROM {lt.relation} WHERE {where}", params).scalar()
    assert msg is not None and msg.startswith("disk full on") and msg in out


async def test_search_nothing_matches_says_why(mcp, fx_lt):
    out = await call(mcp, "search_logs", log_table="fx", filters={"level": "error"})
    assert "level='error' matched nothing" in out and "ERROR" in out


async def test_fallback_to_estimate(mcp, fx_lt, monkeypatch):
    monkeypatch.setattr(cost, "THROUGHPUT_BYTES_PER_S", {"remote": 1.0, "local": 1e3})
    out = await call(mcp, "search_logs", log_table="fx", text="disk full")
    assert "estimated from a sample" in out and "an exact count would read" in out.lower()
    assert "matching entries" in out and "(exact)" not in out


async def test_ask_then_confirm(mcp, fx_lt, monkeypatch):
    monkeypatch.setattr(cost, "BUDGET_SECONDS", 0.0)
    ask = await call(mcp, "search_logs", log_table="fx", text="disk full")
    assert "TOO EXPENSIVE" in ask and "confirmed_cost=" in ask and "search index" in ask
    assert "disk full on" not in ask  # nothing was run
    ok = await call(mcp, "search_logs", log_table="fx", text="disk full", confirmed_cost=token_of(ask))
    assert "disk full on" in ok and "30 matching entries (exact)" in ok


async def test_stale_confirmation_asks_again(mcp, fx_lt, monkeypatch):
    monkeypatch.setattr(cost, "BUDGET_SECONDS", 0.0)
    out = await call(mcp, "search_logs", log_table="fx", text="disk full", confirmed_cost="900TB")
    assert "TOO EXPENSIVE" in out and "does not match" in out and "disk full on" not in out


async def test_timeout_cancels_and_recovers(mcp_short_timeout, fx_lt_short, monkeypatch):
    # max(hash(i)) really scans the range; the brief's count(*) form is answered in under a second here.
    monkeypatch.setattr(lookup, "SEARCH_SQL_SUFFIX", " AND (SELECT max(hash(i)) FROM range(10000000000) t(i)) > 0")
    out = await call(mcp_short_timeout, "search_logs", log_table="fx", text="disk")
    assert out.startswith("TIMEOUT after 1s") and "narrow" in out
    monkeypatch.setattr(lookup, "SEARCH_SQL_SUFFIX", "")
    assert "disk full on" in await call(mcp_short_timeout, "search_logs", log_table="fx", text="disk full")


async def test_fuzzy_needs_index(mcp, fx_lt):
    assert "needs a search index" in await call(mcp, "search_logs", log_table="fx", text="dsik", fuzzy=True)


async def test_value_lookup_cost_checked(mcp, fx_lt, monkeypatch):
    monkeypatch.setattr(cost, "BUDGET_SECONDS", 0.0)
    out = await call(mcp, "describe_logs", log_table="fx", find_values={"role_or_column": "service", "like": "pay"})
    assert "TOO EXPENSIVE" in out and "payments" not in out
    ok = await call(
        mcp, "describe_logs", log_table="fx", find_values={"role_or_column": "service", "like": "pay"},
        confirmed_cost=token_of(out),
    )
    assert "payments (3,000)" in ok


async def test_search_tool_is_read_only(mcp_no_db):
    tools = {t.name: t for t in (await mcp_no_db.list_tools()).tools}
    assert tools["search_logs"].annotations.readOnlyHint is True


async def test_search_copied_table_uses_entry_ids(mcp, tmp_path, database):
    import shutil
    from pathlib import Path

    from serenedb_extractor.catalog.store import CatalogStore
    from serenedb_extractor.query.occurrence import decode_occurrence

    src = Path(__file__).resolve().parent.parent / "fixtures" / "generic_with_stacktrace.log"
    path = tmp_path / "app.log"
    shutil.copy(src, path)
    assert "Set up log table" in await call(mcp, "setup_log_table", name="app", source=str(path))
    out = await call(mcp, "search_logs", log_table="app", text="refund failed")
    occ = first_occurrence(out)
    assert occ.startswith("e:") and "1 matching entry (exact)" in out and "component=payments" in out
    lt = CatalogStore(database).get_log_table("app")
    where, params = decode_occurrence(lt, occ)
    assert "refund failed" in database.read(f"SELECT message FROM {lt.relation} WHERE {where}", params).scalar()


async def test_collect_prices_only_row_groups_in_the_range(mcp, db_url, database):
    import psycopg

    from serenedb_extractor.catalog.store import CatalogStore
    from serenedb_extractor.query.filters import parse_time_range
    from serenedb_extractor.query.stats import collect

    path = "/tmp/t10_fx_rg.parquet"  # three row groups: 2,048 + 2,048 + 904 entries
    with psycopg.connect(db_url, autocommit=True) as conn:
        conn.execute(f"COPY ({FX}) TO '{path}' (FORMAT PARQUET, ROW_GROUP_SIZE 2048)")  # type: ignore[call-overload]
    await call(mcp, "setup_log_table", name="fxrg", source=path)
    lt = CatalogStore(database).get_log_table("fxrg")
    whole = collect(database, lt, parse_time_range(None, None))
    first_hour = collect(database, lt, parse_time_range("2026-03-01T00:00:00", "2026-03-01T01:00:00"))
    assert (whole.total_rows, whole.rows_in_range, whole.file_rows) == (5000, 5000, (5000,))
    assert first_hour.time_skippable and first_hour.rows_in_range == 2048
    assert 0 < first_hour.bytes_for(["message"]) < whole.bytes_for(["message"])
    out = await call(mcp, "search_logs", log_table="fxrg", start="2026-03-01T00:00:00", end="2026-03-01T01:00:00")
    assert "matching entries (exact)" in out and "2026-03-01 00:" in out
