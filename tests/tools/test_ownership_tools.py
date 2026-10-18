"""show_team_ownership and edit_team_ownership: importing, editing and exporting the team-ownership table."""

import re
import shutil
from pathlib import Path

import pytest

from serenedb_extractor import ownership
from serenedb_extractor.catalog.schema import bootstrap
from tests.conftest import call

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
pytestmark = pytest.mark.db

ORGANISERS = "dataset,component,team\nbgl,KERNEL,Kernel Team\nbgl,MMCS,Control Team\n"


@pytest.fixture
async def corpus(mcp, tmp_path):
    for name, fixture in (("bgl", "bgl_sample.log"), ("openstack", "openstack_sample.log")):
        dest = tmp_path / fixture
        shutil.copy(FIXTURES / fixture, dest)
        await call(mcp, "setup_log_table", name=name, source=str(dest))


async def test_show_ownership_says_the_stand_in_is_fictional_and_shows_coverage(mcp, corpus):
    out = await call(mcp, "show_team_ownership")
    assert "from stand-in (fictional" in out and "not an official mapping" in out
    assert "Node OS <- KERNEL" in out
    assert re.search(r"log table bgl \(teams by component, 2 distinct values, 200 entries, exact\)", out), out
    assert "Node OS: 197, 98.5%" in out and "every component value has a team" in out
    describe = await call(mcp, "describe_logs", log_table="bgl")
    assert "stand-in teams are fictional" in describe


async def test_import_replaces_only_the_log_tables_the_file_covers(mcp, corpus):
    out = await call(mcp, "edit_team_ownership", action="import", csv_text=ORGANISERS)
    assert "Ownership table updated (import, imported from pasted CSV" in out
    assert "+ bgl component 'KERNEL' -> Kernel Team" in out
    assert "- bgl% component 'KERNEL' (was Node OS)" in out  # the stand-in rules for bgl are gone
    assert "Kernel Team: 197, 98.5%" in out
    assert "1 component value(s) without a team" in out and "APP: 3" in out
    counts = await call(mcp, "count_logs", log_tables=["bgl"], group_by=["team"])
    assert "Kernel Team: 197" in counts and "Unassigned: 3" in counts and "Node OS" not in counts
    shown = await call(mcp, "show_team_ownership", log_table="openstack", coverage=False)
    assert "Cloud API" in shown  # other log tables keep their rules
    describe = await call(mcp, "describe_logs", log_table="bgl")
    assert "imported from pasted CSV" in describe and "fictional" not in describe


async def test_import_from_a_file_with_other_headers_and_a_default_log_table(mcp, corpus, tmp_path):
    f = tmp_path / "owners.csv"
    f.write_text("Component;Owner;Description\nKERNEL;Kernel Team;the kernel\nAPP;Apps Team;\n", encoding="utf-8")
    out = await call(mcp, "edit_team_ownership", action="import", csv_path=str(f), log_table="bgl")
    assert "imported from owners.csv" in out and "every component value has a team" in out
    shown = await call(mcp, "show_team_ownership", log_table="bgl", coverage=False)
    assert "Apps Team <- APP" in shown and "Kernel Team <- KERNEL" in shown


async def test_merge_keeps_and_replace_all_drops_the_other_rules(mcp, corpus):
    await call(mcp, "edit_team_ownership", action="import", csv_text=ORGANISERS, mode="merge")
    merged = await call(mcp, "show_team_ownership", log_table="bgl", coverage=False)
    assert "Node OS <- KERNEL" in merged and "Kernel Team <- KERNEL" in merged  # bgl% and bgl rules side by side
    await call(mcp, "edit_team_ownership", action="import", csv_text=ORGANISERS, mode="replace_all")
    everything = await call(mcp, "show_team_ownership", coverage=False)
    assert everything.startswith("2 ownership rules for 2 teams") and "Cloud API" not in everything


