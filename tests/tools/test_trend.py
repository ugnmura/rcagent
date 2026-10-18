"""trend (#15): templates over a period against the preceding period of equal length."""

import re

import psycopg
import pytest
import pytest_asyncio

from tests.conftest import call, id_of
from tests.fixtures.data_t15 import T_DAILY_TEXT, T_ONCE_TEXT, T_RISE_TEXT, T_TICK_TEXT, TICKS, TREND

pytestmark = pytest.mark.db


async def _setup(client, db_url, name, select_sql, texts):
    """Write `select_sql` to Parquet (2,048-row groups, so block sampling has blocks), set it up as log
    table `name`, survey it, and return the template ID of each text in `texts`."""
    path = f"/tmp/t15_{name}.parquet"
    with psycopg.connect(db_url, autocommit=True) as conn:
        conn.execute(f"COPY ({select_sql}) TO '{path}' (FORMAT PARQUET, ROW_GROUP_SIZE 2048)")  # type: ignore[call-overload]
    await call(client, "setup_log_table", name=name, source=path)
    out = await call(client, "survey", log_table=name)
    return {key: id_of(out, text) for key, text in texts.items()}


@pytest_asyncio.fixture
async def trend_lt(mcp, db_url):
    texts = {"rise": T_RISE_TEXT, "daily": T_DAILY_TEXT, "once": T_ONCE_TEXT}
    return await _setup(mcp, db_url, "tr", TREND, texts)


@pytest_asyncio.fixture
async def ticks_lt(mcp, db_url):
    return await _setup(mcp, db_url, "ticks", TICKS, {"tick": T_TICK_TEXT})


P = {"start": "2026-03-15", "end": "2026-03-29"}


@pytest.fixture
def sampled(monkeypatch):
    """Pretend an exact count does not fit the budget, so trend estimates from a block sample."""
    from serenedb_extractor.tools import trend

    monkeypatch.setattr(trend, "EXACT_WITHIN_S", 0.0)


async def test_exact_by_default_when_affordable(mcp, trend_lt):
    out = await call(mcp, "trend", log_table="tr", templates=[trend_lt["rise"]], **P)
    assert out.startswith("How this was measured: trend, exact") and "56,000 (exact)" in out


async def test_estimated_default(mcp, trend_lt, sampled):
    out = await call(mcp, "trend", log_table="tr", templates=[trend_lt["rise"]], **P)
    assert out.startswith("How this was measured: trend, estimated")
    assert "≈" in out and "UTC" in out and "block sample" in out


async def test_estimate_is_near_the_truth_and_unsampled_days_are_marked(mcp, trend_lt, sampled):
    out = await call(mcp, "trend", log_table="tr", templates=[trend_lt["rise"]], **P)
    m = re.search(r"this period: ≈([\d,]+) \(.*?preceding period: ≈([\d,]+) \(", out)
    assert m
    now, before = (int(g.replace(",", "")) for g in m.groups())
    assert 50_000 <= now <= 62_000 and 25_000 <= before <= 31_000  # planted: 56,000 and 28,000
    assert "estimated shape" in out


async def test_default_on_small_scope_is_exact_and_says_so(mcp, trend_lt):
    out = await call(mcp, "trend", log_table="tr", templates=[trend_lt["rise"]], start="2026-03-15", end="2026-03-17")
    assert "≈" not in out and "(exact)" in out and "+100%" in out


async def test_exact_change_and_presence(mcp, trend_lt):
    ids = [trend_lt[k] for k in ("rise", "daily", "once")]
    out = await call(mcp, "trend", log_table="tr", templates=ids, exact=True, **P)
    assert "+100%" in out and "14 of 14 days" in out and "1 of 14 days" in out
    assert "56,000 (exact)" in out and "28,000 (exact)" in out
    assert "broker" in out and "scheduler" in out  # components affected
    assert "limited comparison" not in out and "UTC" in out


async def test_no_invented_new(mcp, trend_lt):
    out = await call(mcp, "trend", log_table="tr", templates=[trend_lt["daily"]], start="2026-03-01", end="2026-03-08", exact=True)
    assert "limited comparison" in out and " new" not in out.lower()
    assert "infinite" not in out.lower() and "∞" not in out


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
    assert "Europe/Paris" in out and "56,000 (exact)" in out and "limited comparison" in out


