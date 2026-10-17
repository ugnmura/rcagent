"""Indexes (#17): estimates, explicit builds, and queries that use the index relation, at the MCP tool seam."""

from typing import Any

import pytest

from serenedb_extractor.query import cost
from serenedb_extractor.setup import indexes
from tests.conftest import call, container_parquet
from tests.fixtures.data import FX

pytestmark = pytest.mark.db

FX_FILE = "t17_fx"  # own file name: parallel agents share the container's /tmp


@pytest.fixture
async def fx_path(db_url):
    return container_parquet(db_url, FX_FILE, FX)


@pytest.fixture
async def fx_lt(mcp, fx_path):
    out = await call(mcp, "setup_log_table", name="fx", source=fx_path)
    assert "Set up log table" in out, out
    return fx_path


def _body(out: str) -> list[str]:
    """The answer without the first line (how it was measured), which names the index path."""
    return out.splitlines()[1:]


def _trial_objects(database) -> list[str]:
    rows = database.read("SELECT table_name FROM information_schema.tables WHERE table_name LIKE 'trial%%'", {}).rows
    return [r[0] for r in rows]


def _expensive(monkeypatch) -> None:
    """Make every scan of the tiny fixture too expensive: ~1 KB/s against a 1 ms budget."""
    monkeypatch.setattr(cost, "BUDGET_SECONDS", 0.001)
    monkeypatch.setattr(cost, "THROUGHPUT_BYTES_PER_S", {"remote": 1.0, "local": 1e3})


async def test_setup_builds_nothing_by_default(mcp, fx_path):
    out = await call(mcp, "setup_log_table", name="fx", source=fx_path)
    assert "small enough to search without an index" in out and "No index was built" in out
    assert "indexes: none" in await call(mcp, "describe_logs", log_table="fx")


async def test_offer_shows_estimates_for_big_sources(mcp, fx_path, database, monkeypatch):
    monkeypatch.setattr(indexes, "MIN_ROWS_FOR_OFFER", 1000)
    monkeypatch.setattr(indexes, "TRIAL_ROWS", 1000)
    out = await call(mcp, "setup_log_table", name="fx", source=fx_path)
    assert "filter index: ≈" in out and "search index: ≈" in out and "to build" in out
    assert "from a trial build on 1,000 of 5,000 entries" in out
    assert "No index was built" in out
    assert "indexes: none" in await call(mcp, "describe_logs", log_table="fx")
    assert _trial_objects(database) == []  # trial view and indexes are dropped again


async def test_inspect_source_offers_estimates(mcp, fx_path, database, monkeypatch):
    monkeypatch.setattr(indexes, "MIN_ROWS_FOR_OFFER", 1000)
    monkeypatch.setattr(indexes, "TRIAL_ROWS", 1000)
    out = await call(mcp, "inspect_source", source=fx_path)
    assert "filter index: ≈" in out and "search index: ≈" in out
    assert _trial_objects(database) == []
    monkeypatch.undo()
    assert "small enough to search without an index" in await call(mcp, "inspect_source", source=fx_path)


async def test_dry_run_then_build(mcp, fx_lt):
    dry = await call(mcp, "create_index", log_table="fx", kind="filter", dry_run=True)
    assert "estimated" in dry.lower() and "nothing was built" in dry.lower()
    assert "indexes: none" in await call(mcp, "describe_logs", log_table="fx")
    built = await call(mcp, "create_index", log_table="fx", kind="filter")
    assert "fx_filter_idx" in built and "built" in built.lower()
    d = await call(mcp, "describe_logs", log_table="fx")
    assert "fx_filter_idx" in d and "sampled — rare values" not in d


async def test_create_index_twice_and_bad_kind(mcp, fx_lt):
    await call(mcp, "create_index", log_table="fx", kind="filter")
    again = await call(mcp, "create_index", log_table="fx", kind="filter")
    assert "already" in again.lower()
    bad = await call(mcp, "create_index", log_table="fx", kind="bloom")
    assert "filter" in bad and "search" in bad


