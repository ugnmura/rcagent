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
    assert "2005-06-11: 60" in out and "groups ordered by time" in out


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
