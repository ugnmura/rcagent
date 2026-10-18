"""Round-3 fixes: CSV input messages, per-source summary wording, role hints that fit the action, rules on a role a
log table lacks shown under its coverage, rename_parameter limits and case, and drop_index's header."""

import shutil
from pathlib import Path

import pytest

from tests.conftest import call, container_parquet, id_of
from tests.fixtures.data import FX

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
pytestmark = pytest.mark.db


@pytest.fixture
async def corpus(mcp, tmp_path):
    for name, fixture in (("bgl", "bgl_sample.log"), ("openstack", "openstack_sample.log")):
        dest = tmp_path / fixture
        shutil.copy(FIXTURES / fixture, dest)
        await call(mcp, "setup_log_table", name=name, source=str(dest))


@pytest.fixture
async def fx_lt(mcp, db_url):
    path = container_parquet(db_url, "r3own_fx", FX)  # own file name: parallel agents share the container's /tmp
    await call(mcp, "setup_log_table", name="fx", source=path)
    return path


async def test_csv_input_messages_say_what_was_wrong(mcp, corpus):
    empty = await call(mcp, "edit_team_ownership", action="import", csv_text="")
    assert "The CSV is empty" in empty and "not both" not in empty
    blank = await call(mcp, "edit_team_ownership", action="import", csv_text="  \n")
    assert "The CSV is empty" in blank
    neither = await call(mcp, "edit_team_ownership", action="import")
    assert "neither was given" in neither and "not both" not in neither
    both = await call(mcp, "edit_team_ownership", action="import", csv_text="a,b\n", csv_path="/tmp/x.csv")
    assert "not both: both were given" in both


async def test_summary_reads_naturally_for_every_source(mcp, corpus):
    await call(mcp, "edit_team_ownership", action="import", csv_text="dataset,component,team\nbgl,KERNEL,K\nbgl,APP,A\n")
    await call(mcp, "edit_team_ownership", action="set", rules=[{"log_table": "bgl", "component": "MMCS", "team": "M"}])
    out = await call(mcp, "show_team_ownership", coverage=False)
    first = out.splitlines()[0]
    assert "from imported" not in first and "from set by hand" not in first, first
    assert "2 imported from pasted CSV on " in first and "1 set by hand on " in first
    assert "from stand-in (fictional" in out  # the stand-in still says where it comes from


async def test_role_hint_fits_the_action(mcp, corpus):
    out = await call(mcp, "edit_team_ownership", action="set", rules=[{"log_table": "bgl", "service": "x", "team": "T"}])
    assert "log table bgl has no service field" in out
    assert 'write "component" in the rule instead of "service"' in out and "when importing" not in out
    out = await call(mcp, "edit_team_ownership", action="import", csv_text="dataset,service,team\nbgl,y,T\n", mode="merge")
    assert "give role='component' (or a role column) when importing" in out


async def test_rules_on_a_missing_role_are_listed_under_coverage(mcp, corpus):
    await call(mcp, "edit_team_ownership", action="set", rules=[
        {"log_table": "bgl", "service": "x", "team": "T"},
        {"log_table": "bgl", "service": "y", "team": "T"},
    ])
    out = await call(mcp, "show_team_ownership", log_table="bgl")
    coverage = out[out.index("Coverage"):]
    assert "2 rules on service, which this log table does not have: they match nothing" in coverage
    other = await call(mcp, "show_team_ownership", log_table="openstack")
    assert "which this log table does not have" not in other


async def test_rename_is_case_insensitive_and_limits_the_length(mcp, fx_lt):
    tid = id_of(await call(mcp, "survey", log_table="fx"), "login failed for user <*>")
    out = await call(mcp, "rename_parameter", log_table="fx", template=tid, old_name="USER", new_name="username")
    assert "Parameter 'user' is now 'username'" in out
    long = "a" * 41
    out = await call(mcp, "rename_parameter", log_table="fx", template=tid, old_name="username", new_name=long)
    assert "too long for a parameter name (41 characters)" in out and "40" in out
    ok = "b" * 40
    assert f"is now '{ok}'" in await call(mcp, "rename_parameter", log_table="fx", template=tid, old_name="USERNAME", new_name=ok)


async def test_drop_index_without_an_index_says_nothing_was_removed(mcp, fx_lt):
    out = await call(mcp, "drop_index", log_table="fx", kind="filter")
    head = out.splitlines()[0]
    assert "nothing removed" in head and "index removed" not in head, head
    assert "has no filter index; nothing changed" in out
