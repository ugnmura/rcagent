import re

import pytest

from tests.conftest import call, container_parquet
from tests.telemetry import fixtures as fx

pytestmark = pytest.mark.db


@pytest.fixture
async def shop(mcp, db_url):
    path = container_parquet(db_url, "tm_a2_metrics", fx.metrics_sql())
    await call(mcp, "setup_metric_table", name="shop_metrics", source=path)
    return mcp


def ranked(out: str) -> list[tuple[str, str, float]]:
    """(service, metric, z) of the ranked section, in order."""
    section = out.split("largest changes", 1)[1].split("\n\n", 1)[0]
    return [
        (m.group(1), m.group(2), float(m.group(3)))
        for m in re.finditer(r"^  (\S+) / (\S+): median .*? z ([+-][\d.]+)", section, re.M)
    ]


def section(out: str, title: str) -> str:
    return out.split(title, 1)[1].split("\n\n", 1)[0]


async def test_cart_cpu_is_the_top_series(shop):
    out = await call(shop, "metric_changes", prefix="shop_", pivot=fx.PIVOT_ISO)
    assert out.startswith("How this was measured: ")
    assert "baseline 2026-03-01 10:00:00 to 2026-03-01 10:10:00" in out
    rows = ranked(out)
    assert rows[0][:2] == ("cart", "cpu") and rows[0][2] > 10
    fe = [z for s, m, z in rows if (s, m) == ("frontend", "latency")]
    assert fe and 0 < fe[0] < rows[0][2]
    assert "median 0.22 -> 0.82" in out


async def test_rose_from_zero_is_its_own_group(shop):
    out = await call(shop, "metric_changes", prefix="shop_", pivot=fx.PIVOT_ISO)
    assert ("email", "error") not in [r[:2] for r in ranked(out)]
    assert "email / error" in section(out, "rose from zero")


async def test_per_service_max_and_coverage(shop):
    out = await call(shop, "metric_changes", prefix="shop_", pivot=fx.PIVOT_ISO)
    per = section(out, "largest change per service")
    assert "not a cause ranking" in per
    assert re.search(r"^  cart: \|z\| [\d.]+ \(cpu\)", per, re.M)
    assert "cart: logs no, metrics yes, traces no" in out


async def test_services_and_metrics_filters(shop):
    out = await call(shop, "metric_changes", prefix="shop_", pivot=fx.PIVOT_ISO, services=["frontend"])
    assert {s for s, _, _ in ranked(out)} == {"frontend"}
    out = await call(shop, "metric_changes", prefix="shop_", pivot=fx.PIVOT_ISO, metrics=["mem", "latency"])
    assert {m for _, m, _ in ranked(out)} == {"mem", "latency"}
    assert ranked(out)[0][:2] == ("frontend", "latency")


async def test_sort_by_peak(shop):
    out = await call(shop, "metric_changes", prefix="shop_", pivot=fx.PIVOT_ISO, sort="peak", top=3)
    assert "by |peak z|" in out
    assert ranked(out)[0][:2] == ("cart", "cpu") and len(ranked(out)) == 3


async def test_table_instead_of_prefix(shop):
    out = await call(shop, "metric_changes", table="shop_metrics", pivot=fx.PIVOT_ISO)
    assert ranked(out)[0][:2] == ("cart", "cpu")
    assert "coverage needs a prefix" in out


async def test_exactly_one_of_prefix_and_table(shop):
    out = await call(shop, "metric_changes", pivot=fx.PIVOT_ISO)
    assert "prefix or table" in out
    out = await call(shop, "metric_changes", prefix="shop_", table="shop_metrics", pivot=fx.PIVOT_ISO)
    assert "prefix or table" in out


async def test_prefix_without_metric_tables(shop, db_url):
    out = await call(shop, "metric_changes", prefix="nope_", pivot=fx.PIVOT_ISO)
    assert "No log, metric or trace table name starts with 'nope_'" in out
    log_path = container_parquet(db_url, "tm_a2_logs", fx.logs_sql())
    await call(shop, "setup_log_table", name="web_logs", source=log_path)
    out = await call(shop, "metric_changes", prefix="web_", pivot=fx.PIVOT_ISO)
    assert "No metric table name starts with 'web_'" in out and "web_logs" in out


async def test_too_narrow_window_is_too_little_data(shop):
    out = await call(shop, "metric_changes", prefix="shop_", pivot=fx.PIVOT_ISO, before_minutes=0.05)
    assert "too little data" in out
    assert re.search(r"too little data .*: 20 series", out)
    assert ranked(out) == []


async def test_integer_epoch_gives_the_same_top_series(mcp, db_url):
    path = container_parquet(db_url, "tm_a2_epoch_ms", fx.metrics_sql(epoch_unit="ms"))
    await call(mcp, "setup_metric_table", name="ep_metrics", source=path)
    out = await call(mcp, "metric_changes", prefix="ep_", pivot=fx.PIVOT_ISO)
    assert ranked(out)[0][:2] == ("cart", "cpu") and ranked(out)[0][2] > 10


async def test_metric_series_shows_the_step(shop):
    out = await call(
        shop, "metric_series", table="shop_metrics", services=["cart"], metrics=["cpu"],
        start=fx.START_ISO, end="2026-03-01T10:20:00Z",
    )
    assert out.startswith("How this was measured: ")
    assert "cart / cpu (40 buckets of 30 s)" in out
    lines = re.findall(r"^  (\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)  min (\S+)  median (\S+)  max (\S+)", out, re.M)
    assert len(lines) == 40
    by_time = {t: float(med) for t, _, med, _ in lines}
    assert by_time["2026-03-01 10:09:30"] < 0.3 and by_time["2026-03-01 10:10:00"] > 0.7


async def test_metric_series_caps_rows(shop):
    out = await call(shop, "metric_series", table="shop_metrics", start=fx.START_ISO, end="2026-03-01T10:20:00Z")
    assert "rows cut" in out
