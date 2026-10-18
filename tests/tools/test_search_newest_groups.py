"""search_logs over a single Parquet file with several row groups (S6 perf): it counts, then lists the newest
(or oldest) row groups first and reads more only when they can't hold the answer. The entries shown must be
exactly those of ORDER BY timestamp, file row (NULLS LAST) over the whole scope: ties across a row-group
boundary, entries without a timestamp, a window cutting row groups, and a rare text that fills no group."""

import re

import psycopg
import pytest

from rcagent.query import stats
from tests.conftest import call, call_raw

pytestmark = pytest.mark.db

PATH = "/tmp/newest_groups_a34f.parquet"
N = 10240  # 5 row groups of 2,048 entries
NULL_FROM = 10200  # the last 40 entries have no timestamp
# Entry i at second i // 10, so the 10 entries 2040..2049 share a second across the first row-group boundary;
# every entry says "done", every 1000th (i % 1000 == 7) also "rare".
DATA = f"""
SELECT CASE WHEN i < {NULL_FROM} THEN TIMESTAMPTZ '2026-05-01 10:00:00+00' + (i // 10) * INTERVAL '1 second' END AS ts,
       'INFO' AS level,
       'entry-' || lpad(i::VARCHAR, 5, '0') || CASE WHEN i % 1000 = 7 THEN ' rare' ELSE '' END || ' done' AS message
FROM range(0, {N}) t(i) ORDER BY i
"""


def _second(i: int) -> str:
    return f"2026-05-01T10:{(i // 10) // 60:02d}:{(i // 10) % 60:02d}"


@pytest.fixture
async def grouped(mcp, db_url):
    with psycopg.connect(db_url, autocommit=True) as conn:
        conn.execute(f"COPY ({DATA}) TO '{PATH}' (FORMAT PARQUET, ROW_GROUP_SIZE 2048)")  # type: ignore[call-overload]
    stats.forget_session()
    out = await call(mcp, "setup_log_table", name="grouped", source=PATH)
    assert "Set up log table" in out, out


def _shown(out: str) -> list[int | str]:
    body = out.split("(exact)", 1)[1]
    return [int(x) if x.isdigit() else x for x in re.findall(r"entry-(\d+)", body)]


