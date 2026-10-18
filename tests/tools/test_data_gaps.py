"""Round-3 fixes on gaps in the data: trend counts presence over the buckets with data and names a gap also when the
period runs past the data's edge; rank_problems does not give persistence points for one or two whole days; the
engineer prompt maps the failing components before surveying."""

import re

import pytest

from rcagent.prompts import ENGINEER_PROMPT
from tests.conftest import call, container_parquet, id_of

pytestmark = pytest.mark.db

# Entries every hour from 2026-05-14 06:00 to 2026-05-17 12:00 UTC, except none at all from 05-15 00:00 to 05-16 08:00
# (a gap: all of 15 May and the first 8 hours of 16 May). Each hour: one INFO line and one ERROR "disk quota" line
# (component db); and two ERROR "checksum mismatch" lines (component store) on 16 May at 10:15 and 11:15.
GAPPY = """
SELECT ts, level, component, message FROM (
  SELECT TIMESTAMPTZ '2026-05-14 06:00:00+00' + i * INTERVAL '1 hour' AS ts, 'INFO' AS level, 'web' AS component,
         'request served in 5ms' AS message FROM range(79) t(i)
  UNION ALL
  SELECT TIMESTAMPTZ '2026-05-14 06:20:00+00' + i * INTERVAL '1 hour', 'ERROR', 'db', 'disk quota exceeded on volume 7'
  FROM range(78) t(i)
  UNION ALL
  SELECT TIMESTAMPTZ '2026-05-16 10:15:00+00' + i * INTERVAL '1 hour', 'ERROR', 'store', 'checksum mismatch in block 42'
  FROM range(2) t(i)
) WHERE ts < TIMESTAMPTZ '2026-05-15 00:00:00+00' OR ts >= TIMESTAMPTZ '2026-05-16 08:00:00+00'
ORDER BY ts
"""

# Entries only from 2026-06-01 00:00 to 02:30 UTC: two whole hours, too few to judge persistence.
SHORT = """
SELECT TIMESTAMPTZ '2026-06-01 00:00:00+00' + i * INTERVAL '10 minutes' AS ts, 'ERROR' AS level, 'db' AS component,
       'disk quota exceeded on volume 7' AS message
FROM range(16) t(i)
"""


@pytest.fixture
async def gappy(mcp, db_url):
    await call(mcp, "setup_log_table", name="gappy", source=container_parquet(db_url, "r3gap_gappy", GAPPY))
    await call(mcp, "survey", log_table="gappy")


async def test_trend_counts_presence_over_days_with_data_and_names_the_gap(mcp, gappy):
    # The period runs past the data's edges (it starts 14 May 06:00 and ends 17 May 12:00): a partial coverage,
    # with 15 May a gap inside the data's span.
    out = await call(mcp, "trend", log_table="gappy", start="2026-05-14", end="2026-05-18", exact=True)
    assert "limited comparison" in out and "only part of this period" in out
    assert "inside the data's span the logs have no entries at all in 1 of the 2 whole days (2026-05-15)" in out
    quota = next(b for b in out.split("\n\n") if "disk quota" in b)
    # 14 and 17 May are partial days; 15 May is a gap: only 16 May is a whole day with data
    assert "present in 1 of 1 days with data" in quota
    assert "1 day in a gap in the data with no entries at all" in quota
    assert "present in 1 of 2 days" not in out


async def test_hourly_trend_leaves_the_gap_hours_out_of_presence(mcp, gappy):
    out = await call(mcp, "trend", log_table="gappy", start="2026-05-16", end="2026-05-17", bucket="hour", exact=True)
    quota = next(b for b in out.split("\n\n") if "disk quota" in b)
    assert "present in 16 of 16 hours with data" in quota and "8 hours in a gap in the data" in quota
    assert "of 24 hours" not in quota


async def test_rank_measures_persistence_in_hours_when_one_whole_day_has_data(mcp, gappy):
    out = await call(mcp, "rank_problems", log_tables=["gappy"], start="2026-05-14", end="2026-05-18")
    assert "persistence is measured in hours" in out and "only 1 whole day of this period has data" in out
    assert "measured in hours when fewer than 3 whole days have data" in out  # the rule says so
    items = re.findall(r"^(\d+)\. score \d+/18  \[gappy (T\d+)\] (.*)$", out, re.M)
    assert [text for _, _, text in items][0].startswith("disk quota exceeded")  # the 2-entry problem no longer leads
    rare = next(b for b in out.split("\n\n") if "checksum mismatch" in b)
    assert "persistence 0" in rare and re.search(r"present in 2 of \d+ whole hours with data", rare)
    common = next(b for b in out.split("\n\n") if "disk quota" in b)
    assert "persistence 3" in common
    assert id_of(out, "checksum mismatch")


async def test_rank_does_not_judge_persistence_on_too_few_hours(mcp, db_url):
    await call(mcp, "setup_log_table", name="short", source=container_parquet(db_url, "r3gap_short", SHORT))
    out = await call(mcp, "rank_problems", log_tables=["short"], start="2026-06-01", end="2026-06-02")
    assert "persistence not judged: too few whole days or hours of this period with data (2 whole hours" in out
    block = next(b for b in out.split("\n\n") if "disk quota" in b)
    assert "persistence 0" in block and "too few to judge persistence" in block


def test_engineer_maps_components_before_surveying():
    e = ENGINEER_PROMPT.lower()
    assert e.index("count_logs") < e.index("survey")
    assert "grouped by component and level" in e and "survey each component" in e
