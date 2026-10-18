"""Security round 3: system and extractor tables as sources, .. in paths, which files may be read, and what the
ownership export may write."""

import os
from pathlib import Path

import psycopg
import pytest

from rcagent.config import Settings
from rcagent.errors import UserFacingError
from rcagent.ownership import Rule, parse_csv
from rcagent.setup.paths import resolve_source
from rcagent.tools.ownership_tools import _csv_input, _export, _rule_from
from tests.conftest import call

db = pytest.mark.db

PLAIN = Settings.from_env({"SERENEDB_READER_URL": "postgresql://x@127.0.0.1:1/x"})
MOUNTED = Settings.from_env(
    {"SERENEDB_READER_URL": "postgresql://x@127.0.0.1:1/x", "LOGS_HOST_DIR": "/mnt/hostlogs", "LOGS_CONTAINER_DIR": "/data/loghub"}
)


# ---------------------------------------------------------------- 1. table sources


@pytest.mark.parametrize(
    "name",
    [
        "pg_catalog.pg_authid",
        "PG_CATALOG.pg_authid",
        "information_schema.tables",
        "pg_toast.pg_toast_1",
        "pg_temp_3.t",
        "extractor.ownership",
        "extractor.lt_other",
        "Extractor.catalog",
    ],
)
def test_tables_in_system_or_extractor_schemas_are_refused(name):
    with pytest.raises(UserFacingError, match="schema"):
        resolve_source(name, PLAIN, "table")


def test_tables_in_user_schemas_are_allowed():
    assert resolve_source("public.my_logs", PLAIN, "table").kind == "table"
    assert resolve_source("my_logs", PLAIN).kind == "table"


@db
async def test_setup_of_a_system_table_is_refused_and_creates_no_view(mcp, database):
    out = await call(
        mcp, "setup_log_table", name="authx", source="pg_catalog.pg_authid", format_hint="table", roles={"message": "rolname"}
    )
    assert "pg_catalog schema" in out and "Set up" not in out, out
    out = await call(mcp, "inspect_source", source="information_schema.tables")
    assert "information_schema schema" in out and "columns" not in out, out
    views = database.read("SELECT count(*) FROM information_schema.tables WHERE table_name = 'lt_authx'", {}).scalar()
    assert views == 0


@db
async def test_a_table_in_public_still_works(mcp, db_url):
    with psycopg.connect(db_url, autocommit=True) as conn:
        conn.execute("DROP TABLE IF EXISTS public.r3sec_logs")
        conn.execute("CREATE TABLE public.r3sec_logs (ts TIMESTAMP, msg VARCHAR)")
        conn.execute("INSERT INTO public.r3sec_logs VALUES ('2026-03-01 10:00:00', 'hello')")
    try:
        out = await call(mcp, "setup_log_table", name="r3secpub", source="r3sec_logs", format_hint="table")
        assert "Set up log table 'r3secpub'" in out and "entries: 1" in out, out
    finally:
        with psycopg.connect(db_url, autocommit=True) as conn:
            conn.execute("DROP VIEW IF EXISTS extractor.lt_r3secpub")
            conn.execute("DROP TABLE IF EXISTS public.r3sec_logs")


# ---------------------------------------------------------------- 2. .. in paths


def test_dotdot_leaving_the_mounted_folder_is_refused():
    with pytest.raises(UserFacingError, match="leave the mounted logs folder"):
        resolve_source("/data/loghub/../../etc/passwd", MOUNTED, "csv")
    with pytest.raises(UserFacingError, match="leave the mounted logs folder"):
        resolve_source("/mnt/hostlogs/../other/app.log", MOUNTED)
    with pytest.raises(UserFacingError, match="climbs out"):
        resolve_source("../secret/app.log", PLAIN)


def test_dotdot_inside_the_mounted_folder_is_normalised():
    rs = resolve_source("/data/loghub/a/../b.parquet", MOUNTED)
    assert rs.db_path == "/data/loghub/b.parquet"
    rs = resolve_source("/mnt/hostlogs/x/./../y.log", MOUNTED)
    assert rs.db_path == "/data/loghub/y.log" and rs.host_path == "/mnt/hostlogs/y.log"


# ---------------------------------------------------------------- 3. which files may be read


@pytest.mark.parametrize("path", ["/etc/passwd", "/etc/passwd.csv", "/proc/self/environ.json", "/dev/zero.log",
                                  "/private/etc/hosts.txt", "/root/app.log", "/e*/hosts.csv", "/ETC/x.csv"])
def test_system_locations_and_non_log_files_are_refused(path):
    with pytest.raises(UserFacingError, match="not read"):
        resolve_source(path, PLAIN, "csv")


def test_a_format_hint_does_not_lift_the_extension_rule(tmp_path: Path):
    p = tmp_path / "notes.dat"
    p.write_text("a\nb\n")
    with pytest.raises(UserFacingError, match="log and data files"):
        resolve_source(str(p), PLAIN, "raw")
    with pytest.raises(UserFacingError, match="log and data files"):
        resolve_source("/tmp/r3sec_*", PLAIN, "parquet")


