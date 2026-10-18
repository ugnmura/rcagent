"""What every telemetry tool shares: table prefixes, the pivot window, time expressions, coverage."""

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from serenedb_extractor.catalog.models import LogTable
from serenedb_extractor.context import AppContext
from serenedb_extractor.db import quote_ident
from serenedb_extractor.errors import UserFacingError
from serenedb_extractor.setup.paths import sql_literal
from serenedb_extractor.setup.roles import is_temporal
from serenedb_extractor.telemetry.registry import MetricTable, TelemetryStore, TraceTable
from serenedb_extractor.timezones import get_zone

TIME_UNITS = ("s", "ms", "us", "ns")
_US_PER = {"s": 1_000_000, "ms": 1_000, "us": 1, "ns": None}
_PREFIX = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*_$")
SOURCES = ("logs", "metrics", "traces")


# ------------------------------------------------------------------ prefixes


def check_prefix(prefix: str) -> str:
    p = (prefix or "").strip()
    if not _PREFIX.match(p):
        raise UserFacingError(
            f"'{prefix}' is not a table prefix. A prefix is the shared start of a system's table names and ends "
            "with '_' (for example 'shop_' for shop_logs, shop_metrics, shop_traces)."
        )
    return p


@dataclass
class TableSet:
    prefix: str
    logs: list[LogTable] = field(default_factory=list)
    metrics: list[MetricTable] = field(default_factory=list)
    traces: list[TraceTable] = field(default_factory=list)

    @property
    def names(self) -> list[str]:
        return [t.name for t in self.logs] + [t.name for t in self.metrics] + [t.name for t in self.traces]


def tables_with_prefix(ctx: AppContext, prefix: str) -> TableSet:
    """All log, metric and trace tables whose name starts with `prefix` (plain string match, no wildcards)."""
    p = check_prefix(prefix)
    store = TelemetryStore(ctx.db)
    logs = ctx.store.list_log_tables()
    metrics = store.list_metric_tables()
    traces = store.list_trace_tables()
    found = TableSet(
        p,
        [t for t in logs if t.name.startswith(p)],
        [t for t in metrics if t.name.startswith(p)],
        [t for t in traces if t.name.startswith(p)],
    )
    if not found.names:
        names = sorted([t.name for t in logs] + [t.name for t in metrics] + [t.name for t in traces])
        hint = f" Table names: {', '.join(names[:30])}." if names else " There are no tables yet."
        raise UserFacingError(f"No log, metric or trace table name starts with '{p}'.{hint}")
    return found


# ------------------------------------------------------------------ the pivot window


@dataclass(frozen=True)
class Window:
    """Epoch microseconds: [start, pivot) is the baseline, [pivot, end) the incident."""

    start_us: int
    pivot_us: int
    end_us: int

    def describe(self) -> str:
        return (
            f"baseline {fmt_us(self.start_us)} to {fmt_us(self.pivot_us)}, "
            f"incident {fmt_us(self.pivot_us)} to {fmt_us(self.end_us)} (UTC)"
        )


def parse_time(text: str, timezone: str | None = None) -> datetime:
    """An ISO time; one without an offset is read in `timezone` (default UTC)."""
    try:
        dt = datetime.fromisoformat(text.strip().replace("Z", "+00:00"))
    except ValueError:
        raise UserFacingError(f"'{text}' is not an ISO time such as 2024-01-15T17:30:00Z.") from None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=get_zone(timezone or "UTC"))
    return dt.astimezone(UTC)


def to_us(dt: datetime) -> int:
    return int((dt - datetime(1970, 1, 1, tzinfo=UTC)) / timedelta(microseconds=1))


def fmt_us(us: int | float | None) -> str:
    if us is None:
        return "unknown"
    dt = datetime(1970, 1, 1, tzinfo=UTC) + timedelta(microseconds=int(us))
    return dt.strftime("%Y-%m-%d %H:%M:%S") + (f".{dt.microsecond // 1000:03d}" if dt.microsecond else "")


def parse_window(pivot: str, before_minutes: float = 10, after_minutes: float = 10, timezone: str | None = None) -> Window:
    for label, m in (("before_minutes", before_minutes), ("after_minutes", after_minutes)):
        if not 0 < m <= 24 * 60:
            raise UserFacingError(f"{label} must be between 0 and 1440 minutes; got {m}.")
    p = to_us(parse_time(pivot, timezone))
    return Window(p - int(before_minutes * 60_000_000), p, p + int(after_minutes * 60_000_000))


# ------------------------------------------------------------------ time as epoch microseconds


def guess_epoch_unit(value: float) -> str:
    """The unit of an integer epoch from its magnitude (any date from 1973 to 5138)."""
    v = abs(value)
    if v < 1e11:
        return "s"
    if v < 1e14:
        return "ms"
    if v < 1e17:
        return "us"
    return "ns"


