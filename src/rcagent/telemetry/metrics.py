"""metric_changes, metric_series: what moved in the metric series across a pivot, and the series themselves.

Reports change sizes only (the fixed statistic of stats.change); it never names a cause.
"""

from dataclasses import dataclass
from typing import Any, Literal

from mcp.types import ToolAnnotations

from rcagent import format as fmt
from rcagent.context import AppContext
from rcagent.db import quote_ident
from rcagent.errors import UserFacingError
from rcagent.setup.paths import sql_literal
from rcagent.setup.sniff import relation_columns
from rcagent.telemetry.common import (
    coverage_lines,
    epoch_us_sql,
    fmt_us,
    parse_time,
    parse_window,
    services_by_source,
    tables_with_prefix,
    to_us,
)
from rcagent.telemetry.registry import MetricTable, TelemetryStore
from rcagent.telemetry.stats import FLOOR, MAD_SCALE, MIN_POINTS, Change, change

TOOL_ANNOTATIONS: dict[str, tuple[bool | None, bool | None]] = {
    "metric_changes": (True, None),
    "metric_series": (True, None),
}
NO_SERVICE = "(no service)"
MAX_TOP = 200
SERIES_ROW_CAP = 400
STATISTIC = (
    f"z = (median after - median before) / spread; spread = {MAD_SCALE} x MAD of the baseline, or its standard "
    f"deviation when MAD is 0, never less than {FLOOR:.0%} of |median before|; at least {MIN_POINTS} points on each side"
)


@dataclass(frozen=True)
class Series:
    table: str
    service: str
    metric: str
    change: Change


def _num(v: float | None) -> str:
    return "none" if v is None else f"{v:.4g}"


def _in_list(values: list[str]) -> str:
    return ", ".join(sql_literal(str(v)) for v in values)


def _source_sql(
    ctx: AppContext,
    mt: MetricTable,
    start_us: int,
    end_us: int,
    services: list[str] | None,
    metrics: list[str] | None,
) -> str:
    """A SELECT of (service, metric, v, t) for one metric table, filtered by the window and the lists."""
    types = dict(relation_columns(ctx.db, mt.relation))
    ts = quote_ident(mt.timestamp)
    t_sql = epoch_us_sql(ts, types.get(mt.timestamp, ""), mt.timestamp_unit, mt.timezone)
    svc_sql = (
        f"coalesce(CAST({quote_ident(mt.service)} AS VARCHAR), {sql_literal(NO_SERVICE)})"
        if mt.service
        else sql_literal(NO_SERVICE)
    )
    metric_sql = f"CAST({quote_ident(mt.metric)} AS VARCHAR)"
    where = ["v IS NOT NULL", f"t >= {int(start_us)}", f"t < {int(end_us)}"]
    if services:
        where.append(f"service IN ({_in_list(services)})")
    if metrics:
        where.append(f"metric IN ({_in_list(metrics)})")
    return (
        f"SELECT * FROM (SELECT {svc_sql} AS service, {metric_sql} AS metric, "
        f"CAST({quote_ident(mt.value)} AS DOUBLE) AS v, {t_sql} AS t "
        f"FROM {mt.relation}) x WHERE " + " AND ".join(where)
    )


def _resolve_tables(ctx: AppContext, prefix: str | None, table: str | None) -> tuple[list[MetricTable], Any]:
    if (prefix is None) == (table is None):
        raise UserFacingError("Give a prefix or table, exactly one (e.g. prefix='shop_' or table='shop_metrics').")
    if table is not None:
        return [TelemetryStore(ctx.db).get_metric_table(table)], None
    found = tables_with_prefix(ctx, str(prefix))
    if not found.metrics:
        raise UserFacingError(
            f"No metric table name starts with '{found.prefix}' (its tables: {', '.join(found.names)}). "
            "Register metrics with setup_metric_table under that prefix."
        )
    return found.metrics, found