async def test_set_remove_and_remove_a_team(mcp, corpus):
    out = await call(
        mcp, "edit_team_ownership", action="set", rules=[{"log_table": "bgl%", "component": "KERNEL", "team": "Kernel Team"}]
    )
    assert "~ bgl% component 'KERNEL': Node OS -> Kernel Team" in out and "set by hand" in out
    out = await call(mcp, "edit_team_ownership", action="remove", rules=[{"log_table": "bgl%", "component": "APP"}])
    assert "- bgl% component 'APP' (was HPC Applications)" in out and "APP: 3" in out
    out = await call(mcp, "edit_team_ownership", action="remove", team="cloud api")
    assert re.search(r"0 added, 0 changed, [1-9]\d* removed", out) and "(was Cloud API)" in out
    assert "no rule names the team 'Nobody'" in await call(mcp, "edit_team_ownership", action="remove", team="Nobody")


async def test_dry_run_changes_nothing(mcp, corpus):
    out = await call(mcp, "edit_team_ownership", action="import", csv_text=ORGANISERS, dry_run=True)
    assert out.startswith("Dry run: nothing was changed") and "+ bgl component 'KERNEL' -> Kernel Team" in out
    assert "Node OS <- KERNEL" in await call(mcp, "show_team_ownership", coverage=False)


async def test_export_then_import_round_trips(mcp, corpus, tmp_path):
    out = await call(mcp, "edit_team_ownership", action="export", csv_path=str(tmp_path))
    assert "Wrote" in out and (tmp_path / "ownership.csv").is_file()
    text = (tmp_path / "ownership.csv").read_text(encoding="utf-8")
    assert text.startswith("log_table,role,pattern,team,area,source\n")
    again = await call(mcp, "edit_team_ownership", action="import", csv_path=str(tmp_path / "ownership.csv"))
    assert "Nothing to change" in again


async def test_reset_restores_the_stand_in(mcp, corpus):
    await call(mcp, "edit_team_ownership", action="import", csv_text=ORGANISERS, mode="replace_all")
    out = await call(mcp, "edit_team_ownership", action="reset")
    assert "Node OS" in out and "(was Kernel Team)" in out
    assert "Node OS <- KERNEL" in await call(mcp, "show_team_ownership", coverage=False)


async def test_a_restart_does_not_bring_the_stand_in_back_after_an_import(mcp, corpus, database):
    await call(mcp, "edit_team_ownership", action="import", csv_text=ORGANISERS, mode="replace_all")
    bootstrap(database)  # what every server start does
    n = database.read("SELECT count(*) FROM extractor.ownership", {}).rows[0][0]
    assert n == 2


async def test_bad_input_is_explained(mcp, corpus):
    assert "needs a column naming the component" in await call(
        mcp, "edit_team_ownership", action="import", csv_text="a,b\n1,2\n"
    )
    assert "no log table (or dataset) column" in await call(
        mcp, "edit_team_ownership", action="import", csv_text="component,team\nKERNEL,K\n"
    )
    assert "either csv_path" in await call(mcp, "edit_team_ownership", action="import")
    assert "action must be one of" in await call(mcp, "edit_team_ownership", action="frobnicate")
    out = await call(mcp, "edit_team_ownership", action="import", csv_text="dataset,component,team\nbgl,KERNEL,\nbgl,APP,Apps\n")
    assert "line 2 skipped: no team" in out


def test_parse_csv_reads_roles_and_skips_duplicates():
    rules, notes = ownership.parse_csv(
        "log_table\tservice\tteam\ntextbench\tcart\tShop\ntextbench\tcart\tOther\n", None, None, "x"
    )
    assert [(r.role, r.pattern, r.team) for r in rules] == [("service", "cart", "Shop"), ("service", "cart", "Other")]
    change = ownership.plan_change([], rules)
    assert [r.team for r in change.added] == ["Shop"]
    assert any("duplicate" in n for n in notes)


async def test_upgrade_adds_the_source_column_to_an_old_table(mcp, corpus, database):
    database.write("DROP TABLE IF EXISTS extractor.ownership")
    database.write(
        "CREATE TABLE extractor.ownership (log_table VARCHAR NOT NULL, role VARCHAR NOT NULL, pattern VARCHAR NOT NULL,"
        " team VARCHAR NOT NULL, area VARCHAR, PRIMARY KEY (log_table, role, pattern))"
    )
    database.write("INSERT INTO extractor.ownership VALUES ('bgl%', 'component', 'KERNEL', 'Node OS', NULL)")
    ownership.upgrade(database)
    assert database.read("SELECT source FROM extractor.ownership", {}).rows == [(ownership.STAND_IN,)]