def epoch_us_sql(expr: str, type_name: str, unit: str | None, timezone: str = "UTC") -> str:
    """A BIGINT expression: microseconds since the epoch, for a temporal or integer epoch column."""
    t = type_name.upper()
    if is_temporal(t):
        if t == "DATE":
            expr = f"CAST({expr} AS TIMESTAMP)"
        if "WITH TIME ZONE" in t or t.startswith("TIMESTAMPTZ") or timezone.upper() == "UTC":
            return f"epoch_us({expr})"
        return f"epoch_us({expr} AT TIME ZONE {sql_literal(timezone)})"
    if unit not in TIME_UNITS:
        raise UserFacingError(f"The time column is a number; say its unit ({', '.join(TIME_UNITS)}).")
    per = _US_PER[unit]
    if per is None:
        return f"(CAST({expr} AS BIGINT) // 1000)"
    if per == 1:
        return f"CAST({expr} AS BIGINT)"
    return f"CAST(round({expr} * {per}) AS BIGINT)"


def duration_us_sql(expr: str, unit: str) -> str:
    """A DOUBLE expression: a duration in microseconds."""
    if unit not in TIME_UNITS:
        raise UserFacingError(f"Durations need a unit ({', '.join(TIME_UNITS)}).")
    factor = {"s": "* 1000000.0", "ms": "* 1000.0", "us": "* 1.0", "ns": "/ 1000.0"}[unit]
    return f"(CAST({expr} AS DOUBLE) {factor})"


# ------------------------------------------------------------------ coverage


def services_by_source(ctx: AppContext, tables: TableSet) -> dict[str, set[str]]:
    """The services seen in each kind of table of a prefix (log tables need a service role to count)."""
    out: dict[str, set[str]] = {s: set() for s in SOURCES}
    for lt in tables.logs:
        expr = lt.roles.service
        if expr:
            rows = ctx.db.read(f"SELECT DISTINCT CAST({expr} AS VARCHAR) FROM {lt.relation} WHERE {expr} IS NOT NULL", {})
            out["logs"].update(str(r[0]) for r in rows.rows)
    for mt in tables.metrics:
        if mt.service:
            col = quote_ident(mt.service)
            rows = ctx.db.read(f"SELECT DISTINCT CAST({col} AS VARCHAR) FROM {mt.relation} WHERE {col} IS NOT NULL", {})
            out["metrics"].update(str(r[0]) for r in rows.rows)
    for tt in tables.traces:
        col = quote_ident(tt.service)
        rows = ctx.db.read(f"SELECT DISTINCT CAST({col} AS VARCHAR) FROM {tt.relation} WHERE {col} IS NOT NULL", {})
        out["traces"].update(str(r[0]) for r in rows.rows)
    return out


def coverage_lines(by_source: dict[str, set[str]], indent: str = "  ") -> list[str]:
    """One line per service saying which of logs, metrics and traces it has, so that missing data is
    never read as "no change". `by_source` maps logs/metrics/traces to the services seen there."""
    services = sorted(set().union(*by_source.values())) if by_source else []
    out = ["coverage (which signals exist per service; 'no' means no data, not no change):"]
    for s in services:
        parts = [f"{src} {'yes' if s in by_source.get(src, set()) else 'no'}" for src in SOURCES]
        out.append(f"{indent}{s}: " + ", ".join(parts))
    if not services:
        out.append(f"{indent}no services found")
    return out


# ------------------------------------------------------------------ how much of the window the data covers

COVER_SHARE = 0.9
"""A side of the window counts as covered when the data spans at least this share of it; otherwise
before/after comparisons on counts are not comparable (a nearly empty side is missing data, not quiet)."""


@dataclass(frozen=True)
class Extent:
    """First and last timestamp (epoch µs) of a table's data; None when the table is empty."""

    first_us: int | None
    last_us: int | None

    def covered_us(self, lo: int, hi: int) -> int:
        if self.first_us is None or self.last_us is None:
            return 0
        return max(0, min(hi, self.last_us + 1) - max(lo, self.first_us))

    def covers(self, lo: int, hi: int) -> bool:
        """True when the data spans the whole interval [lo, hi)."""
        return self.first_us is not None and self.last_us is not None and self.first_us <= lo and self.last_us >= hi - 1


def extent(ctx: AppContext, relation: str, epoch_us_expr: str) -> Extent:
    row = ctx.db.read(
        f"SELECT min({epoch_us_expr}) AS a, max({epoch_us_expr}) AS b FROM {relation}", {}, what=f"reading the time range of {relation}"
    ).rows[0]
    return Extent(None if row[0] is None else int(row[0]), None if row[1] is None else int(row[1]))


def window_note(name: str, ext: Extent, w: Window) -> str | None:
    """A plain sentence when the data covers less than COVER_SHARE of either side of the window, else None."""
    before, after = w.pivot_us - w.start_us, w.end_us - w.pivot_us
    cb, ca = ext.covered_us(w.start_us, w.pivot_us), ext.covered_us(w.pivot_us, w.end_us)
    if cb >= COVER_SHARE * before and ca >= COVER_SHARE * after:
        return None
    span = f"its data runs from {fmt_us(ext.first_us)} to {fmt_us(ext.last_us)} UTC" if ext.first_us is not None else "it has no data"
    return (
        f"{name}: the data covers only {cb / 1e6:,.0f} s of the {before / 1e6:,.0f} s before the pivot and "
        f"{ca / 1e6:,.0f} s of the {after / 1e6:,.0f} s after it ({span}), so before/after counts are not comparable "
        "(missing data, not a change)."
    )


def minute_covered(ext: Extent, start_us: int) -> bool:
    """Whether the whole minute starting at start_us lies inside the data; minutes outside are unknown, not zero."""
    return ext.covers(start_us, start_us + 60_000_000)
