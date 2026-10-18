"""Cost check, timeouts with cancel, and search_logs (#10), at the MCP tool seam."""

import pytest

from rcagent.query import cost
from rcagent.tools import lookup
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


RG_PATH = "/tmp/t10_fx_rg.parquet"  # FX in three row groups: 2,048 + 2,048 + 904 entries


def _write_fx_rg(db_url: str) -> str:
    import psycopg

    with psycopg.connect(db_url, autocommit=True) as conn:
        conn.execute(f"COPY ({FX}) TO '{RG_PATH}' (FORMAT PARQUET, ROW_GROUP_SIZE 2048)")  # type: ignore[call-overload]
    return RG_PATH


@pytest.fixture
async def fxrg_lt(mcp, db_url):
    path = _write_fx_rg(db_url)
    await call(mcp, "setup_log_table", name="fxrg", source=path)
    return path


def _search_seconds(database, name: str, start=None, end=None, text=None) -> float:
    """What search_logs predicts for an exact run, at the current throughput."""
    from rcagent.catalog.store import CatalogStore
    from rcagent.query.filters import Filters, parse_time_range
    from rcagent.query.stats import collect
    from rcagent.tools.describe import known_columns

    lt = CatalogStore(database).get_log_table(name)
    tr = parse_time_range(start, end)
    stats = collect(database, lt, tr)
    cols = lookup.columns_read(lt, Filters(), known_columns(database, lt), text)
    return stats.bytes_for(cols) / cost.THROUGHPUT_BYTES_PER_S["local"]


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
    from rcagent.catalog.store import CatalogStore
    from rcagent.query.occurrence import decode_occurrence

    out = await call(mcp, "search_logs", log_table="fx", text="disk full", limit=1)
    occ = first_occurrence(out)
    lt = CatalogStore(database).get_log_table("fx")
    where, params = decode_occurrence(lt, occ)
    msg = database.read(f"SELECT message FROM {lt.relation} WHERE {where}", params).scalar()
    assert msg is not None and msg.startswith("disk full on") and msg in out


async def test_search_nothing_matches_says_why(mcp, fx_lt):
    out = await call(mcp, "search_logs", log_table="fx", filters={"level": "error"})
    assert "level='error' matched nothing" in out and "ERROR" in out


async def test_fallback_to_estimate(mcp, fxrg_lt, monkeypatch):
    # Uses the three-row-group file: one row group can't be sampled more cheaply (R39). At 2 KB/s the
    # exact search (count + listing, ~110 KB) takes ~55 s; one row group fits the 30 s budget.
    monkeypatch.setattr(cost, "THROUGHPUT_BYTES_PER_S", {"remote": 1.0, "local": 2e3})
    out = await call(mcp, "search_logs", log_table="fxrg", text="login failed")
    assert "estimated from a sample" in out and "an exact count would read" in out.lower()
    assert "matching entries" in out and "(exact)" not in out
    assert "margin not estimable from 1 block" in out and "±" not in out  # R38: one block, no binomial margin


async def test_value_lookup_estimated_from_blocks(mcp, fxrg_lt, monkeypatch):
    monkeypatch.setattr(cost, "THROUGHPUT_BYTES_PER_S", {"remote": 1.0, "local": 1e1})  # service: ~900 B -> 90 s
    out = await call(mcp, "describe_logs", log_table="fxrg", find_values={"role_or_column": "service", "like": "pay"})
    assert "estimated distinct-value lookup" in out and "block sample of 2,952 of 5,000 entries" in out  # groups 0, 2
    assert "payments: ≈" in out and "margin not estimable from 2 blocks" in out and "±" not in out


async def test_one_row_group_is_never_sampled(mcp, fx_lt, monkeypatch):  # R39
    monkeypatch.setattr(cost, "THROUGHPUT_BYTES_PER_S", {"remote": 1.0, "local": 1e3})
    out = await call(mcp, "search_logs", log_table="fx", text="disk full")
    assert "TOO EXPENSIVE" in out and "estimated" not in out and "an estimate from a sample" not in out


async def test_ranged_sample_comes_from_row_groups_in_the_range(mcp, fxrg_lt, database, monkeypatch):  # R37, R41
    start = "2026-03-01T20:00:00"  # row group 0 ends at 19:19:58: only groups 1 and 2 (2,952 entries) overlap
    monkeypatch.setattr(cost, "BUDGET_SECONDS", 0.9 * _search_seconds(database, "fxrg", start=start, text="disk full"))
    out = await call(mcp, "search_logs", log_table="fxrg", start=start, text="disk full")
    assert "block sample of 2,048 of up to 2,952 entries" in out, out
    assert "estimated from a sample" in out and "showing 0 of" not in out
    assert "2026-03-01 0" not in out and "2026-03-01 1" not in out  # nothing before the range


