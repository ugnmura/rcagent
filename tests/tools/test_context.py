"""get_context and template tags (#14), at the MCP tool seam."""

import pytest

from tests.conftest import call, container_parquet, first_occurrence
from tests.fixtures.data import FX
from tests.fixtures.data_t14 import CTX

pytestmark = pytest.mark.db


@pytest.fixture
async def fx_lt(mcp, db_url):
    path = container_parquet(db_url, "t14_fx", FX)
    await call(mcp, "setup_log_table", name="fx", source=path)
    return path


@pytest.fixture
async def ctx_lt(mcp, db_url):
    path = container_parquet(db_url, "t14_ctx", CTX)
    out = await call(mcp, "setup_log_table", name="ctxfx", source=path)
    assert "Set up log table" in out, out
    await call(mcp, "survey", log_table="ctxfx")
    return path


async def _occ(mcp, text: str) -> str:
    return first_occurrence(await call(mcp, "search_logs", log_table="ctxfx", text=text, order="oldest", limit=1))


async def test_trace_scope_shows_cause(mcp, ctx_lt):
    occ = await _occ(mcp, "refused")
    out = await call(mcp, "get_context", log_table="ctxfx", occurrence=occ)
    assert "pool exhausted" in out and "other-service" not in out and "→" in out and "±5 min" in out
    assert out.startswith("How this was measured: ")


async def test_everything_scope(mcp, ctx_lt):
    occ = await _occ(mcp, "refused")
    assert "other-service" in await call(mcp, "get_context", log_table="ctxfx", occurrence=occ, scope="everything")


async def test_wider_window(mcp, ctx_lt):
    occ = await _occ(mcp, "refused")
    narrow = await call(mcp, "get_context", log_table="ctxfx", occurrence=occ, window_minutes=0.01)
    wide = await call(mcp, "get_context", log_table="ctxfx", occurrence=occ, window_minutes=10)
    assert "pool exhausted" not in narrow and "pool exhausted" in wide


async def test_absent_scope(mcp, fx_lt):
    occ = first_occurrence(await call(mcp, "search_logs", log_table="fx", text="disk"))
    assert "available scopes" in await call(mcp, "get_context", log_table="fx", occurrence=occ, scope=["host"])


async def test_long_entry_cut(mcp, ctx_lt):  # Review Focus 4
    occ = await _occ(mcp, "IllegalStateException")
    assert "…(cut)" in await call(mcp, "get_context", log_table="ctxfx", occurrence=occ)


async def test_tags_and_bad_occurrence(mcp, ctx_lt):
    assert "[T" in await call(mcp, "search_logs", log_table="ctxfx", text="refused")
    assert "occurrence" in (await call(mcp, "get_context", log_table="ctxfx", occurrence="garbage")).lower()


async def test_before_after_limits_and_default_service_host(mcp, ctx_lt):
    occ = await _occ(mcp, "refused")
    out = await call(mcp, "get_context", log_table="ctxfx", occurrence=occ, scope=["service", "host"], before=1, after=1)
    assert "checkout" in out and "pool exhausted" not in out
