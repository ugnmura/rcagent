import re
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

import pytest

from rcagent.catalog.models import CandidateTemplate
from rcagent.catalog.store import CatalogStore
from rcagent.templating.regex import compile_template
from tests.conftest import call, container_parquet, id_of, ids_in
from tests.fixtures.data import FX

pytestmark = pytest.mark.db


@pytest.fixture
async def fx_lt(mcp, db_url):
    path = container_parquet(db_url, "fx", FX)
    await call(mcp, "setup_log_table", name="fx", source=path)
    return path


async def test_finds_planted_templates(mcp, fx_lt):
    out = await call(mcp, "survey", log_table="fx", sample_size=1000)
    assert out.startswith("How this was measured: ")
    assert "timeout after <NUM>ms calling payments" in out and "login failed for user <*>" in out
    assert "disk full on <PATH>" in out
    assert "≈" in out and "estimated from" in out and "NEW" in out and "cover" in out


async def test_whole_population_sampled_is_exact(mcp, fx_lt):  # R26
    out = await call(mcp, "survey", log_table="fx")
    assert "≈" not in out
    assert "3,000 (exact)" in out and "1,500 (exact)" in out and "30 (exact)" in out
    assert "too rare" not in out and "estimated from" not in out
    assert "exact" in out.splitlines()[0] and "every matching entry" in out.splitlines()[0]


async def test_estimates_are_near_planted_counts(mcp, fx_lt):
    out = await call(mcp, "survey", log_table="fx", sample_size=1000)
    m = re.search(r"≈([\d,]+) \(estimated from a 1k sample, ±\d+%\)", out)
    assert m and 2_500 <= int(m.group(1).replace(",", "")) <= 3_500


async def test_breakdown(mcp, fx_lt):
    out = await call(mcp, "survey", log_table="fx", sample_size=1000)
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


async def test_rare_marked(mcp, fx_lt):  # R29: with 9 sampled entries no template can reach 10 hits, for any seed
    out = await call(mcp, "survey", log_table="fx", sample_size=9)
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


async def test_confirmed_cost_is_never_silently_ignored(mcp, fx_lt):  # R27
    out = await call(mcp, "survey", log_table="fx", confirmed_cost="x")
    assert "confirmed_cost=x was not needed" in out  # cheap: it ran as usual, and says so (#12)
    assert "not needed" not in await call(mcp, "survey", log_table="fx")


async def test_quotes_in_filter_values_are_escaped(mcp, fx_lt):
    out = await call(mcp, "survey", log_table="fx", filters={"service": "o'brien"})
    assert "service='o''brien' matched nothing" in out


def _candidate(text):
    # a real regex and example: a stub regex matching other templates' examples would now generalize them
    compiled = compile_template(text)
    return CandidateTemplate(text, compiled.regex, list(compiled.params), text.replace("<*>", "v"), None, None, 1)


async def test_consecutive_upserts_get_consecutive_ids(mcp, fx_lt, database):  # R28
    store = CatalogStore(database)
    a = store.upsert_survey_templates("fx", [_candidate("alpha <*>")], datetime(2026, 1, 1))
    b = store.upsert_survey_templates("fx", [_candidate("beta <*>"), _candidate("gamma <*>")], datetime(2026, 1, 1))
    assert [t.template_id for t, _ in a.items] == ["T1"]
    assert [t.template_id for t, _ in b.items] == ["T2", "T3"]


async def test_concurrent_upserts_get_distinct_ids(mcp, fx_lt, database):  # R28
    store = CatalogStore(database)

    def go(i):
        return store.upsert_survey_templates("fx", [_candidate(f"word{i} <*>")], datetime(2026, 1, 1)).items[0][0].template_id

    with ThreadPoolExecutor(6) as pool:
        ids = list(pool.map(go, range(6)))
    assert sorted(ids) == sorted(f"T{i}" for i in range(1, 7))
    assert re.fullmatch(r"T\d+", ids[0])


async def test_unknown_log_table(mcp):
    assert "no log table named 'nope'" in await call(mcp, "survey", log_table="nope")


async def test_survey_is_not_read_only(mcp):
    tool = next(t for t in (await mcp.list_tools()).tools if t.name == "survey")
    assert tool.annotations is not None and tool.annotations.readOnlyHint is False and tool.annotations.destructiveHint is False


# A TIMESTAMPTZ_NS timestamp (as in OpenTelemetry Parquet exports): min/max of a nanosecond column
# with sub-microsecond digits come back as text psycopg can't parse ("microsecond must be in
# 0..999999"; spike section 5), so survey reads the timestamp as timestamptz.
NS = """
SELECT (('2026-03-01 00:0' || i::VARCHAR || ':00.' || CASE WHEN i < 5 THEN '000000000' ELSE '123456789' END
          || '+00')::TIMESTAMPTZ_NS) AS ts,
  'disk full on ' || i::VARCHAR AS message
FROM range(10) t(i) ORDER BY i
"""  # the first 5 entries (the ones setup samples) are whole microseconds; the rest are not


async def test_survey_first_and_last_seen_on_a_nanosecond_timestamp(mcp, db_url, database):
    from datetime import datetime

    from rcagent.catalog.store import CatalogStore

    path = container_parquet(db_url, "survey_ns", NS)
    setup = await call(mcp, "setup_log_table", name="ns", source=path)
    assert "Set up log table" in setup, setup
    out = await call(mcp, "survey", log_table="ns")
    assert out.startswith("How this was measured: "), out
    tid = id_of(out, "disk full on <NUM>")
    (t,) = [t for t in CatalogStore(database).templates("ns") if t.template_id == tid]
    assert t.first_seen == datetime(2026, 3, 1, 0, 0), t.first_seen
    assert t.last_seen is not None and t.last_seen.replace(microsecond=0) == datetime(2026, 3, 1, 0, 9), t.last_seen
    assert t.last_seen.microsecond in (123456, 123457), t.last_seen  # nanoseconds cut to microseconds
