"""Round 3 output fixes: limits above the cap say so, extract_params time buckets in time order,
thousands separators on every count."""

import re

import pytest

from serenedb_extractor import format as fmt
from tests.conftest import call, container_parquet, id_of
from tests.fixtures.data import FX


def test_limit_and_note():
    assert fmt.limit_and_note(None, 50, 500) == (50, None)
    import pytest

    from serenedb_extractor.errors import UserFacingError

    with pytest.raises(UserFacingError):
        fmt.limit_and_note(0, 50, 500)
    assert fmt.limit_and_note(80, 50, 500) == (80, None)
    assert fmt.limit_and_note(500, 50, 500) == (500, None)
    value, note = fmt.limit_and_note(5000, 50, 500)
    assert value == 500 and note == "at most 500 per call; 5,000 were asked for"
    assert fmt.clamp_limit(5000, 50, 500) == 500 and fmt.clamp_limit(None, 50, 500) == 50


def test_cut_has_thousands_separators():
    _, note = fmt.cut(list(range(26215)), 1500, "groups")
    assert note == "showing 1,500 of 26,215 groups"


@pytest.fixture
async def fx(mcp, db_url):
    path = container_parquet(db_url, "fx", FX)
    await call(mcp, "setup_log_table", name="fx", source=path)
    out = await call(mcp, "survey", log_table="fx")
    return id_of(out, "timeout after <NUM>ms calling payments")


def _no_bare_thousands(out: str) -> None:
    """Every "showing N of M" count of four or more digits carries separators."""
    for line in out.splitlines():
        if "showing" in line:
            assert not re.search(r"\b\d{4,}\b", line), line


@pytest.mark.db
async def test_search_logs_says_limit_was_capped(mcp, fx):
    out = await call(mcp, "search_logs", log_table="fx", text="timeout", limit=5000)
    assert "showing 500 of 3,000 entries (newest first; at most 500 per call; 5,000 were asked for)" in out
    out = await call(mcp, "search_logs", log_table="fx", text="timeout", limit=20)
    assert "showing 20 of 3,000 entries (newest first)" in out and "asked for" not in out


@pytest.mark.db
async def test_locate_says_limit_was_capped_with_separators(mcp, fx):
    out = await call(
        mcp, "locate_occurrences", log_table="fx", templates=[fx], group_by=["time:1m"], examples_per_group=0, limit=1000
    )
    m = re.search(r"showing the 200 largest of ([\d,]+) groups \(at most 200 per call; 1,000 were asked for\)", out)
    assert m and "," in m.group(1), out[-400:]
    _no_bare_thousands(out)


@pytest.mark.db
async def test_extract_params_says_limit_was_capped(mcp, fx):
    out = await call(mcp, "extract_params", log_table="fx", template=fx, limit=500)
    assert "showing 100 of 900 values (at most 100 per call; 500 were asked for)" in out
    out = await call(mcp, "extract_params", log_table="fx", template=fx, limit=5)
    assert "showing 5 of 900 values" in out and "asked for" not in out


@pytest.mark.db
async def test_count_logs_says_limit_was_capped(mcp, fx):
    out = await call(mcp, "count_logs", log_tables=["fx"], group_by=["time:1m"], limit=10000)
    assert re.search(r"showing the 250 largest of [\d,]+ groups \(at most 250 per call; 10,000 were asked for\)", out), out[:800]
    _no_bare_thousands(out)


def _by_labels(out: str) -> list[str]:
    return re.findall(r"^    (\d{4}-\d\d-\d\d(?: \d\d:\d\d)?): [\d,]+ entries$", out, re.M)


@pytest.mark.db
async def test_extract_params_time_buckets_in_time_order(mcp, fx):
    out = await call(mcp, "extract_params", log_table="fx", template=fx, by="time:6h")
    labels = _by_labels(out)
    assert len(labels) >= 7 and labels == sorted(labels) and "(in time order)" in out
    # More buckets than are shown: the largest ones are kept, then listed in time order.
    out = await call(mcp, "extract_params", log_table="fx", template=fx, by="time:1h")
    labels = _by_labels(out)
    assert len(labels) == 10 and labels == sorted(labels)
    assert re.search(r"showing 10 of \d+ time:1h values \(the largest ones, listed in time order\)", out)


@pytest.mark.db
async def test_extract_params_other_by_stays_largest_first(mcp, fx):
    out = await call(mcp, "extract_params", log_table="fx", template=fx, by="service")
    assert "by service (largest first):" in out
