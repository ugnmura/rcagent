"""The evidence log (footer + show_evidence), team ownership as a role, and count_logs."""

import re
import shutil
from pathlib import Path

import pytest

from serenedb_extractor import ownership
from serenedb_extractor.setup.paths import expand_files
from tests.conftest import call, call_raw

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
pytestmark = pytest.mark.db


async def _setup(mcp, tmp_path, name: str, fixture: str) -> None:
    dest = tmp_path / fixture
    shutil.copy(FIXTURES / fixture, dest)
    out = await call(mcp, "setup_log_table", name=name, source=str(dest))
    assert f"log table '{name}'" in out


@pytest.fixture
async def corpus(mcp, tmp_path):
    await _setup(mcp, tmp_path, "bgl", "bgl_sample.log")
    await _setup(mcp, tmp_path, "openstack", "openstack_sample.log")


# ---- evidence ------------------------------------------------------------------------------------


async def test_every_result_carries_an_evidence_handle_with_its_queries(mcp, corpus):
    out = await call_raw(mcp, "count_logs", log_tables=["bgl"], filters={"level": "FATAL"})
    m = re.search(r"Evidence \[(Q\d+)\]", out)
    assert m, out
    handle = m.group(1)
    assert f"{handle}.1" in out or "metadata lookup" in out
    assert "SELECT" in out and "'FATAL'" in out  # the query is shown with its filter filled in
    full = await call(mcp, "show_evidence", ids=[handle])
    assert f"[{handle}] count_logs(" in full and "level" in full and "result:" in full
    assert "94 matching entries (exact)" in full  # the result is kept with the queries


async def test_evidence_numbers_increase_and_are_listed(mcp, corpus):
    a = await call_raw(mcp, "describe_logs", log_table="bgl")
    b = await call_raw(mcp, "describe_logs", log_table="openstack")
    qa, qb = (int(re.search(r"Evidence \[Q(\d+)\]", x).group(1)) for x in (a, b))
    assert qb == qa + 1
    listing = await call(mcp, "show_evidence")
    assert f"[Q{qb}]" in listing and f"[Q{qa}]" in listing and "describe_logs" in listing


async def test_show_evidence_unknown_and_bad_ids(mcp, corpus):
    assert "not found" in await call(mcp, "show_evidence", ids=["Q999999"])
    assert "not an evidence ID" in await call(mcp, "show_evidence", ids=["nonsense"])


async def test_show_evidence_has_no_footer_of_its_own(mcp, corpus):
    await call(mcp, "describe_logs")
    out = await call_raw(mcp, "show_evidence")
    assert "Evidence [Q" not in out


# ---- teams ---------------------------------------------------------------------------------------


async def test_team_role_is_derived_from_ownership(mcp, corpus):
    out = await call(mcp, "describe_logs", log_table="bgl")
    assert "team: from the ownership table on component" in out and "Node OS" in out


async def test_count_logs_by_team_over_the_whole_corpus(mcp, corpus):
    out = await call(mcp, "count_logs", group_by=["team"])
    assert "Counted 2 log tables separately (bgl, openstack)" in out
    assert "Log table bgl: 200 matching entries (exact)." in out
    assert re.search(r"Node OS: 197, 98\.5%", out), out
    assert "Cloud API" in out and "Compute Service" in out


async def test_team_filter_and_group_in_other_tools(mcp, corpus):
    out = await call(mcp, "search_logs", log_table="bgl", filters={"team": "HPC Applications"}, limit=5)
    assert "3 matching entries (exact)" in out and "team=HPC Applications" in out
    await call(mcp, "survey", log_table="bgl", filters={"level": "FATAL"})
    located = await call(mcp, "locate_occurrences", log_table="bgl", templates=["T1"], group_by=["team"])
    assert "Node OS" in located


async def test_survey_shows_owning_teams(mcp, corpus):
    out = await call(mcp, "survey", log_table="openstack")
    assert "teams: Cloud API" in out


async def test_a_table_without_rules_has_no_team(mcp, tmp_path):
    await _setup(mcp, tmp_path, "applog", "generic_with_stacktrace.log")
    out = await call(mcp, "count_logs", log_tables=["applog"], group_by=["team"])
    assert "No team ownership rule covers" in out


