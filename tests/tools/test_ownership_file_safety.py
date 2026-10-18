"""Issue #37: edit_team_ownership must not overwrite or leak arbitrary files. Export writes only .csv/.tsv and
replaces a file only with overwrite=True; import reads only .csv/.tsv/.txt files; a parse error never quotes the
file. Symlinks, devices and private places are covered by test_source_and_path_security.py
(test_export_refuses_devices_links_hidden_and_system_places, test_import_reads_only_csv_like_regular_files)."""

from pathlib import Path

import pytest

from serenedb_extractor.errors import UserFacingError
from serenedb_extractor.ownership import Rule, parse_csv
from serenedb_extractor.tools.ownership_tools import _csv_input, _export
from tests.conftest import call
from tests.tools.test_ownership_tools import corpus  # noqa: F401 (fixture)

db = pytest.mark.db

RULES = [Rule("bgl", "component", "KERNEL", "Kernel")]
SECRET = "hunter2-SECRET"


def _err(text: str, log_table: str | None = None) -> str:
    with pytest.raises(UserFacingError) as exc:
        parse_csv(text, log_table, None, "s")
    return str(exc.value)


# ---------------------------------------------------------------- export


@pytest.mark.parametrize("name", [".zshrc", "notes.txt", "run.sh", "own.csv.bak", "id_rsa", "own.json"])
def test_export_refuses_a_name_that_is_not_csv_or_tsv(tmp_path: Path, name: str):
    target = tmp_path / name
    target.write_text("keep")
    with pytest.raises(UserFacingError, match=r"\.csv or \.tsv"):
        _export(RULES, str(target), None, overwrite=True)
    assert target.read_text() == "keep"
    with pytest.raises(UserFacingError, match=r"\.csv or \.tsv"):
        _export(RULES, str(tmp_path / ("new_" + name.lstrip("."))), None)


def test_export_refuses_an_existing_file_without_overwrite(tmp_path: Path):
    target = tmp_path / "own.tsv"
    target.write_text("mine")
    with pytest.raises(UserFacingError, match="overwrite=True"):
        _export(RULES, str(target), None)
    with pytest.raises(UserFacingError, match="overwrite=True"):
        _export(RULES, str(target), None, dry_run=True)
    assert target.read_text() == "mine"
    assert "replaced the file" in _export(RULES, str(target), None, overwrite=True)
    assert "KERNEL" in target.read_text()


# ---------------------------------------------------------------- import


@pytest.mark.parametrize("name", [".env", "id_rsa", "key.pem", "conf.json", "own.csv.bak", "shadow", "own.xlsx"])
def test_import_refuses_other_extensions(tmp_path: Path, name: str):
    p = tmp_path / name
    p.write_text(f"component,team\nA,{SECRET}\n")
    with pytest.raises(UserFacingError, match="not read") as exc:
        _csv_input(str(p), None)
    assert SECRET not in str(exc.value)


@pytest.mark.parametrize("name", ["own.csv", "own.TSV", "own.txt"])
def test_import_reads_csv_tsv_and_txt(tmp_path: Path, name: str):
    p = tmp_path / name
    p.write_text("component,team\nA,B\n")
    assert _csv_input(str(p), None) == ("component,team\nA,B\n", name)


# ---------------------------------------------------------------- no file text in messages


def test_a_parse_error_on_an_arbitrary_file_does_not_echo_its_lines(tmp_path: Path):
    p = tmp_path / "notes.txt"
    p.write_text(f"## private notes\naws_secret_access_key={SECRET}\npassword: {SECRET}\n")
    text, _ = _csv_input(str(p), None)
    msg = _err(text)
    assert SECRET not in msg and "private notes" not in msg and "##" not in msg, msg
    assert "column" in msg, msg


def test_unknown_headers_are_counted_not_named():
    msg = _err(f"component,{SECRET},zzhidden\nA,B,C\n")
    assert SECRET not in msg and "zzhidden" not in msg, msg
    assert "recognised columns are: component (and 2 other column(s))" in msg, msg
    msg = _err(f"component,team,{SECRET}\nA,B,C\n")
    assert SECRET not in msg and "log_table" in msg, msg


def test_skipped_rows_and_bad_cells_are_named_by_line_only():
    msg = _err(f"log_table,component,team,role\nbgl,A,T,{SECRET}\n")
    assert "line 2 skipped" in msg and SECRET not in msg, msg
    rules, notes = parse_csv(f"log_table,component,team,role\nbgl,A,T,component\nbgl,B,T,{SECRET}\n", None, None, "s")
    assert len(rules) == 1 and notes == ["line 3 skipped: its role is not one of component, service"], notes
    for row in (f'bgl,A,"{SECRET}\nx"', f"bgl,A,{SECRET * 10}", f"bgl,{SECRET * 30},T"):
        msg = _err(f"log_table,component,team\n{row}\n")
        assert "Line 2" in msg and SECRET[:6] not in msg, msg
    msg = _err(f"log_table,component,team,area\nbgl,A,T,{SECRET}\x07\n")
    assert "area" in msg and SECRET not in msg, msg


def test_unreadable_csv_is_reported_without_its_text():
    huge = 'log_table,component,team\nbgl,A,"' + SECRET * 20_000 + '"\n'
    msg = _err(huge)
    assert "could not be read as CSV" in msg and SECRET not in msg, msg


@db
async def test_import_through_the_tool_does_not_echo_a_private_file(mcp, corpus, tmp_path: Path):
    p = tmp_path / "secrets.txt"
    p.write_text(f"token={SECRET}\nuser,{SECRET}\n")
    out = await call(mcp, "edit_team_ownership", action="import", csv_path=str(p))
    assert SECRET not in out and "token" not in out, out
    p = tmp_path / "half.csv"
    p.write_text(f"log_table,component,team,role\nbgl,KERNEL,K,component\nbgl,X,Y,{SECRET}\n")
    out = await call(mcp, "edit_team_ownership", action="import", csv_path=str(p), dry_run=True)
    assert "line 3 skipped" in out and SECRET not in out, out
