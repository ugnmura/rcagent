"""A log table's own time zone: which zone setup reads zoneless times in, and how times are shown (no database)."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg

from serenedb_extractor import db as dbmod
from serenedb_extractor import format as fmt
from serenedb_extractor.config import Settings
from serenedb_extractor.db import Database
from serenedb_extractor.instructions import ANSWER_RULES
from serenedb_extractor.query.filters import TimeRange, shown_zone
from serenedb_extractor.setup.rawlog import LINE_FORMATS, parse_entries
from serenedb_extractor.tools import setup_tools
from serenedb_extractor.tools import sql as sql_tool
from tests.test_stats_tables import _copied

FIXTURES = Path(__file__).resolve().parent / "fixtures"
# A BGL line from the winter (Pacific Standard Time): its epoch field is 8 hours after its local time.
BGL_WINTER = (
    "- 1135791839 2005.12.28 R31-M0-N4-I:J18-U11 2005-12-28-09.43.59.595659 R31-M0-N4-I:J18-U11 RAS APP FATAL "
    "ciod: Error loading /g/g0/x/inferno: invalid or missing program image, No such file or directory"
)


# --- setup: the zone zoneless times are read in ---


def test_bgl_times_are_us_pacific_local_time_as_their_epoch_field_shows():
    zone = LINE_FORMATS["bgl"].zone
    assert zone == "America/Los_Angeles"
    lines = (FIXTURES / "bgl_sample.log").read_text().splitlines() + [BGL_WINTER]
    entries = list(parse_entries(lines, "bgl", zone))
    assert len(entries) == len(lines)
    for e in entries:  # <Timestamp> is the epoch (whole seconds, UTC); <Time> is the local time with microseconds
        assert e.ts is not None and abs(e.ts.timestamp() - int(e.attrs["timestamp"])) < 1, e
    assert entries[0].ts == datetime(2005, 6, 3, 22, 42, 50, 675872, tzinfo=UTC)  # logged 15:42:50 PDT
    assert entries[-1].ts == datetime(2005, 12, 28, 17, 43, 59, 595659, tzinfo=UTC)  # logged 09:43:59 PST


def test_formats_without_a_zone_of_their_own():
    assert LINE_FORMATS["openstack"].zone is None and LINE_FORMATS["generic"].zone is None


def test_setup_reads_a_format_in_its_own_zone_unless_told_otherwise():
    zone, why = setup_tools.setup_zone(None, "bgl")
    assert zone == "America/Los_Angeles" and "bgl" in why and "US Pacific" in why
    assert setup_tools.setup_zone("UTC", "bgl") == ("UTC", "given by you")
    assert setup_tools.setup_zone(None, "openstack") == ("UTC", "the default")
    assert setup_tools.setup_zone(None, None) == ("UTC", "the default")
    assert setup_tools.setup_zone("Europe/Paris", None) == ("Europe/Paris", "given by you")


# --- how times are shown ---


def test_a_time_outside_utc_carries_its_utc_offset():
    summer, winter = datetime(2005, 6, 3, 23, 17, 40, tzinfo=UTC), datetime(2005, 12, 28, 17, 43, 59, tzinfo=UTC)
    pacific = TimeRange(tz="America/Los_Angeles")
    assert pacific.fmt(summer) == "2005-06-03 16:17:40-07:00"
    assert pacific.fmt(winter) == "2005-12-28 09:43:59-08:00"
    assert TimeRange(tz="UTC").fmt(summer) == "2005-06-03 23:17:40"  # UTC stays as it was
    bounded = TimeRange(summer, winter, "America/Los_Angeles")
    assert bounded.describe() == "2005-06-03 16:17:40-07:00 to 2005-12-28 09:43:59-08:00 America/Los_Angeles"


def test_how_measured_says_a_zone_is_not_utc():
    assert fmt.how_measured("exact").endswith("times in UTC.")
    assert "times in America/Los_Angeles (not UTC)" in fmt.how_measured("exact", tz="America/Los_Angeles")


def test_shown_zone_is_the_tables_own_unless_one_is_given():
    lt = _copied(10)
    pacific = lt.__class__(**{**vars(lt), "timezone": "America/Los_Angeles"})
    assert shown_zone(pacific, None) == "America/Los_Angeles"
    assert shown_zone(pacific, "UTC") == "UTC"
    assert shown_zone(lt, None) == "UTC"


def test_answer_rules_name_the_tables_zone_and_ask_for_utc_alongside():
    rules = ANSWER_RULES.lower()
    assert "own time zone" in rules and "utc offset" in rules and "give utc too" in rules
    assert "utc unless the user said otherwise" not in rules


# --- run_sql reads times in the zone of the log tables it queries ---


def test_run_sql_zone_is_the_shared_zone_of_the_tables_it_reads():
    utc = _copied(10)
    pacific = utc.__class__(**{**vars(utc), "name": "bgl", "timezone": "America/Los_Angeles"})
    assert sql_tool.query_zone([pacific]) == ("America/Los_Angeles", "the time zone of bgl")
    assert sql_tool.query_zone([utc]) == ("UTC", "the time zone of c")
    zone, why = sql_tool.query_zone([pacific, utc])
    assert zone == "UTC" and "differ" in why
    assert sql_tool.query_zone([]) == (None, "")


class _FakeCursor:
    description = None

    def fetchall(self) -> list[Any]:
        return []


class _FakeConn:
    closed = False
    broken = False

    def __init__(self, seen: list[str]) -> None:
        self.seen = seen

        class _Adapters:
            def register_loader(self, *_: Any) -> None:
                pass

        self.adapters = _Adapters()

    def execute(self, sql: str, params: Any = None) -> _FakeCursor:
        self.seen.append(sql)
        return _FakeCursor()


def test_a_statement_read_in_a_zone_sets_it_and_resets_it_after(monkeypatch):
    seen: list[str] = []
    monkeypatch.setattr(psycopg, "connect", lambda url, **kw: _FakeConn(seen))
    d = Database(Settings.from_env({"SERENEDB_READER_URL": "postgresql://r@h/x"}))
    d.read("SELECT 1", zone="America/Los_Angeles")
    d.read("SELECT 2")
    assert seen == ["SET TimeZone = 'America/Los_Angeles'", "SELECT 1", "RESET TimeZone", "SELECT 2"]


def test_the_zone_is_reset_even_when_the_statement_fails(monkeypatch):
    seen: list[str] = []

    class Failing(_FakeConn):
        def execute(self, sql: str, params: Any = None) -> _FakeCursor:
            if sql.startswith("SELECT"):
                self.seen.append(sql)
                raise psycopg.errors.InsufficientPrivilege("permission denied")
            return super().execute(sql, params)

    monkeypatch.setattr(psycopg, "connect", lambda url, **kw: Failing(seen))
    d = Database(Settings.from_env({"SERENEDB_READER_URL": "postgresql://r@h/x"}))
    try:
        d.read("SELECT 1", zone="America/Los_Angeles")
    except dbmod.PermissionRefused:
        pass
    assert seen == ["SET TimeZone = 'America/Los_Angeles'", "SELECT 1", "RESET TimeZone"]
