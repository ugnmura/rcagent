"""The metric_tables and trace_tables registries (DDL in catalog/schema.py)."""

from dataclasses import asdict, dataclass, fields
from datetime import datetime
from typing import Any

from rcagent.db import Database
from rcagent.errors import UserFacingError


@dataclass(frozen=True)
class MetricTable:
    """Roles are plain column names (unquoted); None means absent."""

    name: str
    source: str
    source_format: str
    relation: str
    timestamp: str
    timestamp_unit: str | None
    service: str | None
    metric: str
    value: str
    row_count: int | None
    timezone: str
    created_at: datetime


@dataclass(frozen=True)
class TraceTable:
    """Roles are plain column names of the copied table `relation` (unquoted); None means absent."""

    name: str
    source: str
    source_format: str
    relation: str
    trace_id: str
    span_id: str
    parent_span_id: str | None
    service: str
    operation: str
    start: str
    start_unit: str | None
    duration: str
    duration_unit: str
    status: str | None
    row_count: int | None
    orphan_spans: int | None
    setup_seconds: float | None
    timezone: str
    created_at: datetime


_PLAIN = {"name", "source", "source_format", "relation", "row_count", "timezone", "created_at", "orphan_spans", "setup_seconds"}


def _column(field: str) -> str:
    return field if field in _PLAIN else f"role_{field}"


class UnknownTelemetryTable(UserFacingError):
    def __init__(self, kind: str, name: str, known: list[str]) -> None:
        hint = f" Known {kind} tables: {', '.join(known)}." if known else f" There are no {kind} tables yet."
        super().__init__(f"There is no {kind} table named '{name}'.{hint}")


class TelemetryStore:
    def __init__(self, db: Database) -> None:
        self.db = db

    def _list(self, cls: Any, table: str) -> list[Any]:
        cols = ", ".join(f"{_column(f.name)} AS {f.name}" for f in fields(cls))
        rows = self.db.read(f"SELECT {cols} FROM extractor.{table} ORDER BY name", {})
        return [cls(**r) for r in rows.dicts()]

    def _create(self, obj: Any, table: str) -> None:
        values = asdict(obj)
        cols = ", ".join(_column(k) for k in values)
        marks = ", ".join(f"%({k})s" for k in values)
        self.db.write(f"INSERT INTO extractor.{table} ({cols}) VALUES ({marks})", values)

    def list_metric_tables(self) -> list[MetricTable]:
        return self._list(MetricTable, "metric_tables")

    def list_trace_tables(self) -> list[TraceTable]:
        return self._list(TraceTable, "trace_tables")

    def get_metric_table(self, name: str) -> MetricTable:
        found = [t for t in self.list_metric_tables() if t.name == name]
        if not found:
            raise UnknownTelemetryTable("metric", name, [t.name for t in self.list_metric_tables()])
        return found[0]

    def get_trace_table(self, name: str) -> TraceTable:
        found = [t for t in self.list_trace_tables() if t.name == name]
        if not found:
            raise UnknownTelemetryTable("trace", name, [t.name for t in self.list_trace_tables()])
        return found[0]

    def create_metric_table(self, mt: MetricTable) -> None:
        self._create(mt, "metric_tables")

    def create_trace_table(self, tt: TraceTable) -> None:
        self._create(tt, "trace_tables")

    def names_in_use(self) -> set[str]:
        """Every table name taken by a log, metric or trace table: one namespace, so prefixes stay unambiguous."""
        rows = self.db.read(
            "SELECT name FROM extractor.log_tables UNION ALL SELECT name FROM extractor.metric_tables "
            "UNION ALL SELECT name FROM extractor.trace_tables",
            {},
        )
        return {r[0] for r in rows.rows}
