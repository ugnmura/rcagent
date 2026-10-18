"""setup_trace_table: copy one-row-per-span traces once into extractor.tt_<name>, with self time per span.

The copy has fixed, normalized columns, so the trace tools never re-derive units or status codes:
trace_id, span_id, parent_span_id, service, operation (VARCHAR), start_us (BIGINT, epoch µs),
duration_us (DOUBLE), status ('ok', 'error' or NULL = unknown) and self_time_us (DOUBLE): the
duration minus the union of the child spans' intervals clipped to the span, so overlapping
children are not counted twice and a span whose parent is missing (an orphan) is still measured.
"""

import time
from datetime import UTC, datetime
from typing import Any

from mcp.types import ToolAnnotations

from serenedb_extractor import format as fmt
from serenedb_extractor.context import AppContext
from serenedb_extractor.db import quote_ident, validate_name
from serenedb_extractor.errors import UserFacingError
from serenedb_extractor.setup import localfiles
from serenedb_extractor.setup.paths import resolve_source
from serenedb_extractor.setup.roles import HELPER_COLUMNS, is_temporal
from serenedb_extractor.setup.sniff import readable, sample_values, sniff
from serenedb_extractor.telemetry.common import TIME_UNITS, duration_us_sql, epoch_us_sql, fmt_us, guess_epoch_unit
from serenedb_extractor.telemetry.registry import TelemetryStore, TraceTable
from serenedb_extractor.telemetry.roles import TRACE_CANDIDATES, TRACE_REQUIRED, is_numeric, pick_roles, unknown_roles
from serenedb_extractor.timezones import get_zone

TOOL_ANNOTATIONS: dict[str, tuple[bool | None, bool | None]] = {"setup_trace_table": (False, False)}
ROLE_NAMES = (*TRACE_CANDIDATES, "start_unit", "duration_unit")
_SUFFIX_UNITS = (("_us", "us"), ("_ms", "ms"), ("_ns", "ns"), ("nano", "ns"), ("_s", "s"))


def duration_unit_from_name(column: str) -> str | None:
    low = column.lower()
    return next((unit for suffix, unit in _SUFFIX_UNITS if low.endswith(suffix)), None)


HTTP_GRPC = "CASE WHEN {n} IS NULL THEN NULL WHEN {n} = 0 OR ({n} >= 200 AND {n} < 400) THEN 'ok' ELSE 'error' END"
# OpenTelemetry's numeric StatusCode: 0 UNSET (no error recorded), 1 OK, 2 ERROR.
OTEL = "CASE WHEN {n} IS NULL THEN NULL WHEN {n} IN (0, 1) THEN 'ok' WHEN {n} = 2 THEN 'error' ELSE NULL END"


def numeric_status_scheme(values: set[float]) -> str:
    """'otel' when the numeric status codes seen are OpenTelemetry's (only 0, 1 and 2, with a 1 or 2 among them),
    else 'http' (0 = gRPC OK and 200-399 = HTTP ok, anything else an error)."""
    return "otel" if values and values <= {0.0, 1.0, 2.0} and values & {1.0, 2.0} else "http"


def status_sql(expr: str, type_name: str, scheme: str = "http") -> str:
    """'ok', 'error' or NULL (unknown). Numbers: by `scheme` (see numeric_status_scheme). Text: ok/error (also
    OpenTelemetry's STATUS_CODE_OK/ERROR) as is, a number in text as a number, unset or anything else unknown."""
    num = OTEL if scheme == "otel" else HTTP_GRPC
    if is_numeric(type_name):
        return num.format(n=f"CAST({expr} AS DOUBLE)")
    low = f"lower(trim(CAST({expr} AS VARCHAR)))"
    parsed = f"try_cast({low} AS DOUBLE)"
    return (
        f"CASE WHEN {low} IN ('ok', 'status_code_ok') THEN 'ok' "
        f"WHEN {low} IN ('error', 'status_code_error') THEN 'error' "
        f"WHEN {parsed} IS NOT NULL THEN {num.format(n=parsed)} ELSE NULL END"
    )