async def test_overlap_is_said(mcp, trend_lt):
    out = await call(mcp, "trend", log_table="tr", templates=[trend_lt["rise"], trend_lt["daily"]], exact=True, **P)
    assert "lowest ID" in out


async def test_bad_bucket(mcp, trend_lt):
    assert "bucket" in (await call(mcp, "trend", log_table="tr", templates=[trend_lt["rise"]], bucket="week", **P)).lower()


async def test_too_expensive_asks_before_running(mcp, trend_lt, monkeypatch):
    from serenedb_extractor.query import cost

    monkeypatch.setattr(cost, "THROUGHPUT_BYTES_PER_S", {"remote": 1.0, "local": 1.0})
    out = await call(mcp, "trend", log_table="tr", templates=[trend_lt["rise"]], exact=True, **P)
    assert "TOO EXPENSIVE" in out and "Nothing was run" in out and "this period:" not in out


async def test_too_many_buckets_is_refused_before_listing_any(mcp, trend_lt):
    out = await call(mcp, "trend", log_table="tr", templates=[trend_lt["rise"]], start="1826-01-01", end="2026-01-01", bucket="hour")
    assert "at most 1,000" in out and "How this was measured" not in out


async def test_spring_forward_day_has_23_real_hours(mcp, ticks_lt):
    out = await call(
        mcp, "trend", log_table="ticks", templates=[ticks_lt["tick"]], start="2026-03-29", end="2026-03-30",
        bucket="hour", exact=True, timezone="Europe/Paris",
    )
    assert "23 of 23 hours" in out and "of 24 hours" not in out
    assert "clock change" in out and "limited comparison" not in out


async def test_fall_back_day_has_25_hours_none_merged(mcp, ticks_lt):
    out = await call(
        mcp, "trend", log_table="ticks", templates=[ticks_lt["tick"]], start="2026-10-25", end="2026-10-26",
        bucket="hour", exact=True, timezone="Europe/Paris",
    )
    assert "25 of 25 hours" in out and "clock change" in out and "+02:00" in out and "+01:00" in out


async def test_day_buckets_are_local_calendar_days_across_a_clock_change(mcp, ticks_lt):
    out = await call(
        mcp, "trend", log_table="ticks", templates=[ticks_lt["tick"]], start="2026-03-28", end="2026-03-31",
        bucket="day", exact=True, timezone="Europe/Paris",
    )
    assert "3 of 3 days" in out and "clock change" in out and "23" in out


async def test_partial_edge_buckets_are_not_counted_as_absent(mcp, trend_lt):
    # The data ends on 03-29: that day is only partly there, so it is excluded from "present in N of M"
    # and (R69) the comparison runs over the 9 days the data covers in both periods.
    out = await call(mcp, "trend", log_table="tr", templates=[trend_lt["daily"]], start="2026-03-20", end="2026-03-30", exact=True)
    assert "present in 9 of 9 days" in out and "partial" in out
    assert "compared over the 9 days the data covers in both periods" in out and "no change" in out
    assert "limited comparison" not in out


async def test_coverage_needs_the_whole_period_in_the_data(mcp, trend_lt):
    # 03-29 is only partly in the data: asking for 03-28..03-30 is never called covered in full; the
    # comparison is truncated to the 1 whole day the data covers in both periods (R69).
    out = await call(mcp, "trend", log_table="tr", templates=[trend_lt["daily"]], start="2026-03-28", end="2026-03-30", exact=True)
    assert "compared over the 1 day the data covers in both periods" in out and "no change" in out


async def test_period_past_the_data_end_is_compared_over_the_covered_days(mcp, trend_lt):  # R69
    # Current 03-20..03-31 (the data ends on 03-29): 03-20..03-28 (9 days, 36,000) against the 9 days
    # before 03-20, 03-11..03-19 (4 x 2,000 + 5 x 4,000 = 28,000): +29%.
    out = await call(mcp, "trend", log_table="tr", templates=[trend_lt["rise"]], start="2026-03-20", end="2026-03-31", exact=True)
    assert "compared over the 9 days the data covers in both periods" in out
    assert "36,000 against 28,000" in out and "+29%" in out
    assert "limited comparison" not in out


