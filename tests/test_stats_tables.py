"""I3 (final review): pricing a table or copied source must not itself scan it. The row count comes
from the catalog (log_tables.row_count); a time range gives an upper bound, labelled as one; the
scope's metadata is collected once per tool call."""

from datetime import UTC, datetime

from rcagent.catalog.models import FieldRoles, LogTable
from rcagent.config import Settings
from rcagent.db import Rows
from rcagent.query import stats
from rcagent.query.filters import TimeRange


class RecordingDb:
    def __init__(self) -> None:
        self.settings = Settings("postgresql://r", "postgresql://w", False, None, None)
        self.sql: list[str] = []

    def read(self, sql: str, params=None, **_kw) -> Rows:
        self.sql.append(sql)
        if sql.startswith("DESCRIBE"):
            return Rows(["column_name", "column_type"], [("ts", "TIMESTAMP WITH TIME ZONE"), ("message", "VARCHAR")])
        if "LIMIT 0" in sql:
            return Rows(["ts", "message"], [])
        if "avg(octet_length" in sql:
            return Rows(["a", "b"], [(8.0, 40.0)])
        raise AssertionError(f"unexpected query: {sql}")


def _copied(rows: int | None = 1_000_000) -> LogTable:
    now = datetime.now(UTC)
    roles = FieldRoles(message="message", timestamp="ts")
    return LogTable("c", "/x.log", "raw", "copied", "extractor.c_c", roles, None, None, rows, "UTC", now, now)


def test_table_stats_use_the_catalog_row_count_and_never_count():
    db = RecordingDb()
    s = stats.collect(db, _copied(), TimeRange())  # type: ignore[arg-type]
    assert s.total_rows == s.rows_in_range == 1_000_000 and s.rows_exact
    assert not any("count(*)" in q for q in db.sql)
    assert s.bytes_by_column == {"ts": 8_000_000, "message": 40_000_000}


def test_a_time_range_on_a_table_is_an_upper_bound_not_a_count():
    db = RecordingDb()
    tr = TimeRange(datetime(2026, 3, 1, tzinfo=UTC), datetime(2026, 3, 2, tzinfo=UTC))
    s = stats.collect(db, _copied(), tr)  # type: ignore[arg-type]
    assert s.rows_in_range == 1_000_000 and not s.rows_exact
    assert not any("count(*)" in q for q in db.sql)


def test_scope_stats_are_collected_once_per_tool_call():
    db = RecordingDb()
    lt = _copied()
    with stats.per_call():
        a = stats.collect(db, lt, TimeRange())  # type: ignore[arg-type]
        n = len(db.sql)
        b = stats.collect(db, lt, TimeRange())  # type: ignore[arg-type]
        assert a is b and len(db.sql) == n
    stats.collect(db, lt, TimeRange())  # type: ignore[arg-type]
    assert len(db.sql) > n  # outside a tool call nothing is remembered


class LiveTableDb(RecordingDb):
    """An in-place table source that has grown from 1,000 entries (at setup) to 5,000."""

    def read(self, sql: str, params=None, **_kw) -> Rows:
        if "pg_class" in sql:
            self.sql.append(sql)
            return Rows(["reltuples"], [(5000.0,)])
        return super().read(sql, params, **_kw)


def _table_source(rows: int | None = 1_000) -> LogTable:
    now = datetime.now(UTC)
    roles = FieldRoles(message="message", timestamp="ts")
    return LogTable("t", "logs", "table", "in_place", "extractor.lt_t", roles, None, None, rows, "UTC", now, now)


def test_an_in_place_table_is_priced_at_its_live_row_count_not_the_setup_count():
    # A table source can grow after setup: its row count comes from the planner statistics
    # (pg_class.reltuples, kept current on insert), never count(*), and is read once per tool call.
    db = LiveTableDb()
    with stats.per_call():
        s = stats.collect(db, _table_source(), TimeRange())  # type: ignore[arg-type]
        stats.collect(db, _table_source(), TimeRange(datetime(2026, 3, 1, tzinfo=UTC), None))  # type: ignore[arg-type]
    assert s.total_rows == s.rows_in_range == 5000
    assert s.bytes_by_column == {"ts": 40_000, "message": 200_000}
    assert not any("count(*)" in q for q in db.sql)
    assert sum("pg_class" in q for q in db.sql) == 1


def test_a_copied_table_keeps_the_catalog_count():
    db = LiveTableDb()
    s = stats.collect(db, _copied(), TimeRange())  # type: ignore[arg-type]
    assert s.total_rows == 1_000_000 and not any("pg_class" in q for q in db.sql)
