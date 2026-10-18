"""Indexes (#17): estimates, explicit builds, and queries that use the index relation, at the MCP tool seam."""

from typing import Any

import pytest

from serenedb_extractor.query import cost
from serenedb_extractor.setup import indexes
from tests.conftest import call, container_parquet, token_of
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


async def test_inspect_source_is_read_only_and_gives_rough_sizes(mcp, fx_path, database, monkeypatch):
    monkeypatch.setattr(indexes, "MIN_ROWS_FOR_OFFER", 1000)
    out = await call(mcp, "inspect_source", source=fx_path)
    assert "rough, from column sizes" in out and "create_index with dry_run measures it" in out
    assert "nothing was created or changed" in out.splitlines()[0]
    assert database.read("SELECT table_name FROM information_schema.tables WHERE table_schema = 'extractor'", {}).rows == [] or all(
        r[0] in ("log_tables", "templates", "template_redirects", "log_index_columns", "evidence", "ownership", "ownership_changes",
                 "metric_tables", "trace_tables")
        for r in database.read("SELECT table_name FROM information_schema.tables WHERE table_schema = 'extractor'", {}).rows
    )
    with pytest.raises(Exception, match="log_dict"):
        database.read("SELECT ts_lexize('extractor.log_dict', 'x')", {})
    monkeypatch.undo()
    assert "small enough to search without an index" in await call(mcp, "inspect_source", source=fx_path)


async def test_inspect_source_shows_a_cached_estimate(mcp, fx_path, monkeypatch):
    monkeypatch.setattr(indexes, "MIN_ROWS_FOR_OFFER", 1000)
    monkeypatch.setattr(indexes, "TRIAL_ROWS", 1000)
    await call(mcp, "setup_log_table", name="fx", source=fx_path)
    out = await call(mcp, "inspect_source", source=fx_path)
    assert "from a trial build on 1,000 of 5,000 entries" in out and "rough, from column sizes" not in out


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
    head = after.splitlines()[0]  # every top value came from the index: the header must not say "sampled"
    assert "sampled" not in head and "sample" not in head and "index" in head, head


async def test_search_index_enables_fuzzy(mcp, fx_lt):
    no_index = await call(mcp, "search_logs", log_table="fx", text="dsik full", fuzzy=True)
    assert "search index" in no_index and "disk full on" not in no_index
    await call(mcp, "create_index", log_table="fx", kind="search")
    assert "disk full on" in await call(mcp, "search_logs", log_table="fx", text="dsik full", fuzzy=True)


async def test_text_search_same_answer_with_and_without_index(mcp, fx_lt, monkeypatch):
    queries: list[dict[str, Any]] = [
        {"text": "disk full"},
        {"text": "Disk FULL", "filters": {"level": "ERROR"}},
        {"text": "login failed", "order": "oldest", "limit": 7},
        {"text": "disk full", "start": "2026-03-02", "end": "2026-03-03"},
        {"text": "no such words anywhere"},
    ]
    before = [await call(mcp, "search_logs", log_table="fx", **q) for q in queries]
    await call(mcp, "create_index", log_table="fx", kind="search")
    _expensive(monkeypatch)  # the scan no longer fits the budget, so the index answers
    after = []
    for q in queries:
        out = await call(mcp, "search_logs", log_table="fx", **q)
        if "confirmed_cost=" in out:  # the occurrence-ID lookup is priced; approve it
            out = await call(mcp, "search_logs", log_table="fx", confirmed_cost=token_of(out), **q)
        after.append(out)
    notes = ("Whole words only", "The search index wasn't needed", "Confirmed_cost=")
    for q, b, a in zip(queries, before, after, strict=True):
        assert [ln for ln in _body(b) if not ln.startswith(notes)] == [ln for ln in _body(a) if not ln.startswith(notes)], q
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


async def test_text_without_words_is_refused_for_fuzzy(mcp, fx_lt):
    await call(mcp, "create_index", log_table="fx", kind="search")
    assert "no searchable words" in await call(mcp, "search_logs", log_table="fx", text="---", fuzzy=True)


async def test_fragment_uses_the_scan_when_affordable(mcp, fx_lt):
    await call(mcp, "create_index", log_table="fx", kind="search")
    out = await call(mcp, "search_logs", log_table="fx", text="isk full")
    assert "30 matching entries (exact)" in out and "no index used" in out.splitlines()[0]
    assert "search index wasn't needed" in out


async def test_fragment_through_the_index_carries_the_caveat(mcp, fx_lt, monkeypatch):
    await call(mcp, "create_index", log_table="fx", kind="search")
    _expensive(monkeypatch)
    out = await call(mcp, "search_logs", log_table="fx", text="isk full")
    assert "whole words only" in out.lower() and "'disk' inside 'diskfull'" in out and "search index" in out.splitlines()[0]
    assert "0 matching entries" in out
    words = await call(mcp, "search_logs", log_table="fx", text="disk full")
    assert "30 matching entries" in words and "whole words only" in words.lower()


