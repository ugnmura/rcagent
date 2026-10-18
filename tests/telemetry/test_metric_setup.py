import pytest

from serenedb_extractor.telemetry.common import epoch_us_sql, tables_with_prefix
from serenedb_extractor.telemetry.registry import TelemetryStore
from tests.conftest import call, container_parquet
from tests.telemetry import fixtures as fx

pytestmark = pytest.mark.db


@pytest.fixture
def metrics_path(db_url):
    return container_parquet(db_url, "tm_metrics", fx.metrics_sql())


async def test_setup_metric_table_reads_in_place_and_reports(mcp, metrics_path):
    out = await call(mcp, "setup_metric_table", name="shop_metrics", source=metrics_path)
    assert "read in place" in out and "View extractor.mt_shop_metrics" in out
    assert f"rows: {fx.SECONDS * 5 * 4:,}" in out
    assert "time range (UTC): 2026-03-01 10:00:00 to 2026-03-01 10:19:59" in out
    assert "services (5): cart, checkout, email, frontend, payment" in out
    assert "metric names (4): cpu, error, latency, mem" in out
    assert "timestamp: ts" in out and "service: service" in out and "value: value" in out


async def test_registered_and_found_by_prefix(mcp, metrics_path, database):
    await call(mcp, "setup_metric_table", name="shop_metrics", source=metrics_path)
    [mt] = TelemetryStore(database).list_metric_tables()
    assert (mt.relation, mt.metric, mt.timestamp_unit, mt.row_count) == ("extractor.mt_shop_metrics", "metric", None, 24000)
    log_path = container_parquet(database.settings.reader_url, "tm_logs", fx.logs_sql())
    await call(mcp, "setup_log_table", name="shop_logs", source=log_path)

    class Ctx:
        db = database
        from serenedb_extractor.catalog.store import CatalogStore

        store = CatalogStore(database)

    found = tables_with_prefix(Ctx(), "shop_")  # type: ignore[arg-type]
    assert found.names == ["shop_logs", "shop_metrics"]


@pytest.mark.parametrize("unit", ["s", "ms", "us", "ns"])
async def test_integer_epoch_unit_is_guessed(mcp, db_url, unit):
    path = container_parquet(db_url, f"tm_epoch_{unit}", fx.metrics_sql(epoch_unit=unit))
    out = await call(mcp, "setup_metric_table", name=f"e_{unit}", source=path)
    assert f"timestamp_unit: {unit}  (guessed from the magnitude" in out
    assert "time range (UTC): 2026-03-01 10:00:00 to 2026-03-01 10:19:59" in out


async def test_given_unit_wins(mcp, db_url):
    path = container_parquet(db_url, "tm_epoch_given", fx.metrics_sql(epoch_unit="ms"))
    out = await call(mcp, "setup_metric_table", name="e_given", source=path, roles={"timestamp_unit": "ms"})
    assert "timestamp_unit: ms" in out and "guessed" not in out


async def test_wide_file_is_refused_with_a_hint(mcp, db_url):
    path = container_parquet(db_url, "tm_wide", fx.wide_metrics_sql())
    out = await call(mcp, "setup_metric_table", name="wide", source=path)
    assert "long format" in out and "UNPIVOT" in out


async def test_names_are_one_namespace_across_kinds(mcp, metrics_path, db_url):
    log_path = container_parquet(db_url, "tm_logs2", fx.logs_sql())
    await call(mcp, "setup_log_table", name="shop", source=log_path)
    out = await call(mcp, "setup_metric_table", name="shop", source=metrics_path)
    assert "already used" in out


async def test_log_tools_are_unchanged_by_a_metric_table(mcp, metrics_path):
    await call(mcp, "setup_metric_table", name="shop_metrics", source=metrics_path)
    assert "no log tables yet" in await call(mcp, "describe_logs")


def test_epoch_sql_shapes():
    assert epoch_us_sql('"ts"', "TIMESTAMP WITH TIME ZONE", None) == 'epoch_us("ts")'
    assert epoch_us_sql('"ts"', "TIMESTAMP", None, "Europe/Berlin") == "epoch_us(\"ts\" AT TIME ZONE 'Europe/Berlin')"
    assert epoch_us_sql('"ts"', "BIGINT", "ns") == '(CAST("ts" AS BIGINT) // 1000)'