def test_hidden_folders_and_links_into_system_locations_are_refused(tmp_path: Path):
    hidden = tmp_path / ".ssh"
    hidden.mkdir()
    (hidden / "id.log").write_text("secret\n")
    with pytest.raises(UserFacingError, match="hidden"):
        resolve_source(str(hidden / "id.log"), PLAIN)
    with pytest.raises(UserFacingError, match="hidden"):
        resolve_source("~/.aws/credentials.txt", PLAIN)
    link = tmp_path / "innocent.log"
    os.symlink("/etc/hosts", link)
    with pytest.raises(UserFacingError, match="system location"):
        resolve_source(str(link), PLAIN)


def test_ordinary_log_files_and_remote_urls_still_resolve(tmp_path: Path):
    p = tmp_path / "app.log.gz"
    p.write_bytes(b"")
    assert resolve_source(str(p), PLAIN).kind == "raw_text"
    assert resolve_source("/tmp/r3sec_x.parquet", PLAIN).kind == "parquet"
    assert resolve_source("https://example.com/a/../logs", PLAIN, "parquet").remote


@db
async def test_inspect_does_not_print_a_host_or_container_file(mcp):
    out = await call(mcp, "inspect_source", source="/etc/passwd")
    assert "not read" in out and "root:" not in out, out
    out = await call(mcp, "inspect_source", source="/etc/hostname", format_hint="csv")
    assert "not read" in out and "columns" not in out, out
    out = await call(mcp, "setup_log_table", name="pw", source="/tmp/../etc/passwd", format_hint="csv")
    assert "not read" in out and "root:" not in out, out


# ---------------------------------------------------------------- 4. ownership files and names

RULES = [Rule("bgl", "component", "KERNEL", "Kernel")]


def test_export_needs_a_csv_name_and_overwrite_to_replace(tmp_path: Path):
    sentinel = tmp_path / "keep.txt"
    sentinel.write_text("keep")
    with pytest.raises(UserFacingError, match=r"\.csv or \.tsv"):
        _export(RULES, str(sentinel), None)
    with pytest.raises(UserFacingError, match=r"\.csv or \.tsv"):
        _export(RULES, str(tmp_path / "run.sh"), None)
    assert sentinel.read_text() == "keep"
    target = tmp_path / "own.csv"
    assert "Wrote 1" in _export(RULES, str(target), None)
    target.write_text("mine")
    with pytest.raises(UserFacingError, match="overwrite=True"):
        _export(RULES, str(target), None)
    assert target.read_text() == "mine"
    assert "replaced the file" in _export(RULES, str(target), None, overwrite=True)
    assert "KERNEL" in target.read_text()


def test_export_refuses_devices_links_hidden_and_system_places(tmp_path: Path):
    with pytest.raises(UserFacingError, match="not written|csv"):
        _export(RULES, "/dev/null", None, overwrite=True)
    folder = tmp_path / "x.csv"
    folder.mkdir()
    (folder / "ownership.csv").mkdir()
    with pytest.raises(UserFacingError, match="not a regular file"):
        _export(RULES, str(folder), None, overwrite=True)
    link = tmp_path / "link.csv"
    os.symlink(tmp_path / "elsewhere.csv", link)
    (tmp_path / "elsewhere.csv").write_text("x")
    with pytest.raises(UserFacingError, match="not a regular file"):
        _export(RULES, str(link), None, overwrite=True)
    (tmp_path / ".config").mkdir()
    with pytest.raises(UserFacingError, match="hidden"):
        _export(RULES, str(tmp_path / ".config" / "own.csv"), None)
    with pytest.raises(UserFacingError, match="system location"):
        _export(RULES, "/etc/own.csv", None, overwrite=True)


def test_import_reads_only_csv_like_regular_files(tmp_path: Path):
    with pytest.raises(UserFacingError, match="not read"):
        _csv_input("/etc/passwd", None)
    with pytest.raises(UserFacingError, match="system location"):
        _csv_input("/etc/own.csv", None)
    (tmp_path / ".aws").mkdir()
    (tmp_path / ".aws" / "c.csv").write_text("component,team\nA,B\n")
    with pytest.raises(UserFacingError, match="hidden"):
        _csv_input(str(tmp_path / ".aws" / "c.csv"), None)
    (tmp_path / "d.csv").mkdir()
    with pytest.raises(UserFacingError, match="not a regular file"):
        _csv_input(str(tmp_path / "d.csv"), None)
    ok = tmp_path / "own.txt"
    ok.write_text("component,team\nA,B\n")
    assert _csv_input(str(ok), None)[1] == "own.txt"


