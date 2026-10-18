"""log_changes: per service, how a log table's templates, error-ish share and volume moved across a pivot.

The windows are surveyed first (the incident window, then the baseline) with the ordinary survey, so
templates that only appear after the pivot are in the catalog; then every entry of both windows is read
and counted exactly per service and catalog template. The catalog's first_seen is never trusted: a
template is "new after the pivot" only when its exact count before is zero.
"""

import math
import statistics
from datetime import UTC, datetime, timedelta
from typing import Any

from mcp.types import ToolAnnotations

from serenedb_extractor import format as fmt
from serenedb_extractor.catalog.models import LogTable, Template
from serenedb_extractor.context import AppContext
from serenedb_extractor.errors import UserFacingError
from serenedb_extractor.query import cost
from serenedb_extractor.query.filters import role_sql, ts_compare, ts_tz_sql
from serenedb_extractor.query.templatematch import template_match_sql
from serenedb_extractor.setup.sniff import readable
from serenedb_extractor.telemetry import stats
from serenedb_extractor.telemetry.common import (
    TableSet,
    Window,
    coverage_lines,
    fmt_us,
    parse_window,
    services_by_source,
    tables_with_prefix,
)
from serenedb_extractor.tools import survey as survey_tool
from serenedb_extractor.tools.describe import known_columns

TOOL_ANNOTATIONS: dict[str, tuple[bool | None, bool | None]] = {"log_changes": (False, False)}

ERRORISH_LEVELS = ("error", "fatal", "critical")
ERRORISH_PATTERN = "error|exception|fail|fatal|panic|traceback"
TOP_CHANGES = 5
TEMPLATES_PER_QUERY = 40
MINUTE_US = 60_000_000


def _dt(us: int) -> datetime:
    return datetime(1970, 1, 1, tzinfo=UTC) + timedelta(microseconds=us)


def _iso(us: int) -> str:
    return _dt(us).isoformat()


def _log_tables(ctx: AppContext, prefix: str | None, log_table: str | None) -> tuple[TableSet, list[LogTable]]:
    if log_table:
        lt = ctx.store.get_log_table(log_table)
        tables = tables_with_prefix(ctx, prefix) if prefix else TableSet(prefix="", logs=[lt])
        return tables, [lt]
    if not prefix:
        raise UserFacingError("Give a table prefix (e.g. prefix='shop_') or a log_table.")
    tables = tables_with_prefix(ctx, prefix)
    if not tables.logs:
        raise UserFacingError(
            f"No log table name starts with '{tables.prefix}' (its tables: {', '.join(tables.names)}), "
            "so there are no logs to compare."
        )
    return tables, tables.logs


def _usable(lt: LogTable) -> str | None:
    """Why the table can't be compared per service across a pivot, or None."""
    if lt.roles.service is None:
        return (
            f"Log table '{lt.name}' has no service role, so log_changes can't count its entries per service. "
            "If a column holds the service, set it with setup_log_table (roles={'service': '<column>'})."
        )
    if lt.roles.timestamp is None:
        return f"Log table '{lt.name}' has no timestamp role, so its entries can't be placed before or after the pivot."
    return None


def _survey_windows(ctx: AppContext, lt: LogTable, w: Window) -> list[str]:
    """Survey the incident window, then the baseline, so their templates are in the catalog."""
    notes = []
    for label, a, b in (("incident", w.pivot_us, w.end_us), ("baseline", w.start_us, w.pivot_us)):
        out = survey_tool.survey(ctx, lt.name, start=_iso(a), end=_iso(b), timezone="UTC")
        if cost.ASKED_HOW in out:
            notes.append(
                f"The {label} window of {lt.name} was too large to survey within the time budget, so templates "
                "seen only there may be missing from the catalog and from these counts."
            )
    return notes


def _errorish_sql(lt: LogTable, msg: str) -> tuple[str, str]:
    if lt.roles.level is not None:
        levels = ", ".join(f"'{v}'" for v in ERRORISH_LEVELS)
        return (
            f"lower(({role_sql(lt, 'level')})::varchar) IN ({levels})",
            f"level is {'/'.join(ERRORISH_LEVELS)}",
        )
    return (
        f"regexp_matches({msg}, '{ERRORISH_PATTERN}', 'i')",
        f"message matches {ERRORISH_PATTERN} (no level role)",
    )


class _Counts:
    def __init__(self, n_before_buckets: int, n_after_buckets: int) -> None:
        self.entries = [0, 0]
        self.errorish = [0, 0]
        self.minutes = [[0] * n_before_buckets, [0] * n_after_buckets]
        self.templates: dict[str, list[int]] = {}


