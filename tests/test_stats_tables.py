"""I3 (final review): pricing a table or copied source must not itself scan it. The row count comes
from the catalog (log_tables.row_count); a time range gives an upper bound, labelled as one; the
scope's metadata is collected once per tool call."""

from datetime import UTC, datetime

from serenedb_extractor.catalog.models import FieldRoles, LogTable
from serenedb_extractor.config import Settings
from serenedb_extractor.db import Rows
from serenedb_extractor.query import stats
from serenedb_extractor.query.filters import TimeRange


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