def self_time_select(spans_sql: str) -> str:
    """SELECT over normalized spans (`spans_sql`) adding self_time_us: duration minus the union of the
    child intervals clipped to the parent, found with gaps-and-islands over children sorted by start."""
    return f"""
WITH s AS ({spans_sql}),
c AS (
  SELECT p.trace_id, p.span_id,
    greatest(ch.start_us, p.start_us) AS cs,
    least(ch.start_us + ch.duration_us, p.start_us + p.duration_us) AS ce
  FROM s p JOIN s ch ON ch.trace_id = p.trace_id AND ch.parent_span_id = p.span_id
),
c2 AS (
  SELECT *, max(ce) OVER (PARTITION BY trace_id, span_id ORDER BY cs, ce
                          ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS prev_end
  FROM c WHERE ce > cs
),
c3 AS (
  SELECT *, sum(CASE WHEN prev_end IS NULL OR cs > prev_end THEN 1 ELSE 0 END)
              OVER (PARTITION BY trace_id, span_id ORDER BY cs, ce ROWS UNBOUNDED PRECEDING) AS island
  FROM c2
),
cov AS (
  SELECT trace_id, span_id, sum(e - b) AS covered FROM (
    SELECT trace_id, span_id, island, min(cs) AS b, max(ce) AS e FROM c3 GROUP BY trace_id, span_id, island
  ) i GROUP BY trace_id, span_id
)
SELECT s.trace_id, s.span_id, s.parent_span_id, s.service, s.operation, s.start_us, s.duration_us, s.status,
  greatest(s.duration_us - coalesce(cov.covered, 0), 0) AS self_time_us
FROM s LEFT JOIN cov ON cov.trace_id = s.trace_id AND cov.span_id = s.span_id"""