def metric_changes(
    ctx: AppContext,
    pivot: str,
    prefix: str | None = None,
    table: str | None = None,
    before_minutes: float = 10,
    after_minutes: float = 10,
    services: list[str] | None = None,
    metrics: list[str] | None = None,
    sort: Literal["median", "peak"] = "median",
    top: int = 20,
    timezone: str | None = None,
) -> str:
    if sort not in ("median", "peak"):
        raise UserFacingError("sort must be 'median' or 'peak'.")
    tables, found = _resolve_tables(ctx, prefix, table)
    window = parse_window(pivot, before_minutes, after_minutes, timezone)
    top = fmt.clamp_limit(top, 20, MAX_TOP)
    series: list[Series] = []
    for mt in tables:
        src = _source_sql(ctx, mt, window.start_us, window.end_us, services, metrics)
        p = int(window.pivot_us)
        sql = (
            f"WITH src AS ({src}), "
            f"b AS (SELECT service, metric, quantile_cont(v, 0.5) AS med, stddev_samp(v) AS sd, count(*) AS n "
            f"FROM src WHERE t < {p} GROUP BY service, metric), "
            f"bm AS (SELECT s.service, s.metric, quantile_cont(abs(s.v - b.med), 0.5) AS mad FROM src s "
            f"JOIN b ON s.service = b.service AND s.metric = b.metric WHERE s.t < {p} GROUP BY s.service, s.metric), "
            f"a AS (SELECT s.service, s.metric, quantile_cont(s.v, 0.5) AS med, count(*) AS n, "
            f"arg_max(s.v, abs(s.v - coalesce(b.med, 0))) AS peak FROM src s "
            f"LEFT JOIN b ON s.service = b.service AND s.metric = b.metric WHERE s.t >= {p} "
            f"GROUP BY s.service, s.metric) "
            f"SELECT coalesce(a.service, b.service) AS service, coalesce(a.metric, b.metric) AS metric, "
            f"b.med AS med_b, bm.mad AS mad_b, b.sd AS sd_b, coalesce(b.n, 0) AS n_b, "
            f"a.med AS med_a, coalesce(a.n, 0) AS n_a, a.peak AS peak "
            f"FROM b FULL OUTER JOIN a ON a.service = b.service AND a.metric = b.metric "
            f"LEFT JOIN bm ON bm.service = b.service AND bm.metric = b.metric "
            f"ORDER BY 1, 2"
        )
        rows = ctx.db.read(sql, {}, what=f"comparing the series of {mt.name} before and after the pivot").dicts()
        for r in rows:
            c = change(r["med_b"], r["mad_b"], r["sd_b"], r["n_b"], r["med_a"], r["n_a"], r["peak"])
            series.append(Series(mt.name, str(r["service"]), str(r["metric"]), c))

    names = [mt.name for mt in tables]
    many = len(tables) > 1
    filters = "; ".join(
        f for f in (
            f"services {', '.join(services)}" if services else "",
            f"metrics {', '.join(metrics)}" if metrics else "",
        ) if f
    )
    lines = [
        fmt.how_measured(
            f"robust change of every metric series across the pivot, one aggregate query per metric table ({', '.join(names)})",
            period=window.describe(),
            filters=filters or None,
        ),
        f"window: {window.describe()}"
        + (" (the 10/10 minute defaults)" if (before_minutes, after_minutes) == (10, 10) else ""),
        f"statistic: {STATISTIC}.",
        f"series compared: {len(series)}",
        "",
    ]

    def label(s: Series) -> str:
        return f"{s.service} / {s.metric}" + (f" [{s.table}]" if many else "")

    zs = [s for s in series if s.change.kind == "z"]
    if sort == "peak":
        zs.sort(key=lambda s: abs(s.change.peak_z or 0.0), reverse=True)
    else:
        zs.sort(key=lambda s: s.change.size, reverse=True)
    shown = zs[:top]
    lines.append(
        f"largest changes by {'|peak z|' if sort == 'peak' else '|z|'} ({len(shown)} of {len(zs)} ranked series):"
    )
    for s in shown:
        c = s.change
        lines.append(
            f"  {label(s)}: median {_num(c.median_before)} -> {_num(c.median_after)}, z {c.z:+.1f}, "
            f"peak {_num(c.peak_after)} (peak z {(c.peak_z or 0.0):+.1f}), points {c.n_before}/{c.n_after}"
        )
    if not shown:
        lines.append("  none")
    lines.append("")

    rose = [s for s in series if s.change.kind == "rose_from_zero"]
    lines.append("rose from zero (the baseline is all zero, so z is undefined; not ranked):")
    lines += [
        f"  {label(s)}: median after {_num(s.change.median_after)}, peak {_num(s.change.peak_after)}" for s in rose
    ] or ["  none"]
    lines.append("")

    little = [s for s in series if s.change.kind == "too_little_data"]
    zero = [s for s in series if s.change.kind == "unchanged"]
    lines.append(f"too little data (fewer than {MIN_POINTS} points on a side): {len(little)} series")
    if little:
        cut, note = fmt.cut(little, 10, "series")
        lines += [f"  {label(s)}: points {s.change.n_before}/{s.change.n_after}" for s in cut]
        if note:
            lines.append(f"  ({note})")
    lines.append(f"zero on both sides: {len(zero)} series")
    lines.append("")

    per: dict[str, Series] = {}
    for s in zs:
        if s.service not in per or s.change.size > per[s.service].change.size:
            per[s.service] = s
    rose_by: dict[str, list[str]] = {}
    for s in rose:
        rose_by.setdefault(s.service, []).append(s.metric)
    rose_only = sorted(set(rose_by) - set(per))
    lines.append(
        "largest change per service (its max |z| over its series; describes how much changed, not a cause ranking):"
    )
    for svc, s in sorted(per.items(), key=lambda kv: kv[1].change.size, reverse=True):
        also = f"; rose from zero: {', '.join(rose_by[svc])}" if svc in rose_by else ""
        lines.append(f"  {svc}: |z| {s.change.size:.1f} ({s.metric}){also}")
    for svc in rose_only:
        lines.append(f"  {svc}: only series that rose from zero ({', '.join(rose_by[svc])})")
    if not per and not rose_only:
        lines.append("  none")
    lines.append("")

    if found is not None:
        lines += coverage_lines(services_by_source(ctx, found))
    else:
        lines.append("coverage needs a prefix: give prefix= to see which services have logs, metrics and traces.")
    return "\n".join(lines)


