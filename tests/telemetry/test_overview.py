from datetime import UTC, datetime

import pytest

from serenedb_extractor.telemetry.registry import TelemetryStore, TraceTable
from tests.conftest import call, container_parquet
from tests.telemetry import fixtures as fx

pytestmark = pytest.mark.db


async def _shop(mcp, db_url):
    logs = container_parquet(db_url, "ov_logs", fx.logs_sql())
    metrics = container_parquet(db_url, "ov_metrics", fx.metrics_sql())
    await call(mcp, "setup_log_table", name="shop_logs", source=logs)
    await call(mcp, "setup_metric_table", name="shop_metrics", source=metrics)


def _line(out: str, service: str) -> str:
    return next(ln for ln in out.splitlines() if ln.startswith(f"{service}:"))


def _block(out: str, service: str) -> str:
    lines = out.splitlines()
    i = next(k for k, ln in enumerate(lines) if ln.startswith(f"{service}:"))
    j = next((k for k in range(i + 1, len(lines)) if lines[k] and not lines[k].startswith(" ")), len(lines))
    return "\n".join(lines[i:j])


async def test_overview_lists_every_service_with_coverage_and_counts(mcp, db_url):
    await _shop(mcp, db_url)
    out = await call(mcp, "telemetry_overview", prefix="shop_", pivot=fx.PIVOT_ISO)
    services = [ln.split(":")[0] for ln in out.splitlines() if ln and not ln.startswith(" ") and ln.split(":")[0] in fx.SERVICES]
    assert services == sorted(fx.SERVICES)
    email = _block(out, "email")
    assert "logs no, metrics yes, traces no" in email and "log entries: none" in email
    assert "metrics: cpu, error, latency, mem" in email
    assert "log entries: 600 before, 720 after (+20.0%)" in _block(out, "cart")
    assert "log entries: 600 before, 600 after (+0.0%)" in _block(out, "frontend")
    assert "tables: shop_logs (logs), shop_metrics (metrics)" in out
    assert "missing entirely: traces" in out
    for word in ("rank", "root cause", "most likely", "suspect"):
        assert word not in out.lower()


async def test_overview_counts_spans_of_a_trace_table(mcp, db_url, database):
    await _shop(mcp, db_url)
    database.write(
        "CREATE TABLE extractor.tt_shop_traces AS SELECT service, start_us FROM (VALUES "
        f"('cart', {(fx.BASE_EPOCH + 30) * 1_000_000}), ('cart', {(fx.BASE_EPOCH + 700) * 1_000_000}), "
        f"('cart', {(fx.BASE_EPOCH + 701) * 1_000_000}), ('payment', {(fx.BASE_EPOCH + 5) * 1_000_000})) v(service, start_us)",
        {},
    )
    TelemetryStore(database).create_trace_table(
        TraceTable(
            name="shop_traces", source="test", source_format="table", relation="extractor.tt_shop_traces",
            trace_id="trace_id", span_id="span_id", parent_span_id=None, service="service", operation="operation",
            start="start_us", start_unit="us", duration="duration_us", duration_unit="us", status=None,
            row_count=4, orphan_spans=0, setup_seconds=0.0, timezone="UTC", created_at=datetime.now(UTC).replace(tzinfo=None),
        )
    )
    out = await call(mcp, "telemetry_overview", prefix="shop_", pivot=fx.PIVOT_ISO)
    # 4 spans from 10:00:05 to 10:11:41 cover little of the window: counts shown, no percent (Q49).
    assert "trace table shop_traces: the data covers only" in out
    assert "spans: 1 before, 2 after (not comparable" in _block(out, "cart")
    assert "spans: 1 before, 0 after (not comparable" in _block(out, "payment")
    assert "spans: none" in _block(out, "email")
    assert "missing entirely" not in out
    assert "coverage: logs yes, metrics yes, traces yes" in _block(out, "cart")


async def test_overview_unknown_prefix(mcp, db_url):
    await _shop(mcp, db_url)
    out = await call(mcp, "telemetry_overview", prefix="nope_", pivot=fx.PIVOT_ISO)
    assert "No log, metric or trace table name starts with 'nope_'" in out