def test_team_and_area_names_are_one_short_line():
    with pytest.raises(UserFacingError, match="line break"):
        _rule_from({"log_table": "bgl", "component": "A", "team": "X\nlog_table,role"}, None, None, "s", True)
    with pytest.raises(UserFacingError, match="at most 80"):
        _rule_from({"log_table": "bgl", "component": "A", "team": "T" * 81}, None, None, "s", True)
    with pytest.raises(UserFacingError, match="area"):
        _rule_from({"log_table": "bgl", "component": "A", "team": "X", "area": "a\rb"}, None, None, "s", True)
    r = _rule_from({"log_table": "bgl", "component": "A", "team": "  Kernel  "}, None, None, "s", True)
    assert r.team == "Kernel"
    with pytest.raises(UserFacingError, match="Line 2"):
        parse_csv('log_table,component,team\nbgl,A,"two\nlines"\n', None, None, "s")


def test_a_list_as_a_rule_value_is_refused():
    with pytest.raises(UserFacingError, match="list"):
        _rule_from({"log_table": "bgl", "component": ["APP"], "team": "X"}, None, None, "s", True)


@db
async def test_set_refuses_lists_and_notes_schema_qualified_tables(mcp):
    out = await call(mcp, "edit_team_ownership", action="set", rules=[{"log_table": "bgl", "component": ["APP"], "team": "X"}])
    assert "list" in out and "['APP']" not in out.split("(")[0], out
    out = await call(mcp, "edit_team_ownership", action="set", rules=[{"log_table": "public.bgl", "component": "APP", "team": "X"}])
    assert "schema-qualified" in out, out
    out = await call(mcp, "edit_team_ownership", action="set", rules=[{"log_table": "bgl", "component": "APP", "team": "a\nb"}])
    assert "line break" in out and "Ownership table updated" not in out, out


@db
async def test_export_through_the_tool_takes_overwrite(mcp, tmp_path: Path):
    target = tmp_path / "own.csv"
    target.write_text("mine")
    out = await call(mcp, "edit_team_ownership", action="export", csv_path=str(target))
    assert "overwrite=True" in out and target.read_text() == "mine", out
    out = await call(mcp, "edit_team_ownership", action="export", csv_path=str(target), overwrite=True)
    assert "replaced the file" in out and target.read_text() != "mine", out


def test_a_wildcard_that_could_match_a_hidden_folder_is_refused():
    import pytest

    from rcagent.errors import UserFacingError
    from rcagent.setup.paths import check_private_path

    for p in ("/Users/me/*ssh/id.log", "/Users/me/?aws/x.csv", "/Users/me/[.]x/y.log", "/Users/me/x/[.]y.log"):
        with pytest.raises(UserFacingError, match="hidden|only in the file name|start with a wildcard"):
            check_private_path(p, p)


async def test_export_through_a_linked_folder_is_checked_after_the_link(mcp, tmp_path):
    import os

    hidden = tmp_path / ".private"
    hidden.mkdir()
    link = tmp_path / "innocent"
    os.symlink(hidden, link)
    out = await call(mcp, "edit_team_ownership", action="export", csv_path=str(link / "rules.csv"))
    assert "hidden" in out and not (hidden / "rules.csv").exists()


def test_wildcards_only_in_the_file_name():
    import pytest

    from rcagent.errors import UserFacingError
    from rcagent.setup.paths import check_private_path

    with pytest.raises(UserFacingError, match="only in the file name"):
        check_private_path("/Users/me/lo*/x.log", "/Users/me/lo*/x.log")
    check_private_path("/data/loghub/part_*.parquet", "/data/loghub/part_*.parquet")


def test_final_round_path_rules():
    import pytest

    from rcagent.config import Settings
    from rcagent.errors import UserFacingError
    from rcagent.setup.paths import check_private_path, resolve_source

    s = Settings.from_env({"SERENEDB_READER_URL": "postgresql://x@localhost/db"})
    with pytest.raises(UserFacingError, match="scheme"):
        resolve_source("file:///etc/x.csv", s)
    check_private_path("/logs/app_*.csv", "/logs/app_*.csv")  # a wildcard after a plain start is fine
    with pytest.raises(UserFacingError, match="may not start with a wildcard"):
        check_private_path("/logs/*.csv", "/logs/*.csv")
    limited = Settings.from_env({"SERENEDB_READER_URL": "postgresql://x@localhost/db", "SERENEDB_SOURCE_DIRS": "/data/logs"})
    with pytest.raises(UserFacingError, match="SERENEDB_SOURCE_DIRS"):
        resolve_source("/tmp/elsewhere_r3.csv", limited)
    assert resolve_source("/data/logs/a_r3.csv", limited).db_path == "/data/logs/a_r3.csv"


def test_rule_fields_and_export_cells_are_safe():
    import pytest

    from rcagent import ownership
    from rcagent.errors import UserFacingError

    for bad in ("STJ\nPROBE", "A‮B", "x​y"):
        with pytest.raises(UserFacingError):
            ownership.clean_name(bad, "component", 200)
    out = ownership.to_csv([ownership.Rule("bgl", "component", "KERNEL", '=HYPERLINK("x")')])
    assert "'=HYPERLINK" in out
