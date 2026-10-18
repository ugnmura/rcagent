"""A log table's own time zone through the MCP tools: BGL is read and shown as US Pacific time,
with UTC offsets, and UTC stays available on request."""

import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest

from tests.conftest import call, first_occurrence

pytestmark = pytest.mark.db

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
FIRST = "2005-06-03 15:42:50"  # the first BGL fixture line's local time; its epoch field says 22:42:50 UTC


@pytest.fixture
async def bgl(mcp, tmp_path):
    dest = tmp_path / "bgl_sample.log"
    shutil.copy(FIXTURES / "bgl_sample.log", dest)
    return await call(mcp, "setup_log_table", name="bgl", source=str(dest))


async def test_setup_reads_bgl_as_us_pacific_and_stores_the_real_instant(bgl, database):
    assert "time zone for timestamps without one: America/Los_Angeles (the bgl line format's" in bgl
    first = database.read("SELECT ts FROM extractor.lt_bgl ORDER BY entry_id LIMIT 1").scalar()
    assert first == datetime(2005, 6, 3, 22, 42, 50, 675872, tzinfo=UTC)
    assert database.read("SELECT timezone FROM extractor.log_tables WHERE name = 'bgl'").scalar() == "America/Los_Angeles"


async def test_results_show_the_tables_own_zone_with_offsets(mcp, bgl):
    out = await call(mcp, "describe_logs", log_table="bgl")
    assert "time zone: America/Los_Angeles" in out and f"time range: {FIRST}-07:00 to " in out
    out = await call(mcp, "search_logs", log_table="bgl", order="oldest", limit=1)
    assert "times in America/Los_Angeles (not UTC)" in out and f"{FIRST}-07:00" in out
    occ = first_occurrence(out)
    assert f"{FIRST}-07:00" in await call(mcp, "get_context", log_table="bgl", occurrence=occ)


async def test_times_given_without_a_zone_are_the_logs_local_time(mcp, bgl):
    # 15:42:50 local is in the hour from 15:00 local, which is 22:00 UTC.
    local = await call(mcp, "search_logs", log_table="bgl", start="2005-06-03T15:00:00", end="2005-06-03T16:00:00")
    in_utc = await call(
        mcp, "search_logs", log_table="bgl", start="2005-06-03T22:00:00", end="2005-06-03T23:00:00", timezone="UTC"
    )
    assert f"{FIRST}-07:00" in local and "2005-06-03 22:42:50" in in_utc and "times in UTC" in in_utc


async def test_run_sql_reads_times_in_the_tables_zone(mcp, bgl):
    out = await call(
        mcp, "run_sql",
        sql="SELECT min(ts) AS first, min(ts)::date AS day, sum(CASE WHEN ts < '2005-06-04' THEN 1 ELSE 0 END) AS on_day_one "
        "FROM extractor.lt_bgl",
    )
    assert "times in America/Los_Angeles (not UTC), the time zone of bgl" in out
    assert "2005-06-03 15:42:50.675872-07:00 | 2005-06-03 | 8" in out
    assert "time zone of" not in await call(mcp, "run_sql", sql="SELECT 1 AS one")  # no log table, no zone
    out = await call(mcp, "run_sql", sql="SELECT min(ts) AT TIME ZONE 'UTC' AS first_utc FROM extractor.lt_bgl")
    assert "2005-06-03 22:42:50.675872" in out
