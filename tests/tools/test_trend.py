"""trend (#15): templates over a period against the preceding period of equal length."""

import re

import pytest
import pytest_asyncio

from serenedb_extractor.config import Settings  # noqa: F401
from serenedb_extractor.context import AppContext
from serenedb_extractor.server import build_server  # noqa: F401
from serenedb_extractor.tools import trend as trend_tool
from tests.conftest import _client, _reset_schema, _settings, call, container_parquet, id_of
from tests.fixtures.data_t15 import T_DAILY_TEXT, T_ONCE_TEXT, T_RISE_TEXT, TREND

pytestmark = pytest.mark.db

RG_PATH = "/tmp/t15_trend_rg.parquet"  # ~28,000 entries in row groups of 2,048


def _write_trend(db_url: str) -> str:
    import psycopg

    with psycopg.connect(db_url, autocommit=True) as conn:
        conn.execute(f"COPY ({TREND}) TO '{RG_PATH}' (FORMAT PARQUET, ROW_GROUP_SIZE 2048)")  # type: ignore[call-overload]
    return RG_PATH


async def _setup(client, db_url):
    await call(client, "setup_log_table", name="tr", source=_write_trend(db_url))
    out = await call(client, "survey", log_table="tr")
    return {
        "rise": id_of(out, T_RISE_TEXT),
        "daily": id_of(out, T_DAILY_TEXT),
        "once": id_of(out, T_ONCE_TEXT),
    }


@pytest_asyncio.fixture
async def trend_lt(mcp, db_url):
    return await _setup(mcp, db_url)


@pytest_asyncio.fixture
async def small_sample_lt(db_url):
    """A server whose sample size is small, so the ~28,000 entries are worth sampling."""
    _reset_schema(db_url)
    settings = _settings(db_url, sample_size=300)
    async for c in _client(lambda: AppContext.from_settings(settings)):
        yield c, await _setup(c, db_url)


P = {"start": "2026-03-15", "end": "2026-03-29"}


async def test_estimated_default(small_sample_lt, monkeypatch):
    client, ids = small_sample_lt
    monkeypatch.setattr(trend_tool, "MIN_BUCKET_SAMPLE", 500)
    out = await call(client, "trend", log_table="tr", templates=[ids["rise"]], **P)
    assert out.startswith("How this was measured: ")
    assert "≈" in out and "estimated" in out and "UTC" in out
    assert "exact" not in out.split("\n")[0].lower().replace("an exact", "")  # the head claims no exactness


async def test_default_on_small_scope_is_exact_and_says_so(mcp, trend_lt):
    out = await call(mcp, "trend", log_table="tr", templates=[trend_lt["rise"]], **P)
    assert "≈" not in out and "(exact)" in out and "+100%" in out


async def test_exact_change_and_presence(mcp, trend_lt):
    ids = [trend_lt[k] for k in ("rise", "daily", "once")]
    out = await call(mcp, "trend", log_table="tr", templates=ids, exact=True, **P)
    assert "+100%" in out and "14 of 14 days" in out and "1 of 14 days" in out
    assert "5,600 (exact)" in out and "2,800 (exact)" in out
    assert "broker" in out and "scheduler" in out  # components affected
    assert "limited comparison" not in out and "UTC" in out


async def test_no_invented_new(mcp, trend_lt):
    out = await call(mcp, "trend", log_table="tr", templates=[trend_lt["daily"]], start="2026-03-01", end="2026-03-08", exact=True)
    assert "limited comparison" in out and " new" not in out.lower()
    assert "inf" not in out.lower().replace("information", "")


async def test_new_only_when_preceding_period_is_covered(mcp, trend_lt):
    # once-only template: 03-20 is in the second week; periods 03-16..03-23 vs 03-09..03-16 (covered, count 0)
    out = await call(mcp, "trend", log_table="tr", templates=[trend_lt["once"]], start="2026-03-16", end="2026-03-23", exact=True)
    assert "limited comparison" not in out and re.search(r"\bnew\b", out.lower())


async def test_period_required(mcp, trend_lt):
    assert "which period" in (await call(mcp, "trend", log_table="tr", templates=[trend_lt["daily"]])).lower()


async def test_top_templates_when_none_given(mcp, trend_lt):
    out = await call(mcp, "trend", log_table="tr", exact=True, top_n=2, **P)
    assert out.count("\nT") >= 2 and "showing 2 of" in out


async def test_hour_buckets(mcp, trend_lt):
    out = await call(mcp, "trend", log_table="tr", templates=[trend_lt["daily"]], start="2026-03-15", end="2026-03-16", bucket="hour", exact=True)
    assert "of 24 hours" in out


async def test_unknown_template_and_zone(mcp, trend_lt):
    assert "T999" in await call(mcp, "trend", log_table="tr", templates=["T999"], **P)
    out = await call(mcp, "trend", log_table="tr", templates=[trend_lt["rise"]], exact=True, timezone="Europe/Paris", **P)
    # Paris is an hour ahead of the data's first entry, so the preceding period starts before the data
    assert "Europe/Paris" in out and "5,600 (exact)" in out and "limited comparison" in out


async def test_overlap_is_said(mcp, trend_lt):
    out = await call(mcp, "trend", log_table="tr", templates=[trend_lt["rise"], trend_lt["daily"]], exact=True, **P)
    assert "lowest ID" in out


async def test_bad_bucket(mcp, trend_lt):
    assert "bucket" in (await call(mcp, "trend", log_table="tr", templates=[trend_lt["rise"]], bucket="week", **P)).lower()




async def test_estimate_is_near_the_truth_and_unsampled_days_are_marked(small_sample_lt, monkeypatch):
    client, ids = small_sample_lt
    monkeypatch.setattr(trend_tool, "MIN_BUCKET_SAMPLE", 500)
    out = await call(client, "trend", log_table="tr", templates=[ids["rise"]], **P)
    m = re.search(r"this period: ≈([\d,]+) \(", out)
    assert m and 4_000 <= int(m.group(1).replace(",", "")) <= 8_000  # planted: 5,600
    assert "no sampled entry" in out and "·" in out  # a day no sampled block overlaps is not shown as zero
    assert "estimated shape" in out


async def test_too_expensive_asks_before_running(mcp, trend_lt, monkeypatch):
    from serenedb_extractor.query import cost

    monkeypatch.setattr(cost, "THROUGHPUT_BYTES_PER_S", {"remote": 1.0, "local": 1.0})
    out = await call(mcp, "trend", log_table="tr", templates=[trend_lt["rise"]], exact=True, **P)
    assert "TOO EXPENSIVE" in out and "confirmed_cost=" in out and "this period:" not in out