def _expected(lo: int, hi: int, order: str, limit: int, rare: bool = False) -> list[int]:
    """Entries lo..hi-1 (all timestamped) in ORDER BY ts, file row order."""
    picked = [i for i in range(lo, hi) if not rare or i % 1000 == 7]
    picked.sort(key=lambda i: (i // 10, i), reverse=order == "newest")
    return picked[:limit]


async def _listing_sql(mcp, out_raw: str) -> str:
    handle = re.search(r"Evidence \[(Q\d+)\]", out_raw).group(1)
    return await call(mcp, "show_evidence", ids=[handle])


async def test_newest_reads_one_row_group_and_matches_order_by(mcp, grouped):
    raw = await call_raw(mcp, "search_logs", log_table="grouped", text="done", start="2026-05-01T10:00:00",
                         end="2026-05-01T10:20:00", timezone="UTC", limit=5)
    assert f"{NULL_FROM:,} matching entries (exact)" in raw, raw
    assert _shown(raw) == _expected(0, NULL_FROM, "newest", 5), raw
    evidence = await _listing_sql(mcp, raw)
    assert "file_row_number BETWEEN 8192 AND 10239" in evidence, evidence  # only the newest row group


async def test_oldest_with_ties_across_a_row_group_boundary(mcp, grouped):
    # The window starts at second 204: entries 2040..2049 share it, split over groups 0 and 1.
    out = await call(mcp, "search_logs", log_table="grouped", text="done", start=_second(2040),
                     end=_second(2400), timezone="UTC", order="oldest", limit=12)
    assert _shown(out) == _expected(2040, 2400, "oldest", 12), out
    out = await call(mcp, "search_logs", log_table="grouped", text="done", start=_second(1000),
                     end=_second(2050), timezone="UTC", limit=12)
    assert _shown(out) == _expected(1000, 2050, "newest", 12), out


async def test_many_entries_need_more_than_one_row_group(mcp, grouped):
    out = await call(mcp, "search_logs", log_table="grouped", text="done", start="2026-05-01T10:00:00",
                     end="2026-05-01T10:20:00", timezone="UTC", limit=250)
    assert _shown(out) == _expected(0, NULL_FROM, "newest", 250), out
    # The window ends 8 entries into the newest row group it touches: that group can't fill the listing.
    out = await call(mcp, "search_logs", log_table="grouped", text="done", start="2026-05-01T10:00:00",
                     end=_second(8200), timezone="UTC", limit=250)
    assert _shown(out) == _expected(0, 8200, "newest", 250), out
    # The last entry listed from the newest group ties with the next group's newest second: read on.
    out = await call(mcp, "search_logs", log_table="grouped", text="done", start="2026-05-01T10:00:00",
                     end=_second(2050), timezone="UTC", limit=2)
    assert _shown(out) == [2049, 2048], out


async def test_a_rare_text_and_entries_without_time(mcp, grouped):
    out = await call(mcp, "search_logs", log_table="grouped", text="RARE", limit=20)
    assert "11 matching entries (exact)" in out, out
    assert _shown(out) == _expected(0, NULL_FROM, "newest", 20, rare=True), out
    # Without a period the entries without a timestamp match too, and come last.
    out = await call(mcp, "search_logs", log_table="grouped", text="entry-1020", limit=20)
    assert _shown(out) == [10209, 10208, 10207, 10206, 10205, 10204, 10203, 10202, 10201, 10200], out
    out = await call(mcp, "search_logs", log_table="grouped", text="entry-1019", order="oldest", limit=20)
    assert _shown(out) == [10190, 10191, 10192, 10193, 10194, 10195, 10196, 10197, 10198, 10199], out


async def test_columns_and_metadata_are_reused_until_the_file_changes(mcp, grouped, db_url, monkeypatch):
    monkeypatch.setattr(stats, "SETTLE_S", 0)  # the file was just written
    args = dict(log_table="grouped", text="done", start="2026-05-01T10:00:00", end="2026-05-01T10:20:00",
                timezone="UTC", limit=3)
    await call(mcp, "search_logs", **args)
    second = await _listing_sql(mcp, await call_raw(mcp, "search_logs", **args))
    assert "read_blob(" in second, second
    # Not run again, but cited: each reused metadata query is in this call's evidence, marked as reused.
    for lookup in ("parquet_metadata(", "DESCRIBE", "LIMIT 0"):
        lines = [ln for ln in second.splitlines() if lookup in ln]
        assert lines and all("-- reused: the source's files are unchanged since" in ln for ln in lines), second
    # A changed file (another size) is read again.
    with psycopg.connect(db_url, autocommit=True) as conn:
        conn.execute(  # type: ignore[call-overload]
            f"COPY ({DATA.replace(f'range(0, {N})', 'range(0, 6000)')}) TO '{PATH}' (FORMAT PARQUET, ROW_GROUP_SIZE 2048)"
        )
    raw = await call_raw(mcp, "search_logs", **args)
    assert "6,000 matching entries (exact)" in raw, raw
    assert _shown(raw) == _expected(0, 6000, "newest", 3), raw
    third = await _listing_sql(mcp, raw)
    assert any("parquet_metadata(" in ln and "reused" not in ln for ln in third.splitlines()), third


def test_row_groups_without_statistics_are_never_ruled_out():
    """A row group without timestamp statistics may hold anything: the listing reads on (here: the whole scope)."""
    from rcagent.catalog.models import FieldRoles, LogTable
    from rcagent.db import Rows
    from rcagent.query.stats import GroupStat
    from rcagent.tools import lookup

    sent: list[str] = []

    class Db:
        def read(self, sql, params=None, **_kw):
            sent.append(sql)
            return Rows(["occ_ts"], [(lookup.datetime(2026, 1, 1, tzinfo=lookup.UTC),)] * 2)

    now = lookup.datetime(2026, 1, 1)
    lt = LogTable("x", "/x.parquet", "parquet", "in_place", "r", FieldRoles(message='"m"', timestamp='"ts"', order='"file_row_number"'),
                  None, None, None, "UTC", now, now)
    groups = tuple(GroupStat(i * 10, 10, {}) for i in range(10))
    rows = lookup._newest_groups(Db(), lt, groups, 1000, "TRUE", "TRUE", {}, [("ts", "occ_ts")], "newest", 2, 1.0, "")
    assert len(rows) == 2 and "BETWEEN" not in sent[-1], sent
    rows = lookup._newest_groups(Db(), lt, groups, 1000, "TRUE", "TRUE", {}, [("ts", "occ_ts")], "oldest", 2, 1.0, "")
    assert "BETWEEN" not in sent[-1], sent
