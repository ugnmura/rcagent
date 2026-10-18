"""Round 3 series fixes: a cut grouping says what it left out (so a small time bucket never reads as zero),
long templates are cut in headings, extract_params on a template without parameters has its header, and
get_context says when the nearest entry outside the window is."""

import re

import pytest

from serenedb_extractor.tools.investigate import omitted_line
from serenedb_extractor import format as fmt
from tests.conftest import call, container_parquet, first_occurrence, id_of

# 27 days of FATAL `node <n> failed with code <c>`: day d (2026-03-dd) has 5 + d % 3 entries, one a minute
# from midnight, except 23 March (2) and 26 March (1), the two smallest days.
# 2026-03-28: WARN `heartbeat lost` at 06:00:00 and 06:00:30, then three ERROR multi-kilobyte tracebacks at 08:00.
SMALL = {23: 2, 26: 1}


def _n(d: int) -> int:
    return SMALL.get(d, 5 + d % 3)


SERIES = f"""
SELECT * FROM (
  SELECT TIMESTAMPTZ '2026-03-01 00:00:00+00' + (d - 1) * INTERVAL '1 day' + j * INTERVAL '1 minute' AS ts,
         'FATAL' AS level,
         'node ' || (d * 10 + j)::VARCHAR || ' failed with code ' || (j % 3)::VARCHAR AS message
  FROM range(1, 28) t(d), range(0, 8) u(j)
  WHERE j < CASE WHEN d = 23 THEN 2 WHEN d = 26 THEN 1 ELSE 5 + d % 3 END
  UNION ALL
  SELECT TIMESTAMPTZ '2026-03-28 06:00:00+00' + k * INTERVAL '30 seconds', 'WARN', 'heartbeat lost'
  FROM range(0, 2) v(k)
  UNION ALL
  SELECT TIMESTAMPTZ '2026-03-28 08:00:00+00' + k * INTERVAL '1 second', 'ERROR',
         'Traceback (most recent call last):' || chr(10)
         || repeat('  File "/srv/app/worker.py", line 42, in handle' || chr(10) || '    run()' || chr(10), 60)
         || 'ValueError: bad input'
  FROM range(0, 3) w(k)
) ORDER BY ts
"""


def test_omitted_line_names_few_time_buckets():
    left = [(("2005-12-23",), fmt.Measured(2.0, True)), (("2005-12-29",), fmt.Measured(1.0, True))]
    assert omitted_line(["time:1d"], 2, 3, True, left) == (
        "not shown: 2 smaller days, 3 entries in all (2005-12-23: 2, 2005-12-29: 1)"
    )
    assert omitted_line(["time:1h"], 1, 1, True, left[:1]) == "not shown: 1 smaller hour, 1 entry in all (2005-12-23: 2)"
    assert omitted_line(["time:6h"], 12, 1500, True, None) == "not shown: 12 smaller 6-hour buckets, 1,500 entries in all"
    assert omitted_line(["host"], 2, 3, True, left) == "not shown: 2 smaller groups, 3 entries in all"


@pytest.fixture
async def series(mcp, db_url):
    path = container_parquet(db_url, "r3ser_series", SERIES)
    out = await call(mcp, "setup_log_table", name="r3ser", source=path)
    assert "Set up log table" in out, out
    return await call(mcp, "survey", log_table="r3ser")


@pytest.mark.db
async def test_count_logs_names_left_out_days(mcp, series):
    out = await call(
        mcp, "count_logs", log_tables=["r3ser"], group_by=["time:1d"], start="2026-03-01", end="2026-03-28",
        filters={"level": "FATAL"},
    )
    assert "showing the 25 largest of 27 groups" in out, out
    assert "not shown: 2 smaller days, 3 entries in all (2026-03-23: 2, 2026-03-26: 1)" in out, out
    assert "2026-03-23:" not in out.split("not shown")[0]


@pytest.mark.db
async def test_count_logs_many_left_out_not_named(mcp, series):
    out = await call(
        mcp, "count_logs", log_tables=["r3ser"], group_by=["time:1d"], filters={"level": "FATAL"}, limit=5,
    )
    total = sum(_n(d) for d in range(1, 28))
    shown = sum(int(n) for n in re.findall(r"^  2026-03-\d\d: (\d+)", out, re.M))
    assert f"not shown: 22 smaller days, {total - shown:,} entries in all" in out, out
    assert "entries in all (" not in out


@pytest.mark.db
async def test_locate_names_left_out_days(mcp, series):
    tid = id_of(series, "failed with code")
    out = await call(
        mcp, "locate_occurrences", log_table="r3ser", templates=[tid], group_by=["time:1d"], examples_per_group=0,
        limit=25,
    )
    assert "showing the 25 largest of 27 groups" in out, out
    assert "not shown: 2 smaller days, 3 entries in all (2026-03-23: 2, 2026-03-26: 1)" in out, out


@pytest.mark.db
async def test_extract_params_by_day_says_what_was_left_out(mcp, series):
    tid = id_of(series, "failed with code")
    out = await call(mcp, "extract_params", log_table="r3ser", template=tid, by="time:1d")
    total = sum(_n(d) for d in range(1, 28))
    by = out.split("by time:1d")[1]
    shown = sum(int(n.replace(",", "")) for n in re.findall(r"^    2026-03-\d\d: ([\d,]+) entries", by, re.M))
    assert f"not shown: 17 smaller days, {total - shown:,} entries in all" in out, out


@pytest.mark.db
async def test_long_template_cut_in_headings(mcp, series):
    tid = id_of(series, "Traceback")
    out = await call(mcp, "locate_occurrences", log_table="r3ser", templates=[tid])
    heading = next(line for line in out.splitlines() if line.startswith(tid))
    assert len(heading) < 220 and "…(cut)" in heading and "\n" not in heading, heading
    out = await call(mcp, "extract_params", log_table="r3ser", template=tid)
    heading = next(line for line in out.splitlines() if line.startswith(tid))
    assert len(heading) < 220, heading


@pytest.mark.db
async def test_extract_params_without_parameters_has_header(mcp, series):
    tid = id_of(series, "heartbeat lost")
    out = await call(mcp, "extract_params", log_table="r3ser", template=tid)
    assert out.startswith("How this was measured: catalog only"), out
    assert "no entries were read" in out and "no parameters" in out


@pytest.mark.db
async def test_get_context_says_when_the_nearest_entry_outside_is(mcp, series):
    occ = first_occurrence(await call(mcp, "search_logs", log_table="r3ser", text="heartbeat", order="oldest", limit=1))
    out = await call(mcp, "get_context", log_table="r3ser", occurrence=occ)
    assert "showing 0 of up to 10 entries before and 1 of up to 10 entries after" in out, out
    assert "The nearest earlier entry in this scope is 30 h before (2026-03-27 00:04:00)" in out, out
    assert "The nearest later entry in this scope is 2 h after (2026-03-28 08:00:00)" in out, out
    out = await call(mcp, "get_context", log_table="r3ser", occurrence=occ, filters={"level": "WARN"})
    assert "None earlier in this scope." in out and "None later in this scope." in out, out
    # Enough entries on both sides: no hint.
    out = await call(mcp, "get_context", log_table="r3ser", occurrence=occ, before=0, after=1)
    assert "in this scope" not in out, out
