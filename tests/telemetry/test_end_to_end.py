"""All telemetry tools together on one system (prefix shop_), the way an agent would use them."""

import pytest

from tests.conftest import call, container_parquet
from tests.telemetry import fixtures as fx

pytestmark = pytest.mark.db


@pytest.fixture
async def shop(mcp, db_url):
    await call(mcp, "setup_log_table", name="shop_logs", source=container_parquet(db_url, "e2e_logs", fx.logs_sql()))
    await call(mcp, "setup_metric_table", name="shop_metrics", source=container_parquet(db_url, "e2e_metrics", fx.metrics_sql()))
    await call(mcp, "setup_trace_table", name="shop_traces", source=container_parquet(db_url, "e2e_traces", fx.traces_sql()))
    return mcp


async def test_every_tool_points_at_cart_without_naming_a_cause(shop):
    overview = await call(shop, "telemetry_overview", prefix="shop_", pivot=fx.PIVOT_ISO)
    assert "email:\n  coverage: logs no, metrics yes, traces no" in overview
    assert "root cause" not in overview.lower()
    metrics = await call(shop, "metric_changes", prefix="shop_", pivot=fx.PIVOT_ISO)
    traces = await call(shop, "trace_changes", prefix="shop_", pivot=fx.PIVOT_ISO)
    logs = await call(shop, "log_changes", prefix="shop_", pivot=fx.PIVOT_ISO)
    for out in (metrics, traces, logs):
        assert "cart" in out and "root cause" not in out.lower()
    assert "OutOfMemoryError" in logs
    tree = await call(shop, "get_trace", table="shop_traces", trace_id="t700")
    assert "/GetCart" in tree and "/Charge" in tree


async def test_log_tools_still_see_only_log_tables(shop):
    out = await call(shop, "describe_logs")
    assert "shop_logs" in out and "shop_metrics" not in out and "shop_traces" not in out
