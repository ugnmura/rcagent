"""telemetry_overview: the first look at a system's tables around a pivot, per service and never ranked.

Per service (sorted by name): which of logs, metrics and traces exist, its metric names, and its log
entries and spans before and after the pivot with the change in percent. Also the prefix's tables and
which kinds are missing entirely.
"""

from typing import Any

from mcp.types import ToolAnnotations

from serenedb_extractor import format as fmt
from serenedb_extractor.context import AppContext
from serenedb_extractor.db import quote_ident
from serenedb_extractor.query.filters import role_sql, ts_compare, ts_tz_sql
from serenedb_extractor.setup.sniff import readable
from serenedb_extractor.telemetry.common import (
    SOURCES,
    Extent,
    TableSet,
    Window,
    extent,
    fmt_us,
    parse_window,
    services_by_source,
    tables_with_prefix,
    window_note,
)
from serenedb_extractor.telemetry.log_changes import _dt
from serenedb_extractor.tools.describe import known_columns

TOOL_ANNOTATIONS: dict[str, tuple[bool | None, bool | None]] = {"telemetry_overview": (True, None)}

Counts = dict[str, list[int]]  # service -> [before, after]


def _log_counts(ctx: AppContext, tables: TableSet, w: Window, notes: list[str]) -> Counts:
    out: Counts = {}
    for lt in tables.logs:
        if lt.roles.timestamp is None:
            notes.append(f"Log table {lt.name} has no timestamp role, so its entries are not counted before or after the pivot.")
            continue
        with readable(f"the source of log table '{lt.name}'"):
            cols = known_columns(ctx.db, lt)
            lo, p_lo = ts_compare(lt, ">=", _dt(w.start_us), "w_lo", cols)
            hi, p_hi = ts_compare(lt, "<", _dt(w.end_us), "w_hi", cols)
            after, p_after = ts_compare(lt, ">=", _dt(w.pivot_us), "w_pivot", cols)
            svc = f"({role_sql(lt, 'service')})::varchar" if lt.roles.service is not None else "NULL::varchar"
            rows = ctx.db.read(
                f"SELECT {svc} AS svc, CASE WHEN {after} THEN 1 ELSE 0 END AS p, count(*) AS n "
                f"FROM {lt.relation} WHERE {lo} AND {hi} GROUP BY 1, 2",
                {**p_lo, **p_hi, **p_after},
                what=f"counting log table {lt.name} around the pivot",
            ).rows
        unassigned = [0, 0]
        for s, p, n in rows:
            if s is None:
                unassigned[int(p)] += int(n)
            else:
                out.setdefault(str(s), [0, 0])[int(p)] += int(n)
        if any(unassigned):
            why = "has no service role" if lt.roles.service is None else "has entries without a service"
            notes.append(
                f"Log table {lt.name} {why}: {unassigned[0]:,} entries before and {unassigned[1]:,} after the pivot "
                "are not counted for any service."
            )
    return out


def _span_counts(ctx: AppContext, tables: TableSet, w: Window) -> Counts:
    out: Counts = {}
    for tt in tables.traces:
        rows = ctx.db.read(
            f"SELECT CAST({quote_ident(tt.service)} AS VARCHAR) AS svc, CASE WHEN start_us >= {w.pivot_us} THEN 1 ELSE 0 END AS p, "
            f"count(*) AS n FROM {tt.relation} WHERE start_us >= {w.start_us} AND start_us < {w.end_us} "
            f"AND {quote_ident(tt.service)} IS NOT NULL GROUP BY 1, 2",
            {},
            what=f"counting the spans of trace table {tt.name} around the pivot",
        ).rows
        for s, p, n in rows:
            out.setdefault(str(s), [0, 0])[int(p)] += int(n)
    return out


def _metric_names(ctx: AppContext, tables: TableSet, notes: list[str]) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for mt in tables.metrics:
        metric = quote_ident(mt.metric)
        if mt.service is None:
            rows = ctx.db.read(f"SELECT DISTINCT CAST({metric} AS VARCHAR) FROM {mt.relation} ORDER BY 1 LIMIT 41", {}).rows
            names = [str(r[0]) for r in rows]
            notes.append(
                f"Metric table {mt.name} has no service column, so its metrics belong to no service: "
                + ", ".join(names[:40])
                + (", …" if len(names) > 40 else "")
                + "."
            )
            continue
        rows = ctx.db.read(
            f"SELECT DISTINCT CAST({quote_ident(mt.service)} AS VARCHAR), CAST({metric} AS VARCHAR) FROM {mt.relation} "
            f"WHERE {quote_ident(mt.service)} IS NOT NULL",
            {},
        ).rows
        for s, m in rows:
            out.setdefault(str(s), set()).add(str(m))
    return out


