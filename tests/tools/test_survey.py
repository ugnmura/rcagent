import pytest

from serenedb_extractor.catalog.store import CatalogStore
from tests.conftest import call, container_parquet, id_of, ids_in
from tests.fixtures.data import FX

pytestmark = pytest.mark.db


@pytest.fixture
async def fx_lt(mcp, db_url):
    path = container_parquet(db_url, "fx", FX)
    await call(mcp, "setup_log_table", name="fx", source=path)
    return path


async def test_finds_planted_templates(mcp, fx_lt):
    out = await call(mcp, "survey", log_table="fx")
    assert out.startswith("How this was measured: ")
    assert "timeout after <NUM>ms calling payments" in out and "login failed for user <*>" in out
    assert "disk full on <PATH>" in out
    assert "≈" in out and "estimated from" in out and "NEW" in out and "cover" in out


async def test_estimates_are_near_planted_counts(mcp, fx_lt):
    out = await call(mcp, "survey", log_table="fx")
    line = next(ln for ln in out.splitlines() if "≈3,000 (estimated from a 5k sample" in ln)
    assert "60%" in line


async def test_breakdown(mcp, fx_lt):
    out = await call(mcp, "survey", log_table="fx")
    assert "payments ≈" in out and "gateway ≈" in out


async def test_second_survey_same_ids_no_duplicates(mcp, fx_lt, database):  # Review Focus 5
    a = await call(mcp, "survey", log_table="fx")
    b = await call(mcp, "survey", log_table="fx")
    assert ids_in(a) == ids_in(b) and "NEW" in a and "NEW" not in b
    assert id_of(a, "disk full on <PATH>") == id_of(b, "disk full on <PATH>")
    assert CatalogStore(database).template_count("fx") == len(ids_in(a))


async def test_ids_come_from_the_counter_and_are_not_reused(mcp, fx_lt, database):
    out = await call(mcp, "survey", log_table="fx")
    n = len(ids_in(out))
    assert sorted(ids_in(out)) == sorted(f"T{i}" for i in range(1, n + 1))
    assert database.read("SELECT next_template_no FROM extractor.log_tables WHERE name = 'fx'").scalar() == n + 1


async def test_rare_marked(mcp, fx_lt):
    out = await call(mcp, "survey", log_table="fx", sample_size=200)
    assert "too rare to estimate reliably" in out and "sampled hits" in out


async def test_misspelled_level(mcp, fx_lt):  # Review Focus 1
    out = await call(mcp, "survey", log_table="fx", filters={"level": ["error"]})
    assert "level='error' matched nothing" in out and "ERROR" in out and "no errors" not in out.lower()


async def test_filter_applies_before_sampling(mcp, fx_lt):
    out = await call(mcp, "survey", log_table="fx", filters={"level": "WARN"}, sample_size=500)
    assert "login failed for user <*>" in out and "timeout after" not in out
    assert "≈1,500" in out  # sampled from the filtered population, not from all 5,000


async def test_limit_note(mcp, fx_lt):
    out = await call(mcp, "survey", log_table="fx", limit=1)
    assert "showing 1 of" in out


async def test_time_range_and_zone_are_stated(mcp, fx_lt):
    out = await call(mcp, "survey", log_table="fx", start="2026-03-01", end="2026-03-01T12:00:00", timezone="Europe/Paris")
    assert "Europe/Paris" in out and "timeout after" in out


async def test_exclude_and_confirmed_cost_are_accepted(mcp, fx_lt):
    out = await call(mcp, "survey", log_table="fx", exclude=["T1"], confirmed_cost="x")
    assert out.startswith("How this was measured: ")


async def test_unknown_log_table(mcp):
    assert "no log table named 'nope'" in await call(mcp, "survey", log_table="nope")


async def test_survey_is_not_read_only(mcp):
    tool = next(t for t in (await mcp.list_tools()).tools if t.name == "survey")
    assert tool.annotations is not None and tool.annotations.readOnlyHint is False and tool.annotations.destructiveHint is False