async def test_filter_index_values_equal_the_scan(mcp, fx_lt):
    before = await call(mcp, "describe_logs", log_table="fx")
    await call(mcp, "create_index", log_table="fx", kind="filter")
    after = await call(mcp, "describe_logs", log_table="fx")
    for role in ("level", "service", "component"):
        a = [ln.strip() for ln in before.splitlines() if ln.strip().startswith(f"{role}:")]
        b = [ln.strip() for ln in after.splitlines() if ln.strip().startswith(f"{role}:")]
        assert a and b and b[0].startswith(a[0]), (a, b)  # same values and counts; the index adds a note
    assert "payments (3,000)" in after and "exact" in after


async def test_search_index_enables_fuzzy(mcp, fx_lt):
    no_index = await call(mcp, "search_logs", log_table="fx", text="dsik full", fuzzy=True)
    assert "search index" in no_index and "disk full on" not in no_index
    await call(mcp, "create_index", log_table="fx", kind="search")
    assert "disk full on" in await call(mcp, "search_logs", log_table="fx", text="dsik full", fuzzy=True)


async def test_text_search_same_answer_with_and_without_index(mcp, fx_lt):
    queries: list[dict[str, Any]] = [
        {"text": "disk full"},
        {"text": "Disk FULL", "filters": {"level": "ERROR"}},
        {"text": "login failed", "order": "oldest", "limit": 7},
        {"text": "disk full", "start": "2026-03-02", "end": "2026-03-03"},
        {"text": "no such words anywhere"},
    ]
    before = [await call(mcp, "search_logs", log_table="fx", **q) for q in queries]
    await call(mcp, "create_index", log_table="fx", kind="search")
    after = [await call(mcp, "search_logs", log_table="fx", **q) for q in queries]
    for q, b, a in zip(queries, before, after, strict=True):
        assert _body(b) == _body(a), q
    assert "search index" in after[0].splitlines()[0]
    assert "30 matching entries (exact)" in after[0] and "fx.parquet#" in after[0]


async def test_index_lowers_cost(mcp, fx_lt, monkeypatch):
    _expensive(monkeypatch)
    fv = lambda: call(mcp, "describe_logs", log_table="fx", find_values={"role_or_column": "service", "like": "pay"})
    before = await fv()
    await call(mcp, "create_index", log_table="fx", kind="filter")
    assert "TOO EXPENSIVE" in before and "payments" in await fv()


async def test_refusal_names_the_index_size_once_estimated(mcp, fx_lt, monkeypatch):
    _expensive(monkeypatch)
    ask = await call(mcp, "search_logs", log_table="fx", text="disk full")
    assert "TOO EXPENSIVE" in ask and "≈" not in ask
    await call(mcp, "create_index", log_table="fx", kind="search", dry_run=True)
    ask = await call(mcp, "search_logs", log_table="fx", text="disk full")
    assert "TOO EXPENSIVE" in ask and "search index (≈" in ask
    await call(mcp, "create_index", log_table="fx", kind="search")
    assert "disk full on" in await call(mcp, "search_logs", log_table="fx", text="disk full")


async def test_copied_table_gets_an_index(mcp, tmp_path):
    log = tmp_path / "app.log"
    log.write_text(
        "2026-03-01 10:00:00 ERROR [payments] refund failed for order 7\n"
        "2026-03-01 10:00:05 INFO [web] request ok\n"
        "2026-03-01 10:00:09 ERROR [payments] refund failed for order 9\n"
    )
    out = await call(mcp, "setup_log_table", name="app", source=str(log))
    if "Set up log table" not in out:
        pytest.skip("raw files are not readable in this environment: " + out[:120])
    built = await call(mcp, "create_index", log_table="app", kind="search")
    assert "app_search_idx" in built
    found = await call(mcp, "search_logs", log_table="app", text="refund failed")
    assert "2 matching entries (exact)" in found and "e:" in found
    fuzzy = await call(mcp, "search_logs", log_table="app", text="refnud faild", fuzzy=True)
    assert "refund failed" in fuzzy


async def test_text_without_words_still_searches_by_substring(mcp, fx_lt):
    await call(mcp, "create_index", log_table="fx", kind="search")
    out = await call(mcp, "search_logs", log_table="fx", text="/dev/sd")
    assert "30 matching entries (exact)" in out  # "/dev/sd" is a substring, not whole words: the scan answers it
    odd = await call(mcp, "search_logs", log_table="fx", text="---", fuzzy=True)
    assert "no searchable words" in odd