def setup_trace_table(
    ctx: AppContext, name: str, source: str, roles: dict[str, str | None] | None = None, timezone: str | None = None
) -> str:
    validate_name(name)
    zone = timezone or "UTC"
    get_zone(zone)
    unknown_roles(roles, ROLE_NAMES)
    store = TelemetryStore(ctx.db)
    if name in store.names_in_use():
        raise UserFacingError(f"The name '{name}' is already used by a log, metric or trace table; pick another.")
    rs = resolve_source(source, ctx.settings, None)
    if rs.kind == "raw_text":
        raise UserFacingError("Trace tables are read from Parquet, JSON or a table, not from raw text.")
    if localfiles.copy_needed(rs):
        raise UserFacingError(
            "This file is outside the mounted folder, so SereneDB cannot read it; trace tables are read by SereneDB "
            "itself. Put it under the mounted folder."
        )
    began = time.perf_counter()
    info = sniff(ctx.db, rs, source, for_setup=True)
    columns = [(c, t) for c, t in info.columns if c not in HELPER_COLUMNS]
    types = dict(columns)
    given = {k: v for k, v in (roles or {}).items() if k not in ("start_unit", "duration_unit")}
    picked, why = pick_roles(columns, TRACE_CANDIDATES, given)
    missing = [r for r in TRACE_REQUIRED if picked.get(r) is None]
    if missing:
        raise UserFacingError(
            f"No column found for {', '.join(missing)} (columns: {', '.join(types)}). Traces need one row per span. "
            "Name the columns with roles, e.g. roles={'trace_id': 'traceID', 'duration': 'dur'}."
        )
    start, dur = str(picked["start"]), str(picked["duration"])
    if not is_numeric(types[dur]):
        raise UserFacingError(f"The duration column '{dur}' is {types[dur]}, not a number.")

    start_unit = (roles or {}).get("start_unit")
    if is_temporal(types[start]):
        start_unit = None
    elif not is_numeric(types[start]):
        raise UserFacingError(f"The start column '{start}' is {types[start]}: it must be a timestamp or an epoch number.")
    elif start_unit is None:
        seen = [float(v) for v in sample_values(info).get(start, []) if v.replace(".", "", 1).lstrip("-").isdigit()]
        if not seen:
            raise UserFacingError(f"Can't tell the unit of the epoch column '{start}'; pass roles={{'start_unit': 'us'}}.")
        start_unit = guess_epoch_unit(max(seen))
        why["start_unit"] = f"guessed from the magnitude of {max(seen):.0f}"
    elif start_unit not in TIME_UNITS:
        raise UserFacingError(f"start_unit must be one of {', '.join(TIME_UNITS)}.")
    else:
        why["start_unit"] = "given by you"

    dur_unit = (roles or {}).get("duration_unit")
    if dur_unit is None:
        dur_unit = duration_unit_from_name(dur)
        if dur_unit is None:
            raise UserFacingError(
                f"Can't tell the unit of the duration column '{dur}' from its name; pass "
                f"roles={{'duration_unit': 'us'}} (one of {', '.join(TIME_UNITS)})."
            )
        why["duration_unit"] = f"from the column name '{dur}'"
    elif dur_unit not in TIME_UNITS:
        raise UserFacingError(f"duration_unit must be one of {', '.join(TIME_UNITS)}.")
    else:
        why["duration_unit"] = "given by you"

    def text(role: str) -> str:
        col = picked.get(role)
        return f"CAST({quote_ident(col)} AS VARCHAR)" if col else "CAST(NULL AS VARCHAR)"

    parent = picked.get("parent_span_id")
    status = picked.get("status")
    scheme = "http"
    if status:
        col = quote_ident(status)
        as_num = f"CAST({col} AS DOUBLE)" if is_numeric(types[status]) else f"try_cast(trim(CAST({col} AS VARCHAR)) AS DOUBLE)"
        with readable(source, rs.remote):
            codes = ctx.db.read(f"SELECT DISTINCT {as_num} AS v FROM {info.from_sql} WHERE {as_num} IS NOT NULL LIMIT 4", {})
        scheme = numeric_status_scheme({float(r[0]) for r in codes.rows})
    spans_sql = (
        f"SELECT {text('trace_id')} AS trace_id, {text('span_id')} AS span_id, "
        + (f"NULLIF(trim({text('parent_span_id')}), '')" if parent else "CAST(NULL AS VARCHAR)")
        + f" AS parent_span_id, {text('service')} AS service, {text('operation')} AS operation, "
        f"{epoch_us_sql(quote_ident(start), types[start], start_unit, zone)} AS start_us, "
        f"{duration_us_sql(quote_ident(dur), dur_unit)} AS duration_us, "
        + (status_sql(quote_ident(status), types[status], scheme) if status else "CAST(NULL AS VARCHAR)")
        + f" AS status FROM {info.from_sql}"
    )
    relation = f"extractor.tt_{name}"
    with readable(source, rs.remote):
        ctx.db.write(f"DROP TABLE IF EXISTS {relation}", {})
        ctx.db.write(
            f"CREATE TABLE {relation} AS {self_time_select(spans_sql)}", {}, what=f"copying the spans of {source}"
        )
    try:
        agg = ctx.db.read(
            f"SELECT count(*) AS n, min(start_us) AS t0, max(start_us + duration_us) AS t1, "
            f"count(DISTINCT service) AS services, count(DISTINCT operation) AS operations, "
            f"count(*) FILTER (WHERE status IS NULL) AS unknown_status, "
            f"count(*) FILTER (WHERE status = 'error') AS errors FROM {relation}",
            {},
        ).dicts()[0]
        orphans = int(
            ctx.db.read(
                f"SELECT count(*) FROM {relation} c WHERE c.parent_span_id IS NOT NULL AND NOT EXISTS "
                f"(SELECT 1 FROM {relation} p WHERE p.trace_id = c.trace_id AND p.span_id = c.parent_span_id)",
                {},
            ).scalar()
        )
        seconds = time.perf_counter() - began
        tt = TraceTable(
            name=name,
            source=source.strip(),
            source_format=rs.kind,
            relation=relation,
            trace_id="trace_id",
            span_id="span_id",
            parent_span_id="parent_span_id",
            service="service",
            operation="operation",
            start="start_us",
            start_unit="us",
            duration="duration_us",
            duration_unit="us",
            status="status",
            row_count=int(agg["n"]),
            orphan_spans=orphans,
            setup_seconds=round(seconds, 3),
            timezone=zone,
            created_at=datetime.now(UTC).replace(tzinfo=None),
        )
        store.create_trace_table(tt)
    except Exception:
        ctx.db.write(f"DROP TABLE IF EXISTS {relation}", {})
        raise
    services = _top_values(ctx, relation, "service", 40)
    operations = _top_values(ctx, relation, "service || ' ' || operation", 30)
    unknown = int(agg["unknown_status"])
    lines = [
        fmt.how_measured("trace table set up; the source's spans were copied once and self time computed per span"),
        f"Set up trace table '{name}': spans copied into table {relation} (columns trace_id, span_id, "
        "parent_span_id, service, operation, start_us, duration_us, status, self_time_us).",
        f"spans: {tt.row_count:,}",
        f"time range (UTC): {fmt_us(agg['t0'])} to {fmt_us(agg['t1'])}",
        f"services ({agg['services']}): " + ", ".join(services),
        f"operations ({agg['operations']} names): " + ", ".join(operations),
        f"orphan spans: {orphans:,} (their parent span is not in the table; they keep their own self time)",
        f"status: {int(agg['errors']):,} error, {unknown:,} unknown"
        + (" (no status role: errors are unknown)" if not status else "")
        + (" (numeric codes read as OpenTelemetry's: 0 unset and 1 ok, 2 error)" if scheme == "otel" else ""),
        f"setup took {fmt.duration(seconds)}",
        "roles (source columns):",
        *(f"  {r}: {picked.get(r) or 'absent'}" + (f"  ({why[r]})" if r in why else "") for r in TRACE_CANDIDATES),
        f"  start_unit: {start_unit or 'none (a timestamp column)'}"
        + (f"  ({why['start_unit']})" if "start_unit" in why else ""),
        f"  duration_unit: {dur_unit}  ({why['duration_unit']})",
        f"time zone for timestamps without one: {zone}",
    ]
    return "\n".join(lines)