def _count(
    ctx: AppContext, lt: LogTable, w: Window, services: list[str] | None, templates: list[Template]
) -> tuple[dict[str, _Counts], str]:
    with readable(f"the source of log table '{lt.name}'"):
        cols = known_columns(ctx.db, lt)
        lo, p_lo = ts_compare(lt, ">=", _dt(w.start_us), "w_lo", cols)
        hi, p_hi = ts_compare(lt, "<", _dt(w.end_us), "w_hi", cols)
        after, p_after = ts_compare(lt, ">=", _dt(w.pivot_us), "w_pivot", cols)
        params: dict[str, Any] = {**p_lo, **p_hi, **p_after}
        svc = f"({role_sql(lt, 'service')})::varchar"
        where = f"{lo} AND {hi} AND {svc} IS NOT NULL"
        if services:
            names = {f"svc_{i}": s for i, s in enumerate(services)}
            where += f" AND {svc} IN ({', '.join(f'%({k})s' for k in names)})"
            params.update(names)
        msg = f"coalesce(({role_sql(lt, 'message')})::varchar, '')"
        errorish, rule = _errorish_sql(lt, msg)
        inner = (
            f"SELECT {svc} AS svc, CASE WHEN {after} THEN 1 ELSE 0 END AS p, epoch_us({ts_tz_sql(lt, cols)}) AS us, "
            f"{msg} AS msg, CASE WHEN {errorish} THEN 1 ELSE 0 END AS e FROM {lt.relation} WHERE {where}"
        )
        what = f"counting log table {lt.name} around the pivot"
        n_before = math.ceil((w.pivot_us - w.start_us) / MINUTE_US)
        n_after = math.ceil((w.end_us - w.pivot_us) / MINUTE_US)
        out: dict[str, _Counts] = {}
        rows = ctx.db.read(
            f"SELECT svc, p, CAST((us - CASE WHEN p = 1 THEN {w.pivot_us} ELSE {w.start_us} END) // {MINUTE_US} AS BIGINT) AS m, "
            f"count(*) AS n, sum(e) AS e FROM ({inner}) GROUP BY 1, 2, 3",
            params,
            what=what,
        ).rows
        for s, p, m, n, e in rows:
            c = out.setdefault(str(s), _Counts(n_before, n_after))
            c.entries[p] += int(n)
            c.errorish[p] += int(e or 0)
            if 0 <= m < len(c.minutes[p]):
                c.minutes[p][int(m)] += int(n)
        for start in range(0, len(templates), TEMPLATES_PER_QUERY):
            chunk = templates[start : start + TEMPLATES_PER_QUERY]
            t_params = dict(params)
            sums = []
            for i, t in enumerate(chunk):
                t_params[f"re_{i}"] = t.regex
                sums.append(f"sum(CASE WHEN {template_match_sql('msg', f're_{i}')} THEN 1 ELSE 0 END) AS c_{i}")
            rows = ctx.db.read(f"SELECT svc, p, {', '.join(sums)} FROM ({inner}) GROUP BY 1, 2", t_params, what=what).rows
            for row in rows:
                c = out[str(row[0])]
                for i, t in enumerate(chunk):
                    n = int(row[2 + i] or 0)
                    if n:
                        c.templates.setdefault(t.template_id, [0, 0])[int(row[1])] += n
    return out, rule


def _volume_change(minutes: list[list[int]]) -> stats.Change:
    before, after = [float(v) for v in minutes[0]], [float(v) for v in minutes[1]]
    if not before or not after:
        return stats.change(None, None, None, len(before), None, len(after))
    med = statistics.median(before)
    mad = statistics.median([abs(v - med) for v in before])
    std = statistics.stdev(before) if len(before) > 1 else 0.0
    return stats.change(med, mad, std, len(before), statistics.median(after), len(after), max(after))


def _num(v: float | None) -> str:
    if v is None:
        return "none"
    return f"{v:,.0f}" if float(v).is_integer() else f"{v:,.1f}"


def _volume_text(ch: stats.Change) -> str:
    base = f"median {_num(ch.median_before)} before, {_num(ch.median_after)} after (peak after {_num(ch.peak_after)})"
    if ch.kind == "z":
        return f"{base}; z {ch.z:+.1f}"
    if ch.kind == "rose_from_zero":
        return f"{base}; rose from zero (no spread before, so no z)"
    if ch.kind == "unchanged":
        return f"{base}; zero on both sides"
    return f"{base}; too little data ({ch.n_before} minutes before, {ch.n_after} after; at least {stats.MIN_POINTS} each needed)"


def _rate(e: int, n: int) -> str:
    return f"{100 * e / n:.1f}% ({e:,} of {n:,})" if n else "no entries"