async def test_beyond_the_server_maximum_is_not_offered(mcp, fx_lt, monkeypatch):  # R40
    monkeypatch.setattr(cost, "THROUGHPUT_BYTES_PER_S", {"remote": 1e-3, "local": 1e-3})
    out = await call(mcp, "search_logs", log_table="fx", text="disk full")
    assert "TOO EXPENSIVE" in out and "confirmed_cost=" not in out
    assert "server's maximum query time (600 s)" in out and "narrow" in out


async def test_malformed_confirmation(mcp, fx_lt, monkeypatch):
    monkeypatch.setattr(cost, "BUDGET_SECONDS", 0.0)
    out = await call(mcp, "search_logs", log_table="fx", text="disk full", confirmed_cost="yes")
    assert "isn't a cost confirmation from this tool" in out and "disk full on" not in out


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

    from rcagent.catalog.store import CatalogStore
    from rcagent.query.occurrence import decode_occurrence

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


async def test_collect_prices_only_row_groups_in_the_range(mcp, fxrg_lt, database):
    from rcagent.catalog.store import CatalogStore
    from rcagent.query.filters import parse_time_range
    from rcagent.query.stats import collect

    lt = CatalogStore(database).get_log_table("fxrg")
    whole = collect(database, lt, parse_time_range(None, None))
    first_hour = collect(database, lt, parse_time_range("2026-03-01T00:00:00", "2026-03-01T01:00:00"))
    assert (whole.total_rows, whole.rows_in_range, whole.rows_exact) == (5000, 5000, True)
    assert [g.rows for g in whole.groups] == [2048, 2048, 904]
    assert first_hour.time_skippable and first_hour.rows_in_range == 2048 and not first_hour.rows_exact
    assert [g.first_row for g in first_hour.groups] == [0]
    assert 0 < first_hour.bytes_for(["message"]) < whole.bytes_for(["message"])
    out = await call(mcp, "search_logs", log_table="fxrg", start="2026-03-01T00:00:00", end="2026-03-01T01:00:00")
    assert "106 matching entries (exact)" in out  # 00:00 to 01:00 every 34 s
    assert "matching entries (exact)" in out and "2026-03-01 00:" in out


# --- database timeouts and cancels (R43, R44) ---


def test_foreign_cancel_is_not_called_a_timeout(database):
    import threading
    import time

    import psycopg

    from rcagent.db import QueryTimeout
    from rcagent.errors import UserFacingError

    pid = database.read("SELECT pg_backend_pid()", {}).scalar()
    url = database.settings.reader_url

    def cancel() -> None:
        time.sleep(1.0)
        with psycopg.connect(url, autocommit=True) as other:
            other.execute("SELECT pg_cancel_backend(%s)", (pid,))

    t = threading.Thread(target=cancel)
    t.start()
    with pytest.raises(UserFacingError) as err:
        database.read("SELECT (SELECT max(hash(i)) FROM range(10000000000) t(i)) > 0", {}, timeout_s=30)
    t.join()
    assert not isinstance(err.value, QueryTimeout) and str(err.value) == "The query was cancelled by the database."
    assert database.read("SELECT 1", {}).scalar() == 1


def test_failed_cancel_falls_back_to_closing_and_is_a_timeout(database, monkeypatch):
    import psycopg

    from rcagent.db import QueryTimeout

    def broken(self, timeout=None):
        raise psycopg.OperationalError("cancel refused")

    monkeypatch.setattr(psycopg.Connection, "cancel_safe", broken)
    with pytest.raises(QueryTimeout, match="TIMEOUT after 1s"):
        database.read("SELECT (SELECT max(hash(i)) FROM range(10000000000) t(i)) > 0", {}, timeout_s=1, what="x")
    assert database.read("SELECT 1", {}).scalar() == 1  # reconnected


async def test_describe_scans_are_cost_checked(mcp, tmp_path, monkeypatch):
    import shutil
    from pathlib import Path

    src = Path(__file__).resolve().parent.parent / "fixtures" / "generic_with_stacktrace.log"
    path = tmp_path / "app.log"
    shutil.copy(src, path)
    await call(mcp, "setup_log_table", name="app", source=str(path))
    monkeypatch.setattr(cost, "BUDGET_SECONDS", 0.0)
    out = await call(mcp, "describe_logs", log_table="app", start="2026-01-01", end="2030-01-01")
    assert out.startswith("How this was measured: ")
    assert "time range: not measured" in out and "entries in" in out and "not counted" in out
    assert "TOO EXPENSIVE" not in out.splitlines()[0]
