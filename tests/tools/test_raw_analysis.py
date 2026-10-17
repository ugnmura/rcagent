import shutil
from pathlib import Path

import pytest

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
    assert "1 entry in this log table has no timestamp and is outside any time range" in out


async def test_no_note_without_range(mcp, app_lt):
    assert "no timestamp and" not in await call(mcp, "survey", log_table="app")


async def test_note_on_trend_and_locate(mcp, app_lt):
    s = await call(mcp, "survey", log_table="app")
    tid = id_of(s, "refund failed")
    kw = dict(start="2026-03-01", end="2026-03-02")
    assert "1 entry in this log table has no timestamp and is outside any time range" in await call(mcp, "locate_occurrences", log_table="app", templates=[tid], **kw)
    assert "1 entry in this log table has no timestamp and is outside any time range" in await call(mcp, "trend", log_table="app", **kw)
