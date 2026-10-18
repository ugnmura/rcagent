"""Cost-aware survey (#12), at the MCP tool seam: the cost check picks the sampling method,
asks when nothing fits, honours confirmations and cancels on timeout."""

import re

import psycopg
import pytest

from rcagent.query import cost
from rcagent.tools import survey as survey_mod
from tests.conftest import call, container_parquet, id_of, token_of
from tests.fixtures.data import FX
from tests.fixtures.data_t12 import FX_BIG

pytestmark = pytest.mark.db

FX_FILE = "t12_fx"  # own file names: parallel agents share the container's /tmp
BIG_PATH = "/tmp/t12_fx_big.parquet"  # FX_BIG in 15 row groups of 2,048 entries
SLOW = " AND (SELECT max(hash(i)) FROM range(10000000000) t(i)) > 0"  # really scans (#10: count(*) is answered too fast)


def _write(db_url: str, select_sql: str, path: str) -> str:
    with psycopg.connect(db_url, autocommit=True) as conn:
        conn.execute(f"COPY ({select_sql}) TO '{path}' (FORMAT PARQUET, ROW_GROUP_SIZE 2048)")  # type: ignore[call-overload]
    return path


@pytest.fixture
async def fx_lt(mcp, db_url):
    path = container_parquet(db_url, FX_FILE, FX)
    await call(mcp, "setup_log_table", name="fx", source=path)
    return path


@pytest.fixture
async def fx_lt_short(mcp_short_timeout, db_url):
    path = container_parquet(db_url, FX_FILE, FX)
    out = await call(mcp_short_timeout, "setup_log_table", name="fx", source=path)
    assert "Set up log table" in out, out
    return path


@pytest.fixture
async def big_lt(mcp, db_url):
    path = _write(db_url, FX_BIG, BIG_PATH)
    out = await call(mcp, "setup_log_table", name="big", source=path)
    assert "Set up log table" in out, out
    return path


async def test_population_estimated_when_expensive(mcp, big_lt, monkeypatch):
    # Excluding a template makes the exact count read the whole message column (~100 KB here);
    # at 6 KB/s a 5-block sample (~145 KB with its per-block counts) fits the 30 s budget, the
    # sample plus that count does not, so the population is estimated from the blocks.
    timeout_id = id_of(await call(mcp, "survey", log_table="big", sample_size=2048), "timeout after <NUM>ms calling payments")
    monkeypatch.setattr(cost, "THROUGHPUT_BYTES_PER_S", {"remote": 1.0, "local": 6e3})
    out = await call(mcp, "survey", log_table="big", exclude=[timeout_id], sample_size=2048)
    assert out.startswith("How this was measured: "), out
    assert "population estimated" in out and "block sample of 5 row groups" in out.splitlines()[0]
    assert "timeout after" not in out and "login failed for user <*>" in out
    assert "an exact count of the matching entries would read" in out.lower() and "(exact)" not in out


async def test_ask_then_confirm(mcp, fx_lt, monkeypatch):
    monkeypatch.setattr(cost, "BUDGET_SECONDS", 0.0)
    ask = await call(mcp, "survey", log_table="fx")
    assert "TOO EXPENSIVE" in ask and "confirmed_cost=" in ask
    assert "timeout after" not in ask and "T1" not in ask  # nothing was run or saved
    done = await call(mcp, "survey", log_table="fx", confirmed_cost=token_of(ask))
    assert done.startswith("How this was measured: ") and "timeout after <NUM>ms calling payments" in done
    assert "run as you confirmed" in done.splitlines()[0] and "3,000 (exact)" in done


async def test_sampling_stated(mcp, fx_lt, big_lt):
    reservoir = (await call(mcp, "survey", log_table="fx", sample_size=1000)).splitlines()[0]
    assert "reservoir sample of 1,000 of the 5,000 matching entries" in reservoir
    every = (await call(mcp, "survey", log_table="fx")).splitlines()[0]
    assert "every matching entry" in every and "reservoir" not in every
    blocks = (await call(mcp, "survey", log_table="big", sample_size=2048)).splitlines()[0]
    assert "block sample of 5 row groups (10,240 of 30,720 entries" in blocks


async def test_block_sample_takes_at_least_five_blocks(mcp, big_lt):  # R46
    # 2,048 wanted entries would be a single row group; five are cheap here, so margins are estimable.
    out = await call(mcp, "survey", log_table="big", sample_size=2048)
    assert "block sample of 5 row groups" in out.splitlines()[0]
    assert "30,720 entries match" in out and "population estimated" not in out  # the count is cheap: exact
    assert "≈" in out and "±" in out and "margin not estimable" not in out
    assert "timeout after <NUM>ms calling payments" in out and "(exact)" not in out


async def test_cut_row_groups_say_up_to(mcp, big_lt):  # R41
    out = await call(mcp, "survey", log_table="big", start="2026-03-01T00:30:00", sample_size=2048)
    assert "of up to" in out.splitlines()[0] and "block sample of" in out.splitlines()[0]


async def test_unneeded_confirmation_is_said(mcp, fx_lt):  # R27: never silently ignored
    out = await call(mcp, "survey", log_table="fx", confirmed_cost="1KB")
    assert "confirmed_cost" in out and "not needed" in out and "3,000 (exact)" in out


async def test_survey_timeout(mcp_short_timeout, fx_lt_short, monkeypatch):
    monkeypatch.setattr(survey_mod, "SURVEY_SQL_SUFFIX", SLOW)
    out = await call(mcp_short_timeout, "survey", log_table="fx")
    assert out.startswith("TIMEOUT after 1s") and "narrow" in out
    monkeypatch.setattr(survey_mod, "SURVEY_SQL_SUFFIX", "")
    assert "timeout after <NUM>ms" in await call(mcp_short_timeout, "survey", log_table="fx")


RG_PATH = "/tmp/t12_fx_rg.parquet"  # FX in three row groups: 2,048 + 2,048 + 904 entries


@pytest.fixture
async def fxrg_lt(mcp, db_url):
    path = _write(db_url, FX, RG_PATH)
    out = await call(mcp, "setup_log_table", name="fxrg", source=path)
    assert "Set up log table" in out, out
    return path


async def test_block_sample_masks_a_capped_spread(mcp, big_lt):  # R57
    # 2,048 wanted over 5 blocks of 2,048: at most ceil(2048 / 5) = 410 entries masked per block,
    # every 5th entry of each, so the masking work stays near the sample size.
    out = await call(mcp, "survey", log_table="big", sample_size=2048)
    head = out.splitlines()[0]
    assert "every 5th entry" in head and "close together in time, so margins may understate the error" in head
    assert re.search(r"≈[\d,]+ \(estimated from a 2,0\d\d sample, ±\d+%\)", out), out
    assert "30,720 entries match" in out  # the population is still counted over every entry


async def test_few_blocks_give_a_rough_estimate(mcp, fxrg_lt, monkeypatch):  # R38 in survey
    # 1 KB/s: reading all three row groups (~65 KB) is over budget, one row group (~22 KB) fits.
    monkeypatch.setattr(cost, "THROUGHPUT_BYTES_PER_S", {"remote": 1.0, "local": 1e3})
    out = await call(mcp, "survey", log_table="fxrg", sample_size=1000)
    assert "block sample of 1 row group" in out.splitlines()[0]
    assert "margin not estimable from 1 block" in out and "±" not in out
