import json
import shutil
from pathlib import Path

import pytest

from serenedb_extractor.query import cost
from serenedb_extractor.query.coverage import untimestamped_note, untimestamped_text
from serenedb_extractor.query.filters import parse_time_range

from tests.conftest import call, first_occurrence, id_of

pytestmark = pytest.mark.db

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
PARITY = "instruction cache parity error corrected"


async def _setup(mcp, tmp_path, name: str, fixture: str) -> None:
    dest = tmp_path / fixture
    shutil.copy(FIXTURES / fixture, dest)
    await call(mcp, "setup_log_table", name=name, source=str(dest))


@pytest.fixture
async def bgl_lt(mcp, tmp_path):
    await _setup(mcp, tmp_path, "bgl", "bgl_sample.log")


@pytest.fixture
async def os_lt(mcp, tmp_path):
    await _setup(mcp, tmp_path, "openstack", "openstack_sample.log")


@pytest.fixture
async def app_lt(mcp, tmp_path):
    await _setup(mcp, tmp_path, "app", "generic_with_stacktrace.log")


@pytest.fixture
async def bgl_surveyed(mcp, bgl_lt):
    out = await call(mcp, "survey", log_table="bgl")
    return id_of(out, PARITY)


async def test_survey_raw(mcp, bgl_lt, os_lt):
    assert PARITY in await call(mcp, "survey", log_table="bgl")
    assert "<NUM>" in await call(mcp, "survey", log_table="openstack")


async def test_exact_on_copied(mcp, bgl_surveyed):
    out = await call(mcp, "locate_occurrences", log_table="bgl", templates=[bgl_surveyed], group_by=["host"])
    assert "e:" in out and "≈" not in out
    assert "≈" not in await call(mcp, "extract_params", log_table="bgl", template=bgl_surveyed)


async def test_context_keeps_stacktrace(mcp, app_lt):
    occ = first_occurrence(await call(mcp, "search_logs", log_table="app", text="refund failed"))
    out = await call(mcp, "get_context", log_table="app", occurrence=occ)
    assert "NullPointerException" in out
    assert out.index("charge accepted order=1001") < out.index("NullPointerException") < out.index("login failed for user bob")


async def test_untimestamped_note(mcp, app_lt):
    out = await call(mcp, "survey", log_table="app", start="2026-10-17", end="2026-10-18")
    assert untimestamped_text(1)[:-1] in out


async def test_no_note_without_range(mcp, app_lt):
    assert "no timestamp and" not in await call(mcp, "survey", log_table="app")


async def test_note_on_trend_and_locate(mcp, app_lt):
    s = await call(mcp, "survey", log_table="app")
    tid = id_of(s, "refund failed")
    kw = dict(start="2026-03-01", end="2026-03-02")
    assert untimestamped_text(1)[:-1] in await call(mcp, "locate_occurrences", log_table="app", templates=[tid], **kw)
    assert untimestamped_text(1)[:-1] in await call(mcp, "trend", log_table="app", **kw)


def test_wording():
    assert untimestamped_text(1) == "1 entry in this log table has no timestamp and is outside any time range."
    assert untimestamped_text(3) == "3 entries in this log table have no timestamp and are outside any time range."


async def _jsonl_nulls(mcp, tmp_path):
    p = tmp_path / "nulls.jsonl"
    rows = [{"ts": f"2026-03-01T00:00:{i:02d}", "level": "INFO", "msg": f"hello {i}"} for i in range(10)]
    rows += [{"level": "INFO", "msg": "no time a"}, {"level": "INFO", "msg": "no time b"}]
    p.write_text("\n".join(json.dumps(r) for r in rows))
    await call(mcp, "setup_log_table", name="nulls", source=str(p))


async def test_plural_note(mcp, tmp_path):
    await _jsonl_nulls(mcp, tmp_path)
    out = await call(mcp, "survey", log_table="nulls", start="2026-03-01", end="2026-03-02")
    assert untimestamped_text(2) in out


async def test_too_expensive_is_said(mcp, tmp_path, monkeypatch):
    await _jsonl_nulls(mcp, tmp_path)
    ctx = mcp.made[0] if mcp.made else None
    assert ctx is not None
    lt = ctx.store.get_log_table("nulls")
    tr = parse_time_range("2026-03-01", "2026-03-02", "UTC")
    monkeypatch.setattr(cost, "BUDGET_SECONDS", 0.0)
    note = untimestamped_note(ctx.db, lt, tr)
    assert note is not None and "Couldn't count entries without a timestamp" in note
    assert untimestamped_note(ctx.db, lt, parse_time_range(None, None, "UTC")) is None


async def test_note_on_extract_params_and_search_logs(mcp, app_lt):
    s = await call(mcp, "survey", log_table="app")
    tid = id_of(s, "charge accepted order=<NUM>")
    kw = dict(start="2026-03-01", end="2026-03-02")
    assert untimestamped_text(1)[:-1] in await call(mcp, "extract_params", log_table="app", template=tid, **kw)
    assert untimestamped_text(1)[:-1] in await call(mcp, "search_logs", log_table="app", text="refund", **kw)
    assert "no timestamp and" not in await call(mcp, "search_logs", log_table="app", text="refund")