def _log_extent(ctx: AppContext, lt: Any) -> Extent:
    return extent(ctx, lt.relation, f"epoch_us({ts_tz_sql(lt, known_columns(ctx.db, lt))})")


def _change(c: list[int] | None, has_source: bool, comparable: bool = True) -> str:
    if c is None:
        return "none in either window" if has_source else "none (no data of this kind for this service)"
    before, after = c
    if not comparable:
        return f"{before:,} before, {after:,} after (not comparable: the data does not cover the window, see above)"
    if before == 0:
        return f"{before:,} before, {after:,} after (none before, so no percent)"
    return f"{before:,} before, {after:,} after ({100 * (after - before) / before:+.1f}%)"


def telemetry_overview(
    ctx: AppContext,
    prefix: str,
    pivot: str,
    before_minutes: float = 10,
    after_minutes: float = 10,
    timezone: str | None = None,
) -> str:
    w = parse_window(pivot, before_minutes, after_minutes, timezone)
    tables = tables_with_prefix(ctx, prefix)
    notes: list[str] = []
    by_source = services_by_source(ctx, tables)
    logs = _log_counts(ctx, tables, w, notes)
    spans = _span_counts(ctx, tables, w)
    metrics = _metric_names(ctx, tables, notes)
    log_cover = [
        n for lt in tables.logs if lt.roles.timestamp is not None
        if (n := window_note(f"log table {lt.name}", _log_extent(ctx, lt), w))
    ]
    span_cover = [n for tt in tables.traces if (n := window_note(f"trace table {tt.name}", extent(ctx, tt.relation, "start_us"), w))]
    notes += log_cover + span_cover
    kinds: list[tuple[str, list[str]]] = [
        ("logs", [t.name for t in tables.logs]),
        ("metrics", [t.name for t in tables.metrics]),
        ("traces", [t.name for t in tables.traces]),
    ]
    listed = [f"{name} ({kind})" for kind, names in kinds for name in names]
    missing = [kind for kind, names in kinds if not names]
    found: set[str] = set(logs) | set(spans) | set(metrics)
    for seen in by_source.values():
        found |= seen
    services = sorted(found)
    lines = [
        fmt.how_measured(
            "telemetry_overview, exact: every log entry and span in both windows was counted per service; "
            "metric names were read from the metric tables",
            w.describe(),
        ),
        f"pivot {fmt_us(w.pivot_us)} UTC; windows of {before_minutes:g} minutes before and {after_minutes:g} after it.",
        f"tables: {', '.join(listed)}",
        f"missing entirely: {', '.join(missing)} (no such table starts with '{tables.prefix}')" if missing else
        "logs, metrics and traces all have tables.",
        *notes,
        f"services ({len(services)}), by name, not ordered by any change:",
    ]
    if not services:
        lines.append("  no services found")
    for s in services:
        coverage = ", ".join(f"{src} {'yes' if s in by_source[src] else 'no'}" for src in SOURCES)
        names = sorted(metrics.get(s, set()))
        lines += [
            "",
            f"{s}:",
            f"  coverage: {coverage}",
            f"  metrics: {', '.join(names) if names else 'none'}",
            f"  log entries: {_change(logs.get(s), s in by_source['logs'], not log_cover)}",
            f"  spans: {_change(spans.get(s), s in by_source['traces'], not span_cover)}",
        ]
    lines += ["", "coverage 'no' means no data, not no change."]
    return "\n".join(lines)


_telemetry_overview = telemetry_overview  # the registered tool below shadows the name


def register(mcp: Any, runner: Any) -> None:
    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def telemetry_overview(
        prefix: str, pivot: str, before_minutes: float = 10, after_minutes: float = 10, timezone: str | None = None
    ) -> str:
        """START HERE when metric or trace tables exist: one view of a system's logs, metrics and traces around a moment (the pivot), per service.
        Use when: a system's tables share a prefix (e.g. shop_logs, shop_metrics, shop_traces) and something happened at a known time; then go on with metric_changes, trace_changes and log_changes.
        Inputs: prefix (the tables' shared name start, ending in '_'); pivot (ISO time; without an offset it is read in timezone, default UTC); before_minutes / after_minutes (default 10 / 10).
        Returns: the prefix's tables and which of logs, metrics, traces are missing; per service (sorted by name, not ranked): coverage (logs, metrics, traces yes/no), metric names, log entries and spans before and after the pivot with the change in percent."""
        return await runner.run_tool(
            _telemetry_overview,
            prefix=prefix,
            pivot=pivot,
            before_minutes=before_minutes,
            after_minutes=after_minutes,
            timezone=timezone,
        )