async def test_count_logs_text_and_time_bucket(mcp, corpus):
    out = await call(mcp, "count_logs", log_tables=["bgl"], text="interrupt", group_by=["time:1d"])
    assert "message contains 'interrupt'" in out
    assert "2005-06-11: 60" in out and "in time order" in out


async def test_count_logs_cuts_and_says_so(mcp, corpus):
    out = await call(mcp, "count_logs", log_tables=["openstack"], group_by=["component"], limit=2)
    assert "showing 2 of" in out


def test_team_of_prefers_the_most_specific_pattern():
    rules = [
        ownership.Rule("x%", "component", "nova.%", "Broad"),
        ownership.Rule("x%", "component", "nova.compute.%", "Narrow"),
    ]
    assert ownership.team_of("nova.compute.manager", rules) == "Narrow"
    assert ownership.team_of("nova.api.x", rules) == "Broad"
    assert ownership.team_of("other", rules) == ownership.UNASSIGNED
    expr = ownership.team_expr('"component"', rules)
    assert expr.index("nova.compute.%") < expr.index("'nova.%'")


def test_packaged_ownership_covers_both_base_datasets():
    rules = ownership.packaged_rules()
    assert {r.team for r in rules if r.covers_table("bgl")} >= {"Node OS", "HPC Applications", "Hardware Reliability"}
    assert {r.team for r in rules if r.covers_table("openstack")} >= {"Cloud API", "Compute Service", "Virtualization"}


# ---- several files -------------------------------------------------------------------------------


def test_brace_ranges_expand_to_files():
    files = expand_files("https://h/text_bench/part_{000..002}.parquet")
    assert files == [f"https://h/text_bench/part_00{i}.parquet" for i in range(3)]
    assert expand_files("s3://b/{a,b}.parquet") == ["s3://b/a.parquet", "s3://b/b.parquet"]
    assert expand_files("/x/y.parquet") == ["/x/y.parquet"]


async def test_describe_samples_top_values_when_counting_is_expensive(mcp, corpus, monkeypatch):
    from serenedb_extractor.query import cost

    monkeypatch.setattr(cost, "BUDGET_SECONDS", 0.0)
    out = await call(mcp, "describe_logs", log_table="bgl")
    assert "sampled — rare values may be missing" in out and "KERNEL" in out


async def test_trend_never_calls_new_across_a_gap_in_the_logs(mcp, tmp_path):
    lines = [f"2026-03-01T{h:02d}:00:00Z ERROR [db] connection reset by peer" for h in range(24)]
    lines += [f"2026-03-03T{h:02d}:00:00Z INFO [web] request served" for h in range(24)]
    lines += [f"2026-03-03T{h:02d}:30:00Z ERROR [db] disk quota exceeded on volume 7" for h in range(24)]
    path = tmp_path / "gappy.log"
    path.write_text("\n".join(lines) + "\n")
    await call(mcp, "setup_log_table", name="gappy", source=str(path))
    await call(mcp, "survey", log_table="gappy")
    out = await call(mcp, "trend", log_table="gappy", start="2026-03-03", end="2026-03-04", exact=True)
    # 2 March has no entries at all: the data's span covers it, but the logs do not
    assert "no entries at all in the preceding period" in out and "limited comparison" in out
    assert "new in this period" not in out


async def test_find_values_takes_the_documented_form(mcp, corpus):
    short = await call(mcp, "describe_logs", log_table="bgl", find_values={"level": "fat"})
    long = await call(mcp, "describe_logs", log_table="bgl", find_values={"role_or_column": "level", "like": "fat"})
    assert "FATAL" in short and short == long
    assert "one field at a time" in await call(mcp, "describe_logs", log_table="bgl", find_values={"level": "x", "host": "y"})


