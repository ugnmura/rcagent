"""search_logs counts and picks the newest (or oldest) entries in one scan (count(*) with arg_max/arg_min,
S6 perf): the order must equal ORDER BY timestamp, order role with NULLS LAST, ties included, and entries
without a timestamp still come last."""

import re

import pytest

from tests.conftest import call, container_parquet

# entry-00 .. entry-09: three entries per second (ties broken by file order), then two without a timestamp.
DATA = """
SELECT * FROM (
  SELECT TIMESTAMPTZ '2026-05-01 10:00:00+00' + (i // 3) * INTERVAL '1 second' AS ts,
         'INFO' AS level, 'entry-' || lpad(i::VARCHAR, 2, '0') || ' done' AS message
  FROM range(0, 10) t(i)
  UNION ALL
  SELECT NULL::TIMESTAMPTZ, 'INFO', 'entry-n' || k::VARCHAR || ' done' FROM range(0, 2) u(k)
) ORDER BY ts NULLS LAST, message
"""


def _shown(out: str) -> list[str]:
    return re.findall(r"entry-(\w+) done", out.split("(exact)", 1)[1])


@pytest.fixture
async def onescan(mcp, db_url):
    path = container_parquet(db_url, "onescan_data", DATA)
    out = await call(mcp, "setup_log_table", name="onescan", source=path)
    assert "Set up log table" in out, out


@pytest.mark.db
async def test_newest_and_oldest_match_order_by(mcp, onescan):
    out = await call(mcp, "search_logs", log_table="onescan", text="done", limit=4)
    assert "12 matching entries (exact)" in out, out
    assert _shown(out) == ["09", "08", "07", "06"], out
    out = await call(mcp, "search_logs", log_table="onescan", text="done", order="oldest", limit=4)
    assert _shown(out) == ["00", "01", "02", "03"], out


@pytest.mark.db
async def test_entries_without_time_still_come_last(mcp, onescan):
    out = await call(mcp, "search_logs", log_table="onescan", text="done", limit=20)
    assert "12 matching entries (exact)" in out, out
    assert _shown(out) == ["09", "08", "07", "06", "05", "04", "03", "02", "01", "00", "n1", "n0"], out


@pytest.mark.db
async def test_no_match_counts_zero(mcp, onescan):
    out = await call(mcp, "search_logs", log_table="onescan", text="nothing-like-this")
    assert "0 matching entries" in out or "No entries" in out or "no entries" in out, out
