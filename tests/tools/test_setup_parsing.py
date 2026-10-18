"""Setup round 3: unrecognised raw lines, nested JSON roles, raw files only SereneDB sees, the raw_text hint,
consistent [exact] marks in describe_logs, and what CSV occurrence IDs are."""

import json
import re
from pathlib import Path

import psycopg
import pytest

from rcagent.config import Settings
from rcagent.errors import UserFacingError
from rcagent.setup.paths import resolve_source
from rcagent.setup.rawlog import parse_entries
from rcagent.setup.roles import propose_roles, struct_fields
from rcagent.tools.describe import top_value_lines
from tests.conftest import call

db = pytest.mark.db

PLAIN = "starting worker\nworker ready\n\nshutting down\n"


# ---------------------------------------------------------------- 1. lines without a known format


def test_blank_line_is_not_an_entry_in_lines_format():
    entries = list(parse_entries(PLAIN.splitlines(), "lines", "UTC"))
    assert [e.message for e in entries] == ["starting worker", "worker ready", "shutting down"]
    assert [e.line_start for e in entries] == [1, 2, 4]


@db
async def test_inspect_and_setup_agree_on_unrecognised_lines(mcp, tmp_path: Path):
    p = tmp_path / "plain.log"
    p.write_text(PLAIN)
    out = await call(mcp, "inspect_source", source=str(p))
    assert "line format: none recognised" in out, out
    assert "generic" not in out.split("line format:")[1].split(";")[0]
    samples = out.split("sample entries:")[1]
    assert "1. lines=1-1, message=starting worker" in samples
    assert "3. lines=4-4, message=shutting down" in samples and "⏎" not in samples
    assert "level: absent" in out and "timestamp: ts  (none found" in out
    setup = await call(mcp, "setup_log_table", name="plain", source=str(p))
    assert "line format: none recognised" in setup and "(3 entries)" in setup, setup


@db
async def test_inspect_with_a_line_format_that_matches_nothing_warns(mcp, tmp_path: Path):
    p = tmp_path / "plain2.log"
    p.write_text(PLAIN)
    out = await call(mcp, "inspect_source", source=str(p), line_format="bgl")
    assert "line format: bgl (given by you)" in out and "would refuse" in out


# ---------------------------------------------------------------- 2. nested JSON


def test_struct_fields_parse():
    assert struct_fields('STRUCT("level" VARCHAR, msg VARCHAR, inner STRUCT(a INTEGER, b VARCHAR))') == [
        ("level", "VARCHAR"),
        ("msg", "VARCHAR"),
        ("inner", "STRUCT(a INTEGER, b VARCHAR)"),
    ]
    assert struct_fields("VARCHAR") == []


def test_struct_column_is_never_the_message_and_its_fields_are_proposed():
    cols = [("time", "TIMESTAMP WITH TIME ZONE"), ("log", 'STRUCT("level" VARCHAR, msg VARCHAR, service VARCHAR)')]
    samples = {"log": [json.dumps({"level": "ERROR", "msg": "disk 5 failed", "service": "store"})]}
    roles, evidence = propose_roles(cols, samples)
    assert roles.message == "\"log\" ->> 'msg'"
    assert roles.level == "\"log\" ->> 'level'" and roles.service == "\"log\" ->> 'service'"
    assert roles.timestamp == '"time"'
    assert "field 'msg' inside column 'log'" in evidence["message"] and "disk 5 failed" in evidence["message"]


def test_json_column_fields_come_from_samples():
    cols = [("ts", "TIMESTAMPTZ"), ("log", "JSON")]
    samples = {"log": [json.dumps({"severity": "WARN", "message": "slow disk"})]}
    roles, _ = propose_roles(cols, samples)
    assert roles.message == "\"log\" ->> 'message'" and roles.level == "\"log\" ->> 'severity'"


def test_plain_columns_win_over_nested_fields():
    cols = [("ts", "TIMESTAMPTZ"), ("msg", "VARCHAR"), ("log", "STRUCT(msg VARCHAR, level VARCHAR)")]
    roles, _ = propose_roles(cols, {})
    assert roles.message == '"msg"' and roles.level == "\"log\" ->> 'level'"


def _nested_file(db_url: str, path: str) -> None:
    with psycopg.connect(db_url, autocommit=True) as c:
        c.execute(  # type: ignore[call-overload]
            "COPY (SELECT '2026-03-01T10:00:' || lpad(i::VARCHAR, 2, '0') || '+02:00' AS time, "
            "{'level': CASE WHEN i % 2 = 0 THEN 'ERROR' ELSE 'INFO' END, 'msg': 'disk ' || i::VARCHAR || ' failed'} "
            f"AS log FROM range(10) t(i)) TO '{path}' (FORMAT JSON)"
        )