async def test_hour_buckets_keep_both_hours_when_clocks_go_back(mcp, tmp_path):
    """Generic lines with explicit offsets: 01:30 PDT and 01:30 PST on 2005-10-30 are two different hours."""
    log = tmp_path / "fallback.log"
    log.write_text(
        "2005-10-30T01:30:00-07:00 INFO first pass\n2005-10-30T01:30:00-08:00 INFO second pass\n"
        "2005-10-30T01:40:00-08:00 INFO second pass again\n",
        encoding="utf-8",
    )
    await call(mcp, "setup_log_table", name="fb", source=str(log), timezone="America/Los_Angeles")
    out = await call(mcp, "count_logs", log_tables=["fb"], group_by=["time:1h"])
    assert "2005-10-30 01:00-07:00: 1" in out and "2005-10-30 01:00-08:00: 2" in out
    week = await call(mcp, "count_logs", log_tables=["fb"], group_by=["time:7d"])
    assert "2005-10-24: 3" in week  # weeks start on a Monday


async def test_input_checks_and_one_line_entries(mcp, corpus):
    assert "empty list" in await call(mcp, "search_logs", log_table="bgl", filters={"level": []})
    assert "IS NULL" in await call(mcp, "search_logs", log_table="bgl", filters={"level": None})
    assert "give 1 or more" in await call(mcp, "search_logs", log_table="bgl", limit=0)
    found = await call(mcp, "search_logs", log_table="openstack", limit=1)
    occ = re.search(r"\s(e:\d+|\S+#\d+)\s", found).group(1)
    out = await call(mcp, "get_context", log_table="openstack", occurrence=occ, scope=["component"],
                     filters={"level": "INFO"}, before=1, after=1)
    assert "the same component" in out and "level='INFO'" in out.splitlines()[0]
    assert "before and after are numbers" in await call(mcp, "get_context", log_table="openstack", occurrence=occ, before=-1)


def test_entry_text_keeps_one_line():
    from serenedb_extractor import format as fmt

    assert fmt.entry_text("Traceback\n  File x\r\n  boom") == "Traceback ⏎   File x ⏎   boom"


async def test_an_occurrence_id_may_name_just_the_file(mcp, db_url):
    from tests.conftest import container_parquet
    from tests.fixtures.data import FX

    path = container_parquet(db_url, "fx_short", FX)
    await call(mcp, "setup_log_table", name="fxs", source=path)
    found = await call(mcp, "search_logs", log_table="fxs", limit=1)
    occ = re.search(r"\s(\S+#\d+)\s", found).group(1)
    out = await call(mcp, "get_context", log_table="fxs", occurrence=occ.rsplit("/", 1)[-1], scope="everything")
    assert "→" in out and occ in out


async def test_raw_openstack_logs_get_service_and_trace(mcp, corpus):
    desc = await call(mcp, "describe_logs", log_table="openstack")
    assert "service: attrs ->> 'service'" in desc and "trace: attrs ->> 'trace'" in desc
    counts = await call(mcp, "count_logs", log_tables=["openstack"], group_by=["service"])
    assert "nova-api:" in counts and "nova-compute:" in counts
    found = await call(mcp, "search_logs", log_table="openstack", filters={"service": "nova-api"}, limit=1)
    occ = re.search(r"\s(e:\d+)\s", found).group(1)
    ctx_out = await call(mcp, "get_context", log_table="openstack", occurrence=occ)
    assert "the narrowest available context scope: the same trace" in ctx_out


async def test_a_timestamp_role_on_a_column_without_times_is_refused(mcp, db_url):
    from tests.conftest import container_parquet
    from tests.fixtures.data import FX

    path = container_parquet(db_url, "fx_badts", FX)
    out = await call(mcp, "setup_log_table", name="badts", source=path, roles={"timestamp": "level"})
    assert "holds values that are not times" in out and re.search(r"\(e\.g\. '(ERROR|WARN|INFO)'\)", out)
    fixed = await call(mcp, "setup_log_table", name="badts", source=path)  # nothing was registered: a clean setup works
    assert "Set up log table 'badts'" in fixed
    await call(mcp, "setup_log_table", name="goodts", source=path)
    again = await call(mcp, "setup_log_table", name="goodts", source=path, roles={"timestamp": "service"})
    assert "holds values that are not times" in again