async def test_occurrence_lookup_is_priced(mcp, fx_lt, monkeypatch):
    await call(mcp, "create_index", log_table="fx", kind="search")
    _expensive(monkeypatch)
    out = await call(mcp, "search_logs", log_table="fx", text="disk full", limit=3)
    assert "30 matching entries" in out and "disk full on" in out
    assert "occurrence ids were not looked up" in out.lower() and "confirmed_cost=" in out and "fx.parquet#" not in out
    again = await call(mcp, "search_logs", log_table="fx", text="disk full", limit=3, confirmed_cost=token_of(out))
    assert "fx.parquet#" in again and "not looked up" not in again


async def test_table_source_indexes_stay_in_the_extractor_schema(mcp, database):
    database.write("DROP TABLE IF EXISTS public.t17_logs")
    database.write("CREATE TABLE public.t17_logs (ts TIMESTAMPTZ, level VARCHAR, message VARCHAR)")
    database.write("INSERT INTO public.t17_logs VALUES ('2026-03-01 00:00:00+00', 'WARN', 'disk almost full')")
    try:
        await call(mcp, "setup_log_table", name="tbl", source="public.t17_logs")
        built = await call(mcp, "create_index", log_table="tbl", kind="filter")
        assert "tbl_filter_idx" in built and "extractor" in built
        assert database.read('SELECT count(*) FROM extractor."tbl_filter_idx"', {}).scalar() == 1
        with pytest.raises(Exception, match="tbl_filter_idx"):
            database.read('SELECT count(*) FROM public."tbl_filter_idx"', {})
        assert "WARN (1)" in await call(mcp, "describe_logs", log_table="tbl")
    finally:
        database.write("DROP VIEW IF EXISTS extractor.lt_tbl")
        database.write("DROP TABLE IF EXISTS public.t17_logs")


async def test_build_refused_when_the_estimate_exceeds_the_limit(mcp, fx_lt, database, monkeypatch):
    monkeypatch.setattr(indexes, "MIN_ROWS_FOR_OFFER", 1000)
    monkeypatch.setattr(indexes, "_trial", lambda *a, **k: (1e9, 1e6))
    out = await call(mcp, "create_index", log_table="fx", kind="filter")
    assert "longer than" in out and "maximum" in out and "600 s" in out and "was not built" in out
    assert "indexes: none" in await call(mcp, "describe_logs", log_table="fx")


async def test_failed_record_drops_the_new_index(mcp, fx_lt, database, monkeypatch):
    from serenedb_extractor.catalog.store import CatalogStore

    def boom(*a, **k):
        raise RuntimeError("catalog down")

    monkeypatch.setattr(CatalogStore, "set_index", boom)
    out = await call(mcp, "create_index", log_table="fx", kind="filter")
    assert "Something went wrong" in out
    with pytest.raises(Exception, match="fx_filter_idx"):
        database.read('SELECT count(*) FROM extractor."fx_filter_idx"', {})


async def test_leftover_trial_objects_are_swept(mcp, fx_lt, database, monkeypatch):
    database.write("CREATE VIEW extractor.trial_1_deadbeef_v AS SELECT 1 AS x")
    await call(mcp, "create_index", log_table="fx", kind="filter", dry_run=True)
    assert _trial_objects(database) == []


async def test_dictionary_creation_tolerates_a_race(db_url, monkeypatch):
    from tests.conftest import _settings
    from serenedb_extractor.context import AppContext

    ctx = AppContext.from_settings(_settings(db_url))
    try:
        indexes.ensure_dictionary(ctx)
        monkeypatch.setattr(indexes, "_dictionary_exists", lambda ctx: False)  # another process created it meanwhile
        indexes.ensure_dictionary(ctx)
    finally:
        ctx.db.close()


async def test_estimates_are_forgotten_when_setup_reruns(mcp, fx_lt, monkeypatch):
    _expensive(monkeypatch)
    await call(mcp, "create_index", log_table="fx", kind="search", dry_run=True)
    assert "search index (≈" in await call(mcp, "search_logs", log_table="fx", text="disk full")
    await call(mcp, "setup_log_table", name="fx", source=fx_lt)
    out = await call(mcp, "search_logs", log_table="fx", text="disk full")
    assert "TOO EXPENSIVE" in out and "search index (≈" not in out


async def test_failed_build_at_setup_is_one_short_line(mcp, fx_path, monkeypatch):
    import psycopg

    from serenedb_extractor.setup import indexes

    def fail(ctx, lt, kind):
        raise psycopg.Error("index build failed\nDETAIL:  out of memory\nHINT:  try a smaller table")

    monkeypatch.setattr(indexes, "build_measured", fail)
    out = await call(mcp, "setup_log_table", name="fx", source=fx_path, build_filter_index=True)
    line = next(ln for ln in out.splitlines() if ln.startswith("The filter index could not be built"))
    assert "out of memory" in line and "HINT: try a smaller table" in line, out


async def test_drop_index_frees_it_and_build_again_works(mcp, fx_lt, database):
    await call(mcp, "create_index", log_table="fx", kind="filter")
    assert "indexes: extractor." in await call(mcp, "describe_logs", log_table="fx")
    out = await call(mcp, "drop_index", log_table="fx", kind="filter")
    assert "Dropped the filter index" in out
    assert "indexes: none" in await call(mcp, "describe_logs", log_table="fx")
    assert "has no filter index; nothing changed" in await call(mcp, "drop_index", log_table="fx", kind="filter")
    assert "Built the filter index" in await call(mcp, "create_index", log_table="fx", kind="filter")
