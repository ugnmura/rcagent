"""Round-4 notes: rank_problems says how many templates it considered of how many; trend names gaps of hours inside
days, marks gap days in its series, gives the cap note for top_n and tells days outside the data from partial days;
count_logs says when the period cuts a time bucket and why a text count is 0; locate_occurrences says when its cut
falls inside a tie."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
import pytest_asyncio

from serenedb_extractor import format as fmt
from serenedb_extractor.context import AppContext
from serenedb_extractor.query.filters import TimeRange
from serenedb_extractor.tools.aggregate import _partial_buckets
from serenedb_extractor.tools.investigate import tie_note
from serenedb_extractor.tools.trend import _series_lines
from tests.conftest import Client, _client, _reset_schema, _settings, call, container_parquet, id_of

NOISE = [
    "fan speed below threshold on tray",
    "link down on port of switch",
    "memory scrub found correctable error",
    "power supply voltage out of range",
    "job scheduler queue is full",
    "backup snapshot failed to complete",
    "user session token could not be verified",
    "temperature sensor reports overheating",
    "replication lag exceeded the limit",
    "license server is unreachable now",
    "dns lookup timed out for resolver",
    "raid array is rebuilding slowly",
]
_noise_values = ", ".join(f"({i}, '{m}')" for i, m in enumerate(NOISE))

# Every hour from 2026-04-01 00:00 to 2026-04-11 11:00 UTC: one INFO line (web), one ERROR "disk quota" line (db) and
# one WARN "cache miss" line (cache), except none at all from 2026-04-05 07:00 to 15:00 (8 empty hours inside a day)
# and on all of 2026-04-08 (a gap day). Twelve other ERROR templates once a day from 1 to 7 April.
DATA = f"""
SELECT ts, level, component, message FROM (
  SELECT TIMESTAMPTZ '2026-04-01 00:00:00+00' + i * INTERVAL '1 hour' AS ts, 'INFO' AS level, 'web' AS component,
         'request served in 5ms' AS message FROM range(252) t(i)
  UNION ALL
  SELECT TIMESTAMPTZ '2026-04-01 00:20:00+00' + i * INTERVAL '1 hour', 'ERROR', 'db', 'disk quota exceeded on volume 7'
  FROM range(252) t(i)
  UNION ALL
  SELECT TIMESTAMPTZ '2026-04-01 00:40:00+00' + i * INTERVAL '1 hour', 'WARN', 'cache', 'cache miss ratio high for shard 3'
  FROM range(252) t(i)
  UNION ALL
  SELECT TIMESTAMPTZ '2026-04-01 01:05:00+00' + d * INTERVAL '1 day' + n.k * INTERVAL '1 minute', 'ERROR', 'hw', n.m
  FROM range(7) t(d), (VALUES {_noise_values}) n(k, m)
) WHERE NOT (ts >= TIMESTAMPTZ '2026-04-05 07:00:00+00' AND ts < TIMESTAMPTZ '2026-04-05 15:00:00+00')
    AND NOT (ts >= TIMESTAMPTZ '2026-04-08 00:00:00+00' AND ts < TIMESTAMPTZ '2026-04-09 00:00:00+00')
