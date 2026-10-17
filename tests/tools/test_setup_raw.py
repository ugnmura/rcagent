import json
import os
import shutil
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import psycopg
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
import pytest_asyncio

from serenedb_extractor.context import AppContext
from serenedb_extractor.setup.rawlog import LINE_FORMATS, detect_line_format, parse_entries
from tests.conftest import _client, _reset_schema, _settings, call

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


def copy_fixture(tmp_path: Path, name: str) -> Path:
    dest = tmp_path / name
    shutil.copy(FIXTURES / name, dest)
    return dest


def fixture_lines(name: str) -> list[str]:
    return (FIXTURES / name).read_text().splitlines()


# --- line formats and multi-line entries (pure parsing, per-case precision) ---


def test_stacktrace_is_one_entry_spanning_its_lines():
    lines = fixture_lines("generic_with_stacktrace.log")
    assert detect_line_format(lines) == "generic"
    entries = list(parse_entries(lines, "generic", "UTC"))
    assert [(e.line_start, e.line_end) for e in entries] == [(1, 1), (2, 2), (3, 3), (4, 7), (8, 8), (9, 9)]
    refund = entries[3]
    assert refund.level == "ERROR" and refund.component == "payments"
    assert refund.message.splitlines() == [
        "refund failed",
        "java.lang.NullPointerException: refund is null",
        "    at com.acme.Refund.apply(Refund.java:42)",
        "    at com.acme.Handler.run(Handler.java:10)",
    ]
    assert refund.ts == datetime(2026, 3, 1, 10, 0, 2, tzinfo=UTC)


def test_lines_before_the_first_timestamp_form_one_entry_without_ts():
    entries = list(parse_entries(["banner one", "banner two", "2026-03-01 10:00:00 INFO [a] x"], "generic", "UTC"))
    assert entries[0].ts is None and entries[0].message == "banner one\nbanner two"
    assert (entries[0].line_start, entries[0].line_end) == (1, 2)
    assert entries[1].ts is not None


def test_zoneless_timestamps_use_the_given_zone():
    (e,) = parse_entries(["2026-03-01 10:00:00 INFO [a] x"], "generic", "Europe/Paris")
    assert e.ts == datetime(2026, 3, 1, 9, 0, 0, tzinfo=UTC)
    (z,) = parse_entries(["2026-03-01T10:00:00+02:00 INFO [a] x"], "generic", "Europe/Paris")
    assert z.ts == datetime(2026, 3, 1, 8, 0, 0, tzinfo=UTC)


def test_trailing_blank_lines_are_not_part_of_an_entry():
    entries = list(parse_entries(["2026-03-01 10:00:00 ERROR [a] boom", "  at x", "", "", "2026-03-01 10:00:01 INFO [a] ok"], "generic", "UTC"))
    assert [(e.line_start, e.line_end) for e in entries] == [(1, 2), (5, 5)]


def test_bgl_line_maps_to_fields():
    lines = fixture_lines("bgl_sample.log")
    assert detect_line_format(lines) == "bgl"
    entries = list(parse_entries(lines, "bgl", "UTC"))
    assert len(entries) == len(lines) and all(e.ts for e in entries)
    first = entries[0]
    assert (first.level, first.component, first.host) == ("INFO", "KERNEL", "R02-M1-N0-C:J12-U11")
    assert first.message == "instruction cache parity error corrected"
    assert first.ts == datetime(2005, 6, 3, 15, 42, 50, 675872, tzinfo=UTC)
    assert first.attrs["label"] == "-" and first.attrs["type"] == "RAS"


def test_openstack_line_maps_to_fields():
    lines = fixture_lines("openstack_sample.log")
    assert detect_line_format(lines) == "openstack"
    entries = list(parse_entries(lines, "openstack", "UTC"))
    assert len(entries) == len(lines) and all(e.ts for e in entries)
    first = entries[0]
    assert (first.level, first.component, first.host) == ("INFO", "nova.osapi_compute.wsgi.server", None)
    assert first.message.startswith('10.11.10.1 "GET /v2/54fadb412c4e40cdbaed9335e4c35a9e/servers/detail')
    assert first.ts == datetime(2017, 5, 16, 0, 0, 0, 8000, tzinfo=UTC)
    assert first.attrs["pid"] == "25746" and first.attrs["addr"].startswith("req-38101a0b")


def test_known_line_formats():
    assert set(LINE_FORMATS) == {"generic", "bgl", "openstack"}


# --- through the MCP tools, against a real SereneDB ---

db = pytest.mark.db


