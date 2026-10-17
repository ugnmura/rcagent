from datetime import UTC, datetime

import pytest

from serenedb_extractor.catalog.models import FieldRoles, LogTable
from serenedb_extractor.errors import UserFacingError
from serenedb_extractor.query import cost
from serenedb_extractor.tools.investigate import parse_group_by
from tests.conftest import call, container_parquet, id_of
from tests.fixtures.data import FX
from tests.fixtures.data_t13 import BIG

pytestmark = pytest.mark.db


@pytest.fixture
async def fx_lt(mcp, db_url):
    path = container_parquet(db_url, "fx", FX)
    await call(mcp, "setup_log_table", name="fx", source=path)
    return path


@pytest.fixture
async def fx_surveyed(mcp, fx_lt):
    out = await call(mcp, "survey", log_table="fx")
    return {
        "timeout": id_of(out, "timeout after <NUM>ms calling payments"),
        "login": id_of(out, "login failed for user <*>"),
        "disk": id_of(out, "disk full on <PATH>"),
    }


async def test_exact_by_service(mcp, fx_surveyed):
    out = await call(mcp, "locate_occurrences", log_table="fx", templates=[fx_surveyed["timeout"]], group_by=["service"])
    assert "payments: 3,000" in out and "≈" not in out and "fx.parquet#" in out
    assert out.startswith("How this was measured: ")


async def test_time_bucket(mcp, fx_surveyed):
    out = await call(mcp, "locate_occurrences", log_table="fx", templates=[fx_surveyed["timeout"]], group_by=["time:1d"])
    assert "2026-03-01" in out and "2026-03-02" in out


async def test_group_by_column_and_hour_bucket(mcp, fx_surveyed):
    out = await call(mcp, "locate_occurrences", log_table="fx", templates=[fx_surveyed["login"]], group_by=["component", "time:6h"])
    assert "login, 2026-03-01 00:00" in out
    assert "1,500" not in out or "≈" not in out  # exact


async def test_two_templates_no_double_count(mcp, fx_surveyed):
    ids = [fx_surveyed["timeout"], fx_surveyed["disk"]]
    out = await call(mcp, "locate_occurrences", log_table="fx", templates=ids)
    assert "3,000" in out and ": 30" in out and "counted under the first one" in out


async def test_requires_template(mcp, fx_lt):
    assert "run a survey first" in await call(mcp, "locate_occurrences", log_table="fx", templates=[])


async def test_unknown_template(mcp, fx_surveyed):
    out = await call(mcp, "locate_occurrences", log_table="fx", templates=["T99"])
    assert "no template 'T99'" in out


async def test_bad_group_by(mcp, fx_surveyed):
    out = await call(mcp, "locate_occurrences", log_table="fx", templates=[fx_surveyed["timeout"]], group_by=["nosuch"])
    assert "nosuch" in out and "Traceback" not in out


async def test_word_param(mcp, fx_surveyed):
    out = await call(mcp, "extract_params", log_table="fx", template=fx_surveyed["login"])
    assert "showing 10 of 50" in out and "user0" in out


async def test_numeric_param(mcp, fx_surveyed):
    out = await call(mcp, "extract_params", log_table="fx", template=fx_surveyed["timeout"])
    assert all(k in out for k in ("min", "p50", "p95", "max"))
    assert "min 100" in out and "max 999" in out


async def test_param_by_service(mcp, fx_surveyed):
    out = await call(mcp, "extract_params", log_table="fx", template=fx_surveyed["timeout"], by="service")
    assert "payments" in out and "3,000" in out


async def test_cost_check_asks(mcp, fx_surveyed, monkeypatch):
    monkeypatch.setattr(cost, "BUDGET_SECONDS", 0.0)
    out = await call(mcp, "locate_occurrences", log_table="fx", templates=[fx_surveyed["timeout"]])
    assert "TOO EXPENSIVE" in out and "confirmed_cost=" in out
    out = await call(mcp, "extract_params", log_table="fx", template=fx_surveyed["timeout"])
    assert "TOO EXPENSIVE" in out


def _lt() -> LogTable:
    r = FieldRoles(message="message", timestamp="ts", service="service", level="level")
    now = datetime.now(UTC)
    return LogTable("fx", "/x.parquet", "parquet", "in_place", "read_parquet('/x.parquet')", r, None, None, None, "UTC", now, now)


COLS = {"ts": "TIMESTAMP WITH TIME ZONE", "service": "VARCHAR", "message": "VARCHAR", "level": "VARCHAR"}


def test_parse_group_by_labels():
    got = parse_group_by(_lt(), ["service", "time:15m", "level"], COLS)
    assert [g[0] for g in got] == ["service", "time:15m", "level"]


@pytest.mark.parametrize("bad", ["time:0m", "time:5x", "time:", "nosuch"])
def test_parse_group_by_rejects(bad):
    with pytest.raises(UserFacingError):
        parse_group_by(_lt(), [bad], COLS)



@pytest.fixture
async def big_surveyed(mcp, db_url):
    import psycopg

    with psycopg.connect(db_url, autocommit=True) as conn:
        conn.execute(f"COPY ({BIG}) TO '/tmp/big13.parquet' (FORMAT PARQUET, ROW_GROUP_SIZE 2000)")  # type: ignore[call-overload]
    await call(mcp, "setup_log_table", name="big", source="/tmp/big13.parquet")
    out = await call(mcp, "survey", log_table="big")
    return id_of(out, "timeout after <NUM>ms calling payments")


def _force_sampling(monkeypatch, database):
    from serenedb_extractor.catalog.store import CatalogStore
    from serenedb_extractor.query.filters import TimeRange
    from serenedb_extractor.query.stats import collect

    lt = CatalogStore(database).get_log_table("big")
    exact_bytes = collect(database, lt, TimeRange()).bytes_for(["message", "ts", "message", "ts"])
    monkeypatch.setitem(cost.THROUGHPUT_BYTES_PER_S, "local", 1.0)
    monkeypatch.setattr(cost, "BUDGET_SECONDS", exact_bytes * 0.6)


async def test_estimate_fallback_labelled(mcp, big_surveyed, database, monkeypatch):
    _force_sampling(monkeypatch, database)
    out = await call(mcp, "locate_occurrences", log_table="big", templates=[big_surveyed], group_by=["service"])
    assert "≈" in out and "estimated" in out and "block sample" in out and "payments:" in out
    ex = await call(mcp, "extract_params", log_table="big", template=big_surveyed)
    assert "estimated" in ex and "min" in ex and "from the sample" in ex