@db
async def test_nested_json_in_place(mcp, db_url):
    path = "/tmp/r3_nested.json"  # own file name: parallel agents share the container's /tmp
    _nested_file(db_url, path)
    out = await call(mcp, "inspect_source", source=path)
    assert "message: log ->> 'msg'" in out and "level: log ->> 'level'" in out, out
    assert re.search(r'log=\{"level":"ERROR","msg":"disk 0 failed"\}', out), out
    await call(mcp, "setup_log_table", name="nested", source=path)
    desc = await call(mcp, "describe_logs", log_table="nested")
    assert "ERROR (5)" in desc and "INFO (5)" in desc, desc
    found = await call(mcp, "search_logs", log_table="nested", text="disk", filters={"level": "ERROR"})
    assert "disk 4 failed" in found and "disk 3 failed" not in found, found


@db
async def test_nested_json_copied_from_this_machine(mcp, tmp_path: Path):
    p = tmp_path / "nested.jsonl"
    p.write_text(
        "\n".join(
            json.dumps({"time": f"2026-03-01T10:00:{i:02d}+02:00", "log": {"level": "ERROR", "msg": f"disk {i} failed"}})
            for i in range(5)
        )
    )
    out = await call(mcp, "inspect_source", source=str(p))
    assert "message: log ->> 'msg'" in out and "level: log ->> 'level'" in out, out
    setup = await call(mcp, "setup_log_table", name="nestedcopy", source=str(p))
    assert "message: log ->> 'msg'" in setup, setup
    assert "ERROR (5)" in await call(mcp, "describe_logs", log_table="nestedcopy")


# ---------------------------------------------------------------- 3. a raw log only SereneDB can see


@db
async def test_raw_log_only_on_the_sereneDB_side(mcp):
    out = await call(mcp, "inspect_source", source="/tmp/r3_only_in_container_x.log")
    assert "parsed here" in out and "Parquet, JSON or CSV" in out, out
    out = await call(mcp, "setup_log_table", name="nothere", source="/tmp/r3_only_in_container_x.log")
    assert "parsed here" in out and "Parquet, JSON or CSV" in out, out


# ---------------------------------------------------------------- 4. the raw_text hint


def test_raw_and_raw_text_hints_are_both_accepted_and_errors_say_raw_text():
    settings = Settings.from_env({"SERENEDB_READER_URL": "postgresql://x@127.0.0.1:1/x"})
    assert resolve_source("/tmp/a.csv", settings, "raw").kind == "raw_text"
    assert resolve_source("/tmp/a.csv", settings, "raw_text").kind == "raw_text"
    with pytest.raises(UserFacingError, match="raw_text"):
        resolve_source("/tmp/a.csv", settings, "rawtext")


@db
async def test_inspect_names_the_raw_text_kind(mcp, tmp_path: Path):
    p = tmp_path / "x.csv"
    p.write_text(PLAIN)
    out = await call(mcp, "inspect_source", source=str(p), format_hint="raw")
    assert "(raw_text)" in out and "(raw)" not in out


# ---------------------------------------------------------------- 5. [exact] marks in describe_logs


def test_top_values_marks_every_field_when_sources_differ():
    lines = top_value_lines(
        [
            ("level", "ERROR (3)", "sampled"),
            ("service", "no values", "index"),
            ("component", "gateway (2)", "index"),
        ],
        "",
        ["extractor.x_filter_idx"],
    )
    assert lines[1].endswith("[sampled]") and lines[1].startswith("    level:")
    assert lines[2].endswith("[exact, from the index]") and lines[3].endswith("[exact, from the index]")
    assert "[sampled] = from the first" in lines[0]


def test_top_values_mixed_exact_sources_are_both_marked():
    lines = top_value_lines(
        [("level", "ERROR (3)", "counted"), ("service", "a (1)", "index"), ("component", "absent", "absent")],
        "",
        ["i"],
    )
    assert lines[1].endswith("[exact, counted]") and lines[2].endswith("[exact, from the index]")
    assert lines[3] == "    component: absent"


def test_top_values_one_source_needs_no_marks():
    lines = top_value_lines([("level", "ERROR (3)", "counted"), ("service", "a (1)", "counted")], "", [])
    assert lines[0] == "  top values (exact, counted over every entry):"
    assert not any("[" in ln for ln in lines[1:])


# ---------------------------------------------------------------- 6. CSV positions are not row numbers


def test_order_evidence_does_not_call_file_row_number_a_row_number():
    cols = [("ts", "TIMESTAMPTZ"), ("message", "VARCHAR"), ("file_row_number", "BIGINT")]
    _, evidence = propose_roles(cols, {})
    assert "not a row number" in evidence["order"]