def metric_series(
    ctx: AppContext,
    table: str,
    start: str,
    end: str,
    services: list[str] | None = None,
    metrics: list[str] | None = None,
    bucket_seconds: int = 30,
    timezone: str | None = None,
) -> str:
    mt = TelemetryStore(ctx.db).get_metric_table(table)
    if not 1 <= int(bucket_seconds) <= 86_400:
        raise UserFacingError("bucket_seconds must be between 1 and 86400.")
    start_us, end_us = to_us(parse_time(start, timezone)), to_us(parse_time(end, timezone))
    if end_us <= start_us:
        raise UserFacingError("end must be after start.")
    b = int(bucket_seconds) * 1_000_000
    src = _source_sql(ctx, mt, start_us, end_us, services, metrics)
    rows = ctx.db.read(
        f"WITH src AS ({src}) SELECT service, metric, (t // {b}) * {b} AS bucket, min(v) AS lo, "
        f"quantile_cont(v, 0.5) AS med, max(v) AS hi, count(*) AS n FROM src "
        f"GROUP BY service, metric, bucket ORDER BY service, metric, bucket LIMIT {SERIES_ROW_CAP + 1}",
        {},
        what=f"bucketing the series of {mt.name}",
    ).dicts()
    cut = len(rows) > SERIES_ROW_CAP
    rows = rows[:SERIES_ROW_CAP]
    filters = "; ".join(
        f for f in (
            f"services {', '.join(services)}" if services else "",
            f"metrics {', '.join(metrics)}" if metrics else "",
        ) if f
    )
    lines = [
        fmt.how_measured(
            f"min, median and max per {bucket_seconds} s bucket of each series in {mt.name}",
            period=f"{fmt_us(start_us)} to {fmt_us(end_us)} (UTC)",
            filters=filters or None,
        ),
    ]
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for r in rows:
        groups.setdefault((str(r["service"]), str(r["metric"])), []).append(r)
    for (svc, metric), rs in groups.items():
        lines.append(f"{svc} / {metric} ({len(rs)} buckets of {bucket_seconds} s):")
        for r in rs:
            lines.append(
                f"  {fmt_us(r['bucket'])}  min {_num(r['lo'])}  median {_num(r['med'])}  max {_num(r['hi'])}  (n {r['n']})"
            )
    if not groups:
        lines.append("no points in this range" + (" for these filters" if filters else ""))
    if cut:
        lines.append(
            f"rows cut at {SERIES_ROW_CAP} (buckets); narrow with services/metrics, a shorter range or larger buckets."
        )
    return "\n".join(lines)


_metric_changes = metric_changes  # the registered tools below shadow the names
_metric_series = metric_series


def register(mcp: Any, runner: Any) -> None:
    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def metric_changes(
        pivot: str,
        prefix: str | None = None,
        table: str | None = None,
        before_minutes: float = 10,
        after_minutes: float = 10,
        services: list[str] | None = None,
        metrics: list[str] | None = None,
        sort: Literal["median", "peak"] = "median",
        top: int = 20,
        timezone: str | None = None,
    ) -> str:
        """Which metric series changed across a pivot time: per (service, metric) a robust z of the median after vs before.
        Use when: you have a suspected incident time and want to see which services' metrics moved. It reports change sizes, not causes. For a short incident (shorter than half the after-window) the median barely moves: use sort="peak" or a shorter after_minutes.
        Inputs: pivot (ISO time); exactly one of prefix (all metric tables of a system, e.g. 'shop_') or table; before_minutes/after_minutes (default 10/10); services, metrics to filter; sort 'median' (|z|) or 'peak' (|peak z|, the after-value farthest from the baseline); top (20); timezone for a pivot without offset (default UTC).
        Returns: top series with medians before -> after, z and peak; series that rose from zero (listed apart); too-little-data count; largest change per service; coverage per service when a prefix is given."""
        return await runner.run_tool(
            _metric_changes, pivot=pivot, prefix=prefix, table=table, before_minutes=before_minutes,
            after_minutes=after_minutes, services=services, metrics=metrics, sort=sort, top=top, timezone=timezone,
        )

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def metric_series(
        table: str,
        start: str,
        end: str,
        services: list[str] | None = None,
        metrics: list[str] | None = None,
        bucket_seconds: int = 30,
        timezone: str | None = None,
    ) -> str:
        """The metric series themselves, bucketed: min, median and max per bucket.
        Use when: checking that a change metric_changes reported is real (a step, a spike, or noise).
        Inputs: table (a metric table); start, end (ISO times); services, metrics to filter; bucket_seconds (30); timezone for times without offset (default UTC).
        Returns: per series one line per bucket; output is capped and says when it was cut."""
        return await runner.run_tool(
            _metric_series, table=table, start=start, end=end, services=services, metrics=metrics,
            bucket_seconds=bucket_seconds, timezone=timezone,
        )