async def test_new_after_truncation_needs_the_truncated_preceding_period_covered(mcp, trend_lt):  # R69
    out = await call(mcp, "trend", log_table="tr", templates=[trend_lt["once"]], start="2026-03-20", end="2026-03-31", exact=True)
    assert "compared over the 9 days" in out and re.search(r"\bnew\b", out.lower())


async def test_no_truncation_when_the_data_starts_late(mcp, trend_lt):
    # The preceding period of 03-01..03-08 lies before the data: no comparison, nothing called new.
    out = await call(mcp, "trend", log_table="tr", templates=[trend_lt["daily"]], start="2026-03-01", end="2026-03-31", exact=True)
    assert "limited comparison" in out and "compared over" not in out


async def test_minute_buckets_on_a_telemetry_log_table(mcp, db_url):
    from tests.telemetry import fixtures as fx

    ids = await _setup(mcp, db_url, "shop_logs", fx.logs_sql(), {"oom": "OutOfMemoryError"})
    out = await call(
        mcp, "trend", log_table="shop_logs", templates=[ids["oom"]], start="2026-03-01T10:10:00Z",
        end="2026-03-01T10:20:00Z", bucket="minute", exact=True,
    )
    assert "split into minutes: this period has 10" in out and "Minutes are real minutes" in out
    assert "this period by minute: 12 12 12 12 12 12 12 12 12 12" in out


async def test_peak_of_a_burst_is_one_bucket_with_all_entries(mcp, trend_lt):  # #29
    out = await call(mcp, "trend", log_table="tr", templates=[trend_lt["once"]], exact=True, **P)
    assert "    peak: 2026-03-20 with 600 entries (100% of this period)" in out


async def test_peak_of_an_even_spread_has_a_low_share(mcp, trend_lt):  # #29
    out = await call(mcp, "trend", log_table="tr", templates=[trend_lt["daily"]], exact=True, **P)
    # 1,000 a day on each of 14 days: the first such day, with 1/14 of the period
    assert "    peak: 2026-03-15 with 1,000 entries (7% of this period)" in out


async def test_peak_by_hour_is_labelled_in_the_shown_zone(mcp, trend_lt):  # #29
    # heartbeat slots 03:20..04:03 UTC: 800 entries in hour 03, 200 in hour 04
    out = await call(
        mcp, "trend", log_table="tr", templates=[trend_lt["daily"]], start="2026-03-15", end="2026-03-16",
        bucket="hour", exact=True,
    )
    assert "    peak: 2026-03-15 03:00 UTC with 800 entries (80% of this period)" in out
    paris = await call(
        mcp, "trend", log_table="tr", templates=[trend_lt["daily"]], start="2026-03-15", end="2026-03-16",
        bucket="hour", exact=True, timezone="Europe/Paris",
    )
    assert "    peak: 2026-03-15 04:00 UTC+01:00 with 800 entries" in paris


async def test_peak_of_a_sampled_run_is_estimated(mcp, trend_lt, sampled):  # #29
    out = await call(mcp, "trend", log_table="tr", templates=[trend_lt["rise"]], **P)
    assert re.search(r"\n    peak \(estimated\): 2026-03-\d\d with ≈[\d,]+ entries \(≈\d+% of this period\)", out)
    assert "\n    peak: " not in out


async def test_peak_by_minute(mcp, db_url):  # #29
    from tests.telemetry import fixtures as fx

    ids = await _setup(mcp, db_url, "shop_logs", fx.logs_sql(), {"oom": "OutOfMemoryError"})
    out = await call(
        mcp, "trend", log_table="shop_logs", templates=[ids["oom"]], start="2026-03-01T10:10:00Z",
        end="2026-03-01T10:20:00Z", bucket="minute", exact=True,
    )
    assert "    peak: 2026-03-01 10:10 UTC with 12 entries (10% of this period)" in out