ORDER BY ts
"""


@pytest_asyncio.fixture
async def mcp_small_cap(db_url: str) -> AsyncIterator[Client]:
    _reset_schema(db_url)
    settings = _settings(db_url, limit_cap=1)
    async for c in _client(lambda: AppContext.from_settings(settings)):
        yield c


async def _setup(client: Client, db_url: str) -> None:
    out = await call(client, "setup_log_table", name="r4n", source=container_parquet(db_url, "r4note_data", DATA))
    assert "Set up log table" in out, out
    await call(client, "survey", log_table="r4n")


@pytest.fixture
async def data(mcp, db_url):
    await _setup(mcp, db_url)


# ---- 1. rank_problems: how many templates were considered ---------------------------------------------------


@pytest.mark.db
async def test_rank_says_how_many_templates_it_considered(mcp, data):
    out = await call(mcp, "rank_problems", log_tables=["r4n"], start="2026-04-02", end="2026-04-08", candidates=3)
    assert "Log table r4n: considered the 3 largest of 14 warning-and-worse templates of this period (candidates=3)" in out, out
    assert "smaller ones are not ranked" in out
    out = await call(mcp, "rank_problems", log_tables=["r4n"], start="2026-04-02", end="2026-04-08", candidates=100)
    assert "considered the 14 largest of 14 warning-and-worse templates of this period " in out, out
    assert "(candidates=60; at most 60 per call; 100 were asked for)" in out, out


# ---- 2. trend: hours with no entries inside days; gap days marked in the series ------------------------------


@pytest.mark.db
async def test_trend_days_name_empty_hours_and_mark_gap_days(mcp, data):
    out = await call(mcp, "trend", log_table="r4n", start="2026-04-04", end="2026-04-13", exact=True)
    assert "hours with no entries at all inside days" in out, out
    assert "this period: 2026-04-05 07:00 UTC for 8 hours" in out, out
    quota = next(b for b in out.split("\n\n") if "disk quota" in b)
    assert "this period by day (– = a day in a gap in the data, no entries of any kind): 24 16 24 24 – 24 24 12 0" in quota, quota
    # 4. days past the data's end are not "partial"
    assert "1 partial day at the edge of the period or the data; 1 day outside the data" in quota, quota
    assert "1 day in a gap in the data with no entries at all" in quota


def test_series_lines_mark_gap_buckets():
    ms = [fmt.Measured(v, True) for v in (3.0, 0.0, 2.0)]
    now, before = _series_lines(ms, ms, "day", True, {1}, set())
    assert now.endswith(": 3 – 2") and "– = a day in a gap" in now
    assert before == "    preceding period by day: 3 0 2"
    many = [fmt.Measured(1.0, True)] * 40
    assert "–" in _series_lines(many, many, "day", True, {5}, set())[0].split(": ", 1)[1]


# ---- 3. trend: top_n above its cap -----------------------------------------------------------------------------


@pytest.mark.db
async def test_trend_top_n_above_cap_says_so(mcp_small_cap, db_url):
    await _setup(mcp_small_cap, db_url)
    out = await call(mcp_small_cap, "trend", log_table="r4n", start="2026-04-02", end="2026-04-08", top_n=50)
    assert "showing 10 of 15 templates" in out, out
    assert "at most 10 per call; 50 were asked for" in out, out


# ---- 5. count_logs: a period that cuts a time bucket ----------------------------------------------------------


def test_partial_bucket_notes():
    tr = TimeRange(datetime(2026, 4, 1, tzinfo=UTC), datetime(2026, 4, 11, tzinfo=UTC), "UTC")
    notes = _partial_buckets(["time:7d"], tr)
    assert notes == [
        "partial bucket: the first 7-day bucket, 2026-03-30, holds only entries from 2026-04-01 on (the period starts inside it)",
        "partial bucket: the last 7-day bucket, 2026-04-06, holds only entries before 2026-04-11 (the period ends inside it)",
    ]
    assert _partial_buckets(["time:1d", "component"], tr) == []
    assert _partial_buckets(["time:7d"], TimeRange(datetime(2026, 3, 30, tzinfo=UTC), datetime(2026, 4, 6, tzinfo=UTC))) == []
    late = _partial_buckets(["time:1h"], TimeRange(datetime(2026, 4, 1, 6, 30, tzinfo=UTC), None))
    assert late == [
        "partial bucket: the first hour bucket, 2026-04-01 06:00, holds only entries from 2026-04-01 06:30 on "
        "(the period starts inside it)"
    ]


@pytest.mark.db
async def test_count_logs_notes_a_partial_first_week(mcp, data):
    out = await call(mcp, "count_logs", log_tables=["r4n"], group_by=["time:7d"], start="2026-04-01", end="2026-04-11")
    assert "the first 7-day bucket, 2026-03-30, holds only entries from 2026-04-01 on" in out, out
    assert "the last 7-day bucket, 2026-04-06, holds only entries before 2026-04-11" in out, out


# ---- 6. count_logs: a text that matches nothing -----------------------------------------------------------------


@pytest.mark.db
async def test_count_logs_explains_a_text_with_no_match(mcp, data):
    out = await call(mcp, "count_logs", log_tables=["r4n"], text="zzz-no-such-text")
    assert "0 matching entries" in out, out
    assert "No entry in this scope contains 'zzz-no-such-text' (searched in any case)." in out, out
    out = await call(mcp, "count_logs", log_tables=["r4n"], text="disk quota", filters={"level": "NOPE"})
    assert "level='NOPE' matched nothing" in out, out
    assert "No entry in this scope contains" not in out
    out = await call(
        mcp, "count_logs", log_tables=["r4n"], text="zzz", group_by=["component"], filters={"level": "ERROR"},
    )
    assert "No entry in this scope contains 'zzz' (searched in any case)." in out, out
    assert "no entry matches all of them together" not in out


# ---- 7. locate_occurrences: a cut inside a tie ----------------------------------------------------------------


def test_tie_note():
    m1, m2 = fmt.Measured(1.0, True), fmt.Measured(2.0, True)
    keep = [(("a",), m1), (("b",), m1)]
    assert tie_note(keep, [(("c",), m1), (("d",), m1)], lambda m: f"{round(m.value)}") == (
        "all shown groups and 2 others have 1 each; which of them are shown is arbitrary (the cut falls inside a tie)"
    )
    assert tie_note([(("a",), m2), (("b",), m1)], [(("c",), m1)], lambda m: f"{round(m.value)}").startswith(
        "the smallest shown group and 1 other have 1 each"
    )
    assert tie_note([(("a",), m2)], [(("c",), m1)], str) is None


@pytest.mark.db
async def test_locate_says_when_the_cut_falls_in_a_tie(mcp, data):
    survey = await call(mcp, "survey", log_table="r4n")
    tid = id_of(survey, "disk quota")
    out = await call(
        mcp, "locate_occurrences", log_table="r4n", templates=[tid], group_by=["time:1h"],
        start="2026-04-01", end="2026-04-02", limit=5, examples_per_group=0,
    )
    assert "showing the 5 largest of 24 groups" in out, out
    assert "all shown groups and 19 others have 1 each; which of them are shown is arbitrary" in out, out
