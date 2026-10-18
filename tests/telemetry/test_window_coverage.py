"""Data that starts just before the pivot: counts before it are missing data, not a quiet baseline (Q49)."""

import pytest

from tests.conftest import call, container_parquet
from tests.telemetry import fixtures as fx

pytestmark = pytest.mark.db

LATE = f"to_timestamp({fx.BASE_EPOCH + fx.PIVOT_S - 3})"  # data starts 3 s before the pivot


@pytest.fixture
async def late(mcp, db_url):
    logs = f"SELECT * FROM ({fx.logs_sql()}) x WHERE ts >= {LATE}"
    traces = f"SELECT * FROM ({fx.traces_sql()}) x WHERE start >= {LATE}"
    await call(mcp, "setup_log_table", name="late_logs", source=container_parquet(db_url, "wc_logs", logs))
    await call(mcp, "setup_trace_table", name="late_traces", source=container_parquet(db_url, "wc_traces", traces))
    return mcp


async def test_overview_says_counts_are_not_comparable(late):
    out = await call(late, "telemetry_overview", prefix="late_", pivot=fx.PIVOT_ISO)
    assert "log table late_logs: the data covers only 3 s of the 600 s before the pivot" in out
    assert "trace table late_traces: the data covers only 3 s" in out
    assert "not comparable" in out and "%)" not in out


async def test_log_volume_leaves_out_minutes_without_data(late):
    out = await call(late, "log_changes", prefix="late_", pivot=fx.PIVOT_ISO)
    assert "the data covers only 3 s of the 600 s before the pivot" in out
    assert "log volume per minute" in out and "too little data (0 minutes before" in out


async def test_trace_volume_leaves_out_minutes_without_data(late):
    out = await call(late, "trace_changes", prefix="late_", pivot=fx.PIVOT_ISO, sort="volume")
    assert "the data covers only 3 s of the 600 s before the pivot" in out


async def test_full_coverage_has_no_note(mcp, db_url):
    await call(mcp, "setup_log_table", name="full_logs", source=container_parquet(db_url, "wc_full", fx.logs_sql()))
    out = await call(mcp, "telemetry_overview", prefix="full_", pivot=fx.PIVOT_ISO)
    assert "covers only" not in out and "(+20.0%)" in out