def _service_lines(name: str, c: _Counts, by_id: dict[str, Template], rule: str) -> list[str]:
    out = [f"service {name}  (entries: {c.entries[0]:,} before, {c.entries[1]:,} after)"]
    new = sorted(
        ((tid, n) for tid, n in c.templates.items() if n[0] == 0 and n[1] > 0), key=lambda x: (-x[1][1], x[0])
    )
    if new:
        out.append("  new after the pivot (0 before, seen after):")
        for tid, n in new:
            t = by_id[tid]
            out.append(f"    {tid}  {fmt.template_text(t.template)}  0 before, {n[1]:,} after")
            out.append(f"        example: {fmt.shorten(fmt.template_text(t.example), 200)}")
    else:
        out.append("  new after the pivot: none")
    moved = sorted(
        ((tid, n) for tid, n in c.templates.items() if n[0] > 0 and n[0] != n[1]),
        key=lambda x: (-abs(x[1][1] - x[1][0]), x[0]),
    )[:TOP_CHANGES]
    if moved:
        out.append("  biggest count changes (templates seen before too):")
        for tid, n in moved:
            gone = "  (none after the pivot)" if n[1] == 0 else ""
            out.append(
                f"    {tid}  {fmt.template_text(by_id[tid].template)}  {n[0]:,} before, {n[1]:,} after ({n[1] - n[0]:+,}){gone}"
            )
    else:
        out.append("  biggest count changes: none (templates seen before have the same counts after)")
    out.append(f"  error-ish rate: {_rate(c.errorish[0], c.entries[0])} before, {_rate(c.errorish[1], c.entries[1])} after  [{rule}]")
    out.append(f"  log volume per minute: {_volume_text(_volume_change(c.minutes))}")
    return out


def log_changes(
    ctx: AppContext,
    pivot: str,
    prefix: str | None = None,
    log_table: str | None = None,
    before_minutes: float = 10,
    after_minutes: float = 10,
    services: list[str] | None = None,
    timezone: str | None = None,
) -> str:
    w = parse_window(pivot, before_minutes, after_minutes, timezone)
    tables, logs = _log_tables(ctx, prefix, log_table)
    problems = [p for lt in logs if (p := _usable(lt))]
    usable = [lt for lt in logs if _usable(lt) is None]
    if not usable:
        raise UserFacingError(" ".join(problems))
    scope = f"services {', '.join(services)}" if services else None
    lines = [
        fmt.how_measured(
            "log_changes, exact: both windows were surveyed into the catalog, then every entry in them was read "
            "and counted per service and template",
            w.describe(),
            scope,
        ),
        f"pivot {fmt_us(w.pivot_us)} UTC; windows of {before_minutes:g} minutes before and {after_minutes:g} after it.",
        *problems,
    ]
    for lt in usable:
        notes = _survey_windows(ctx, lt, w)
        templates = ctx.store.templates(lt.name)
        counts, rule = _count(ctx, lt, w, services, templates)
        by_id = {t.template_id: t for t in templates}
        lines += ["", f"log table {lt.name}: {len(templates)} catalog templates counted.", *notes]
        if not counts:
            lines.append("No entries with a service in either window.")
        for name in sorted(counts):
            lines += ["", *_service_lines(name, counts[name], by_id, rule)]
    by_source = services_by_source(ctx, tables)
    if services:
        by_source = {k: v & set(services) for k, v in by_source.items()}
    lines += ["", *coverage_lines(by_source)]
    return "\n".join(lines)


_log_changes = log_changes  # the registered tool below shadows the name


def register(mcp: Any, runner: Any) -> None:
    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False))
    async def log_changes(
        pivot: str,
        prefix: str | None = None,
        log_table: str | None = None,
        before_minutes: float = 10,
        after_minutes: float = 10,
        services: list[str] | None = None,
        timezone: str | None = None,
    ) -> str:
        """What changed in the logs of each service across a moment (the pivot): templates that appear only after it, the biggest count changes, the error-ish share and the log volume per minute.
        Use when: something happened at a known time and you want each service's log changes side by side, next to metric_changes and trace_changes. Surveys both windows first (adds their templates to the catalog), then counts exactly.
        Inputs: pivot (ISO time; without an offset it is read in timezone, default UTC); prefix (all log tables starting with it) or log_table; before_minutes / after_minutes (default 10 / 10); services to narrow to. Needs the log table's service role.
        Returns: per service (sorted by name): templates with zero entries before and some after (count and example), the biggest count changes, error-ish rate before/after (level error/fatal/critical, or the message matching error|exception|fail|fatal|panic|traceback when there is no level), and the per-minute volume change (robust z); plus coverage per service. It reports changes only; it does not say which service caused them."""
        return await runner.run_tool(
            _log_changes,
            pivot=pivot,
            prefix=prefix,
            log_table=log_table,
            before_minutes=before_minutes,
            after_minutes=after_minutes,
            services=services,
            timezone=timezone,
        )