def _top_values(ctx: AppContext, relation: str, expr: str, limit: int) -> list[str]:
    rows = ctx.db.read(
        f"SELECT DISTINCT CAST({expr} AS VARCHAR) AS v FROM {relation} WHERE {expr} IS NOT NULL "
        f"ORDER BY 1 LIMIT {int(limit) + 1}",
        {},
    ).rows
    vals = [str(r[0]) for r in rows]
    return vals[:limit] + (["…"] if len(vals) > limit else [])


_setup_trace_table = setup_trace_table  # the registered tool below shadows the name


def register(mcp: Any, runner: Any) -> None:
    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False))
    async def setup_trace_table(
        name: str, source: str, roles: dict[str, str | None] | None = None, timezone: str | None = None
    ) -> str:
        """Register traces so trace_changes and get_trace can use them. One row per span (Parquet, JSON or a table); the spans are copied once into extractor.tt_<name> with each span's self time (its duration minus the time its child spans cover).
        Use when: a system has traces next to its logs and metrics. Name its tables with one shared prefix (e.g. shop_logs, shop_metrics, shop_traces) so telemetry_overview and the change tools find them together.
        Inputs: name; source (path or table); roles to correct the guesses: trace_id, span_id, parent_span_id, service, operation, start, duration, status, start_unit (s|ms|us|ns, for an epoch-number start column), duration_unit (s|ms|us|ns; read from a _us/_ms/_ns/_s column-name suffix, otherwise required); timezone for timestamps without one (default UTC).
        Returns: roles and why, span count, time range, services, operations, orphan spans, status counts, setup time."""
        return await runner.run_tool(_setup_trace_table, name=name, source=source, roles=roles, timezone=timezone)