@db
async def test_stacktrace_joined_and_untimestamped_reported(mcp, tmp_path):  # Review Focus 3
    p = copy_fixture(tmp_path, "generic_with_stacktrace.log")
    out = await call(mcp, "setup_log_table", name="app", source=str(p))
    assert "copied" in out and "UTC" in out
    assert "1 entry has no timestamp" in await call(mcp, "describe_logs", log_table="app")


@db
async def test_copied_table_is_ordered_and_keeps_positions(mcp, tmp_path, database):
    await call(mcp, "setup_log_table", name="app", source=str(copy_fixture(tmp_path, "generic_with_stacktrace.log")))
    rows = database.read(
        "SELECT entry_id, line_start, line_end, ts, level, component, host, message, attrs, source_file "
        "FROM extractor.lt_app ORDER BY entry_id"
    ).rows
    assert [r[0] for r in rows] == [1, 2, 3, 4, 5, 6]
    assert rows[0][3] is None and rows[0][1:3] == (1, 1)  # NULL timestamps first
    err = [r for r in rows if r[4] == "ERROR"][0]
    assert (err[1], err[2]) == (4, 7) and "NullPointerException" in err[7] and err[5] == "payments" and err[6] is None
    assert err[9].endswith("generic_with_stacktrace.log")
    stamps = [r[3] for r in rows[1:]]
    assert stamps == sorted(stamps)
    lt = database.read("SELECT mode, role_order, role_timestamp FROM extractor.log_tables WHERE name = 'app'").rows[0]
    assert lt == ("copied", '"entry_id"', '"ts"')


@db
async def test_out_of_order_file_is_sorted_by_timestamp(mcp, tmp_path, database):
    p = tmp_path / "shuffled.log"
    p.write_text(
        "2026-03-01 10:00:05 INFO [a] late\n2026-03-01 10:00:01 ERROR [a] early\n  at trace line\n2026-03-01 10:00:03 INFO [a] middle\n"
    )
    await call(mcp, "setup_log_table", name="shuf", source=str(p))
    rows = database.read("SELECT entry_id, level, line_start, line_end FROM extractor.lt_shuf ORDER BY entry_id").rows
    assert rows == [(1, "ERROR", 2, 3), (2, "INFO", 4, 4), (3, "INFO", 1, 1)]


@db
async def test_bgl_and_openstack_parse(mcp, tmp_path):
    for name in ("bgl", "openstack"):
        assert "copied" in await call(
            mcp, "setup_log_table", name=name, source=str(copy_fixture(tmp_path, f"{name}_sample.log"))
        )
    assert "KERNEL" in await call(mcp, "describe_logs", log_table="bgl")
    assert "nova" in await call(mcp, "describe_logs", log_table="openstack")
    assert "host" in (await call(mcp, "describe_logs", log_table="bgl"))


@db
async def test_given_timezone_is_used_and_stated(mcp, tmp_path, database):
    p = tmp_path / "paris.log"
    p.write_text("2026-03-01 10:00:00 INFO [a] hello\n")
    out = await call(mcp, "setup_log_table", name="paris", source=str(p), timezone="Europe/Paris")
    assert "Europe/Paris" in out
    assert database.read("SELECT ts FROM extractor.lt_paris").scalar() == datetime(2026, 3, 1, 9, 0, tzinfo=UTC)


@db
async def test_inspect_raw_text_changes_nothing(mcp, tmp_path):
    p = copy_fixture(tmp_path, "generic_with_stacktrace.log")
    out = await call(mcp, "inspect_source", source=str(p))
    assert "line format: generic" in out and "copied" in out and "outside the mounted folder" in out
    assert "no log tables yet" in await call(mcp, "describe_logs")


@db
async def test_remote_raw_text_is_still_rejected(mcp):
    out = await call(mcp, "setup_log_table", name="r", source="https://example.com/app.log")
    assert "must be local" in out


@db
async def test_structured_outside_mount_copied(mcp, tmp_path):
    p = tmp_path / "local.jsonl"
    p.write_text(
        "\n".join(
            json.dumps({"ts": f"2026-03-01T00:00:{i:02d}", "level": "INFO", "msg": f"hello {i}"}) for i in range(50)
        )
    )
    out = await call(mcp, "setup_log_table", name="local", source=str(p))
    assert "copied" in out and "outside the mounted folder" in out
    desc = await call(mcp, "describe_logs", log_table="local")
    assert "entries: 50" in desc and "copied" in desc and "INFO (50)" in desc


