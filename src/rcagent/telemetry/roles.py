"""Role detection for metric and trace tables: plain column names only (no expressions), matched by
name case-insensitively, OpenTelemetry names included. Stored unquoted; quote with quote_ident."""

from collections.abc import Mapping, Sequence

from rcagent.errors import UserFacingError
from rcagent.setup.roles import HELPER_COLUMNS, resolve_column

METRIC_CANDIDATES: dict[str, tuple[str, ...]] = {
    "timestamp": ("ts", "timestamp", "time", "time_unix_nano", "timeunixnano", "@timestamp"),
    "service": ("service", "servicename", "service_name", "service.name", "container_name", "app"),
    "metric": ("metric", "metric_name", "metricname", "name"),
    "value": ("value", "val", "metric_value"),
}
METRIC_REQUIRED = ("timestamp", "metric", "value")

TRACE_CANDIDATES: dict[str, tuple[str, ...]] = {
    "trace_id": ("trace_id", "traceid"),
    "span_id": ("span_id", "spanid"),
    "parent_span_id": ("parent_span_id", "parentspanid", "parent_id", "parentid"),
    "service": ("service", "servicename", "service_name", "service.name"),
    "operation": ("operation", "operationname", "operation_name", "span_name", "spanname", "name"),
    "start": ("start", "start_time", "starttime", "starttimeunixnano", "start_time_unix_nano", "timestamp", "ts"),
    "duration": ("duration_us", "duration", "duration_ms", "duration_ns", "durationnano"),
    "status": ("status", "status_code", "statuscode"),
}
TRACE_REQUIRED = ("trace_id", "span_id", "service", "operation", "start", "duration")


def is_numeric(type_name: str) -> bool:
    t = type_name.upper()
    return any(t.startswith(p) for p in ("TINYINT", "SMALLINT", "INT", "BIGINT", "HUGEINT", "UTINYINT", "USMALLINT",
                                          "UINT", "UBIGINT", "FLOAT", "DOUBLE", "REAL", "DECIMAL", "NUMERIC"))


def pick_roles(
    columns: Sequence[tuple[str, str]],
    candidates: Mapping[str, tuple[str, ...]],
    given: Mapping[str, str | None] | None = None,
) -> tuple[dict[str, str | None], dict[str, str]]:
    """(role -> column or None, role -> why). Given roles win; None or 'absent' clears one."""
    cols = {c: t for c, t in columns if c not in HELPER_COLUMNS}
    picked: dict[str, str | None] = {}
    why: dict[str, str] = {}
    taken: set[str] = set()
    for role, names in candidates.items():
        by_lower = {c.lower(): c for c in cols if c not in taken}
        col = next((by_lower[n] for n in names if n in by_lower), None)
        picked[role] = col
        if col is not None:
            taken.add(col)
            why[role] = f"column name '{col}'"
    for role, expr in (given or {}).items():
        if role not in candidates:
            continue
        if expr is None or not str(expr).strip() or str(expr).strip().lower() in ("absent", "none"):
            picked[role], why[role] = None, "removed by you"
            continue
        col = resolve_column(str(expr).strip(), cols)
        if col is None:
            raise UserFacingError(
                f"'{expr}' is not a column of this source (columns: {', '.join(list(cols)[:30])})."
            )
        picked[role], why[role] = col, "given by you"
    return picked, why


def unknown_roles(given: Mapping[str, object] | None, allowed: Sequence[str]) -> None:
    bad = [r for r in (given or {}) if r not in allowed]
    if bad:
        raise UserFacingError(f"Unknown role(s) {', '.join(bad)}. Roles here are: {', '.join(allowed)}.")
