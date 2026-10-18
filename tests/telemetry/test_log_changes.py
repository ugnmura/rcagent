import re

import pytest

from tests.conftest import call, container_parquet
from tests.telemetry import fixtures as fx

pytestmark = pytest.mark.db


async def _shop(mcp, db_url, scenario="cart_fault"):
    logs = container_parquet(db_url, f"lc_logs_{scenario}", fx.logs_sql(scenario))
    metrics = container_parquet(db_url, f"lc_metrics_{scenario}", fx.metrics_sql(scenario))
    await call(mcp, "setup_log_table", name="shop_logs", source=logs)
    await call(mcp, "setup_metric_table", name="shop_metrics", source=metrics)


def _section(out: str, service: str) -> str:
    """The lines of one service's section (from 'service <name>' to the next 'service ' header)."""
    m = re.search(rf"^service {service}\b.*?(?=^service |\Z)", out, re.S | re.M)
    assert m, out
    return m.group(0)


async def test_new_template_after_the_pivot_is_counted_exactly(mcp, db_url):
    await _shop(mcp, db_url)
    out = await call(mcp, "log_changes", prefix="shop_", pivot=fx.PIVOT_ISO)
    cart = _section(out, "cart")
    assert "new after the pivot" in cart
    line = next(ln for ln in cart.splitlines() if "OutOfMemoryError" in ln and "0 before" in ln)
    assert "120 after" in line
    for svc in ("frontend", "checkout"):
        assert "new after the pivot: none" in _section(out, svc)
    rate = next(ln for ln in cart.splitlines() if "error-ish rate" in ln)
    assert "0.0% (0 of 600) before" in rate and "16.7% (120 of 720) after" in rate


async def test_shows_coverage_window_and_volume(mcp, db_url):
    await _shop(mcp, db_url)
    out = await call(mcp, "log_changes", prefix="shop_", pivot=fx.PIVOT_ISO)
    assert "2026-03-01 10:00:00 to 2026-03-01 10:10:00" in out
    assert "coverage" in out and "email: logs no, metrics yes, traces no" in out
    assert "log volume per minute" in _section(out, "cart")
    assert "root cause" not in out.lower()


async def test_by_log_table_and_service_filter(mcp, db_url):
    await _shop(mcp, db_url)
    out = await call(mcp, "log_changes", log_table="shop_logs", pivot=fx.PIVOT_ISO, services=["cart"])
    assert "service cart" in out and "service frontend" not in out


async def test_no_change_scenario_has_no_new_templates(mcp, db_url):
    await _shop(mcp, db_url, "network_delay")
    out = await call(mcp, "log_changes", prefix="shop_", pivot=fx.PIVOT_ISO)
    assert "OutOfMemoryError" not in out
    assert out.count("new after the pivot: none") == 3


async def test_needs_the_service_role(mcp, db_url):
    path = container_parquet(db_url, "lc_nosvc", f"SELECT ts, level, message FROM ({fx.logs_sql()})")
    await call(mcp, "setup_log_table", name="plain_logs", source=path, roles={"service": None})
    out = await call(mcp, "log_changes", log_table="plain_logs", pivot=fx.PIVOT_ISO)
    assert "service" in out and "setup_log_table" in out