@db
async def test_parquet_outside_mount_copied(mcp, tmp_path, database):
    p = tmp_path / "local.parquet"
    pq.write_table(
        pa.table(
            {
                "ts": pa.array([datetime(2026, 3, 1, 0, 0, i) for i in range(20)], pa.timestamp("us")),
                "level": ["WARN"] * 20,
                "message": [f"disk {i}% full" for i in range(20)],
                "extra": [{"k": i} for i in range(20)],
            }
        ),
        p,
    )
    out = await call(mcp, "setup_log_table", name="pq", source=str(p))
    assert "copied" in out and "outside the mounted folder" in out and "UTC" in out
    assert database.read("SELECT count(*) FROM extractor.lt_pq").scalar() == 20
    assert database.read("SELECT message FROM extractor.lt_pq WHERE entry_id = 11").scalar() == "disk 10% full"
    assert "WARN (20)" in await call(mcp, "describe_logs", log_table="pq")


@db
async def test_large_file_warning(mcp, tmp_path):
    p = tmp_path / "big.log"
    p.write_text("2026-03-01 00:00:00 INFO [x] start\n")
    os.truncate(p, 1_100_000_000)  # sparse, > 1 GB
    out = await call(mcp, "inspect_source", source=str(p))
    assert "full copy" in out and "mounting the folder would avoid it" in out


@db
async def test_small_file_has_no_size_warning(mcp, tmp_path):
    out = await call(mcp, "inspect_source", source=str(copy_fixture(tmp_path, "bgl_sample.log")))
    assert "full copy" not in out


# --- a file under the mounted folder is read by SereneDB, not by this process ---


@pytest_asyncio.fixture
async def mcp_mounted(db_url):
    """Server whose logs folder /mnt/hostlogs (absent on this machine) is /tmp inside SereneDB."""
    _reset_schema(db_url)
    settings = _settings(db_url, logs_host_dir="/mnt/hostlogs", logs_container_dir="/tmp")
    async for c in _client(lambda: AppContext.from_settings(settings)):
        yield c


@db
async def test_mounted_file_is_read_by_serenedb(mcp_mounted, db_url, database):
    lines = [
        "2026-03-01 10:00:00 INFO [a] start",
        "2026-03-01 10:00:01 ERROR [a] boom",
        "  at frame one",
        "  at frame two",
        "2026-03-01 10:00:02 INFO [a] done",
    ]
    values = ", ".join(f"({i}, '{line}')" for i, line in enumerate(lines))
    with psycopg.connect(db_url, autocommit=True) as conn:
        conn.execute(
            f"COPY (SELECT line FROM (VALUES {values}) AS t(i, line) ORDER BY i) TO '/tmp/mounted_raw.log' "
            "(FORMAT CSV, HEADER false, QUOTE '')"
        )
    out = await call(mcp_mounted, "setup_log_table", name="mnt", source="/mnt/hostlogs/mounted_raw.log")
    assert "copied" in out and "read by SereneDB" in out and "outside the mounted folder" not in out
    rows = database.read("SELECT entry_id, level, line_start, line_end FROM extractor.lt_mnt ORDER BY entry_id").rows
    assert rows == [(1, "INFO", 1, 1), (2, "ERROR", 2, 4), (3, "INFO", 5, 5)]


@db
async def test_unreadable_raw_file_is_one_plain_line(mcp, tmp_path):
    out = await call(mcp, "setup_log_table", name="gone", source=str(tmp_path / "missing.log"))
    assert "Traceback" not in out and "missing.log" in out


@db
async def test_percent_and_quotes_in_log_text_survive(mcp, tmp_path, database):
    p = tmp_path / "odd.log"
    p.write_text("2026-03-01 10:00:00 ERROR [a] disk 100% full on 'sda1' (\"quoted\") %s %(x)s\n")
    await call(mcp, "setup_log_table", name="odd", source=str(p))
    msg = database.read("SELECT message FROM extractor.lt_odd").scalar()
    assert msg == "disk 100% full on 'sda1' (\"quoted\") %s %(x)s"
    assert "100% full" in await call(mcp, "describe_logs", log_table="odd", find_values={"role_or_column": "message", "like": "100%"})


@db
async def test_rerun_keeps_zone_and_refuses_to_change_it_on_a_copy(mcp, tmp_path):
    p = copy_fixture(tmp_path, "generic_with_stacktrace.log")
    await call(mcp, "setup_log_table", name="app", source=str(p))
    again = await call(mcp, "setup_log_table", name="app", source=str(p))
    assert "nothing changed" in again
    out = await call(mcp, "setup_log_table", name="app", source=str(p), timezone="Asia/Tokyo")
    assert "can't be changed" in out
