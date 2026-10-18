"""trace_changes and get_trace over trace tables (copies made by setup_trace_table, normalized columns).

trace_changes compares the window before the pivot with the window after it, per (service, operation)
and per edge between services. It reports what changed; it never says which service is the cause.
"""

import statistics
from dataclasses import dataclass
from typing import Any

from mcp.types import ToolAnnotations

from rcagent import format as fmt
from rcagent.context import AppContext
from rcagent.errors import UserFacingError
from rcagent.telemetry.common import (
    Extent,
    TableSet,
    Window,
    coverage_lines,
    extent,
    fmt_us,
    minute_covered,
    parse_window,
    services_by_source,
    tables_with_prefix,
    window_note,
)
from rcagent.telemetry.registry import TelemetryStore, TraceTable
from rcagent.telemetry.stats import MIN_POINTS, Change, change

TOOL_ANNOTATIONS: dict[str, tuple[bool | None, bool | None]] = {"trace_changes": (True, None), "get_trace": (True, None)}
SORTS = ("self_time", "errors", "volume")
MAX_TOP = 200
MAX_TRACE_SPANS = 500
STATISTIC = (
    "z = (median after - median before) / spread; spread = 1.4826 * MAD before, or the standard deviation "
    f"before if MAD is 0, at least 1% of |median before|; at least {MIN_POINTS} values per side"
)


# ------------------------------------------------------------------ formatting


def _ms(us: float | None) -> str:
    if us is None:
        return "?"
    v = us / 1000
    return f"{v:.0f}" if abs(v) >= 1000 else f"{v:.1f}" if abs(v) >= 1 or v == 0 else f"{v:.3f}"


def _z(c: Change) -> str:
    if c.kind == "z" and c.z is not None:
        return f"z {c.z:+.1f}"
    return {"rose_from_zero": "rose from zero", "unchanged": "unchanged (zero on both sides)"}.get(
        c.kind, f"too little data (n {c.n_before}/{c.n_after})"
    )


def _rate(errors: int, known: int) -> str:
    return "unknown" if known == 0 else f"{100.0 * errors / known:.1f}%"


def _errors(eb: int, kb: int, ea: int, ka: int, total_b: int, total_a: int) -> str:
    if kb == 0 and ka == 0:
        return "errors unknown (no status)"
    out = f"errors {_rate(eb, kb)} -> {_rate(ea, ka)}"
    if kb < total_b or ka < total_a:
        out += f" (status known for {kb}/{total_b} -> {ka}/{total_a} spans)"
    return out


def _f(v: Any) -> float | None:
    return None if v is None else float(v)


# ------------------------------------------------------------------ tables


def _trace_tables(ctx: AppContext, prefix: str | None, table: str | None) -> tuple[list[TraceTable], TableSet | None]:
    if prefix and table:
        raise UserFacingError("Give either prefix (all trace tables of a system) or table (one trace table), not both.")
    if table:
        return [TelemetryStore(ctx.db).get_trace_table(table)], None
    if not prefix:
        raise UserFacingError("Give prefix (e.g. 'shop_', all tables of a system) or table (one trace table).")
    found = tables_with_prefix(ctx, prefix)
    if not found.traces:
        raise UserFacingError(
            f"No trace table name starts with '{found.prefix}' (its tables: {', '.join(found.names)}). "
            "Set one up with setup_trace_table."
        )
    return found.traces, found


def _spans_sql(tables: list[TraceTable]) -> str:
    cols = "trace_id, span_id, parent_span_id, service, operation, start_us, duration_us, status, self_time_us"
    return " UNION ALL ".join(f"SELECT {cols} FROM {t.relation}" for t in tables)


def _filter(services: list[str] | None, operations: list[str] | None, params: dict[str, Any], alias: str = "") -> str:
    out = ""
    a = f"{alias}." if alias else ""
    if services:
        params["services"] = list(services)
        out += f" AND {a}service = ANY(%(services)s)"
    if operations:
        params["operations"] = list(operations)
        out += f" AND {a}operation = ANY(%(operations)s)"
    return out


# ------------------------------------------------------------------ trace_changes


@dataclass
class OpRow:
    service: str
    operation: str
    self_change: Change
    p95_before: float | None
    p95_after: float | None
    dur_before: float | None
    dur_after: float | None
    errors: str
    error_shift: float | None
    volume: Change
    slowest: list[str]

    def line(self) -> str:
        c, v = self.self_change, self.volume
        parts = [
            f"self p50 {_ms(c.median_before)} -> {_ms(c.median_after)} ms, {_z(c)} (n {c.n_before}/{c.n_after})",
            f"self p95 {_ms(self.p95_before)} -> {_ms(self.p95_after)} ms",
            f"duration p50 {_ms(self.dur_before)} -> {_ms(self.dur_after)} ms",
            self.errors,
            f"volume {_count(v.median_before)} -> {_count(v.median_after)} spans/min, {_z(v)}",
        ]
        if self.slowest:
            parts.append("slowest after: " + ", ".join(self.slowest))
        return f"  {self.service} {self.operation}: " + "; ".join(parts)


def _count(v: float | None) -> str:
    return "?" if v is None else f"{v:.1f}"


def _volume(per_minute: dict[int, int], before_buckets: int, after_buckets: int, ext: Extent, pivot_us: int) -> Change:
    # Minutes the data does not cover are unknown, not zero spans: they are left out.
    def known(b: int) -> bool:
        return minute_covered(ext, pivot_us + b * 60_000_000)

    before = [per_minute.get(b, 0) for b in range(-before_buckets, 0) if known(b)]
    after = [per_minute.get(b, 0) for b in range(0, after_buckets) if known(b)]
    if not before or not after:
        return change(None, None, None, len(before), None, len(after))
    med_b = statistics.median(before)
    mad_b = statistics.median(abs(x - med_b) for x in before)
    std_b = statistics.stdev(before) if len(before) > 1 else 0.0
    return change(med_b, mad_b, std_b, len(before), statistics.median(after), len(after), max(after))


def _ops(ctx: AppContext, spans: str, w: Window, flt: str, params: dict[str, Any], ext: Extent) -> list[OpRow]:
    params = {**params, "a": w.start_us, "p": w.pivot_us, "b": w.end_us}
    base = (
        f"SELECT service, operation, trace_id, self_time_us AS x, duration_us AS d, status, start_us, "
        f"start_us >= %(p)s AS aft FROM ({spans}) s WHERE start_us >= %(a)s AND start_us < %(b)s{flt}"
    )
    rows = ctx.db.read(
        f"""SELECT service, operation,
  count(*) FILTER (WHERE NOT aft) AS n_b, count(*) FILTER (WHERE aft) AS n_a,
  CAST(median(x) FILTER (WHERE NOT aft) AS DOUBLE) AS med_b, CAST(mad(x) FILTER (WHERE NOT aft) AS DOUBLE) AS mad_b,
  stddev_samp(x) FILTER (WHERE NOT aft) AS sd_b, CAST(median(x) FILTER (WHERE aft) AS DOUBLE) AS med_a,
  quantile_cont(x, 0.95) FILTER (WHERE NOT aft) AS p95_b, quantile_cont(x, 0.95) FILTER (WHERE aft) AS p95_a,
  CAST(median(d) FILTER (WHERE NOT aft) AS DOUBLE) AS dur_b, CAST(median(d) FILTER (WHERE aft) AS DOUBLE) AS dur_a,
  count(status) FILTER (WHERE NOT aft) AS k_b, count(status) FILTER (WHERE aft) AS k_a,
  count(*) FILTER (WHERE NOT aft AND status = 'error') AS e_b, count(*) FILTER (WHERE aft AND status = 'error') AS e_a,
  (list(trace_id ORDER BY x DESC) FILTER (WHERE aft))[1:3] AS slowest
FROM ({base}) t GROUP BY service, operation""",
        params,
        what="comparing span self times before and after the pivot",
    ).dicts()
    minutes = ctx.db.read(
        f"SELECT service, operation, CAST(floor((start_us - %(p)s) / 60000000.0) AS BIGINT) AS m, count(*) AS n "
        f"FROM ({base}) t GROUP BY service, operation, m",
        params,
        what="counting spans per minute",
    ).rows
    per: dict[tuple[str, str], dict[int, int]] = {}
    for svc, op, m, n in minutes:
        per.setdefault((svc, op), {})[int(m)] = int(n)
    before_buckets = int((w.pivot_us - w.start_us) // 60_000_000)
    after_buckets = int((w.end_us - w.pivot_us) // 60_000_000)
    out = []
    for r in rows:
        c = change(_f(r["med_b"]), _f(r["mad_b"]), _f(r["sd_b"]), r["n_b"], _f(r["med_a"]), r["n_a"], _f(r["p95_a"]))
        kb, ka, eb, ea = int(r["k_b"]), int(r["k_a"]), int(r["e_b"]), int(r["e_a"])
        shift = (ea / ka - eb / kb) if kb and ka else None
        out.append(
            OpRow(
                str(r["service"]), str(r["operation"]), c, _f(r["p95_b"]), _f(r["p95_a"]), _f(r["dur_b"]),
                _f(r["dur_a"]), _errors(eb, kb, ea, ka, int(r["n_b"]), int(r["n_a"])), shift,
                _volume(per.get((r["service"], r["operation"]), {}), before_buckets, after_buckets, ext, w.pivot_us),
                [str(t) for t in (r["slowest"] or [])],
            )
        )
    return out


@dataclass
class EdgeRow:
    caller: str
    callee: str
    latency: Change
    network: Change
    errors: str

    def line(self) -> str:
        lat, net = self.latency, self.network
        net_text = (
            f"network time p50 {_ms(net.median_before)} -> {_ms(net.median_after)} ms, {_z(net)} "
            f"(n {net.n_before}/{net.n_after})"
            if net.n_before or net.n_after
            else "network time not measured (no caller span with exactly one child)"
        )
        return (
            f"  {self.caller} -> {self.callee}: calls {lat.n_before}/{lat.n_after}; "
            f"call latency p50 {_ms(lat.median_before)} -> {_ms(lat.median_after)} ms, {_z(lat)}; {net_text}; {self.errors}"
        )

    @property
    def size(self) -> float:
        return max(self.latency.size, self.network.size)


def _edges(
    ctx: AppContext, spans: str, w: Window, services: list[str] | None, operations: list[str] | None
) -> list[EdgeRow]:
    params: dict[str, Any] = {"a": w.start_us, "p": w.pivot_us, "b": w.end_us}
    flt = ""
    if services:
        params["services"] = list(services)
        flt += " AND (p.service = ANY(%(services)s) OR c.service = ANY(%(services)s))"
    if operations:
        params["operations"] = list(operations)
        flt += " AND (p.operation = ANY(%(operations)s) OR c.operation = ANY(%(operations)s))"
    sql = f"""
WITH s AS ({spans}),
c AS (SELECT * FROM s WHERE start_us >= %(a)s AND start_us < %(b)s AND parent_span_id IS NOT NULL),
kids AS (
  SELECT trace_id, parent_span_id, count(*) AS n FROM s
  WHERE parent_span_id IS NOT NULL AND trace_id IN (SELECT trace_id FROM c)
  GROUP BY trace_id, parent_span_id
),
e AS (
  SELECT p.service AS caller, c.service AS callee, c.duration_us AS lat,
    CASE WHEN k.n = 1 THEN p.duration_us - c.duration_us END AS net, c.status, c.start_us >= %(p)s AS aft
  FROM c JOIN s p ON p.trace_id = c.trace_id AND p.span_id = c.parent_span_id
  JOIN kids k ON k.trace_id = p.trace_id AND k.parent_span_id = p.span_id
  WHERE p.service <> c.service{flt}
)
SELECT caller, callee,
  count(*) FILTER (WHERE NOT aft) AS n_b, count(*) FILTER (WHERE aft) AS n_a,
  CAST(median(lat) FILTER (WHERE NOT aft) AS DOUBLE) AS lat_b, CAST(mad(lat) FILTER (WHERE NOT aft) AS DOUBLE) AS lat_mad,
  stddev_samp(lat) FILTER (WHERE NOT aft) AS lat_sd, CAST(median(lat) FILTER (WHERE aft) AS DOUBLE) AS lat_a,
  max(lat) FILTER (WHERE aft) AS lat_peak,
  count(net) FILTER (WHERE NOT aft) AS nn_b, count(net) FILTER (WHERE aft) AS nn_a,
  CAST(median(net) FILTER (WHERE NOT aft) AS DOUBLE) AS net_b, CAST(mad(net) FILTER (WHERE NOT aft) AS DOUBLE) AS net_mad,
  stddev_samp(net) FILTER (WHERE NOT aft) AS net_sd, CAST(median(net) FILTER (WHERE aft) AS DOUBLE) AS net_a,
  max(net) FILTER (WHERE aft) AS net_peak,
  count(status) FILTER (WHERE NOT aft) AS k_b, count(status) FILTER (WHERE aft) AS k_a,
  count(*) FILTER (WHERE NOT aft AND status = 'error') AS e_b, count(*) FILTER (WHERE aft AND status = 'error') AS e_a
FROM e GROUP BY caller, callee"""
    rows = ctx.db.read(sql, params, what="comparing calls between services before and after the pivot").dicts()
    out = []
    for r in rows:
        lat = change(_f(r["lat_b"]), _f(r["lat_mad"]), _f(r["lat_sd"]), r["n_b"], _f(r["lat_a"]), r["n_a"], _f(r["lat_peak"]))
        net = change(
            _f(r["net_b"]), _f(r["net_mad"]), _f(r["net_sd"]), r["nn_b"], _f(r["net_a"]), r["nn_a"], _f(r["net_peak"])
        )
        errs = _errors(int(r["e_b"]), int(r["k_b"]), int(r["e_a"]), int(r["k_a"]), int(r["n_b"]), int(r["n_a"]))
        out.append(EdgeRow(str(r["caller"]), str(r["callee"]), lat, net, errs.replace("errors", "callee errors", 1)))
    return out


def _op_key(sort: str):  # type: ignore[no-untyped-def]
    if sort == "errors":
        return lambda o: (o.error_shift is None, -abs(o.error_shift or 0.0), -o.self_change.size)
    if sort == "volume":
        return lambda o: (-o.volume.size, -o.self_change.size)
    return lambda o: (-o.self_change.size, -o.volume.size)


def trace_changes(
    ctx: AppContext,
    pivot: str,
    prefix: str | None = None,
    table: str | None = None,
    before_minutes: float = 10,
    after_minutes: float = 10,
    services: list[str] | None = None,
    operations: list[str] | None = None,
    sort: str = "self_time",
    top: int = 20,
    timezone: str | None = None,
) -> str:
    if sort not in SORTS:
        raise UserFacingError(f"sort must be one of {', '.join(SORTS)}; got '{sort}'.")
    limit = fmt.clamp_limit(top, 20, MAX_TOP)
    w = parse_window(pivot, before_minutes, after_minutes, timezone)
    tables, found = _trace_tables(ctx, prefix, table)
    spans = _spans_sql(tables)
    params: dict[str, Any] = {}
    flt = _filter(services, operations, params)
    ext = extent(ctx, f"({spans}) s", "start_us")
    note = window_note(", ".join(t.name for t in tables), ext, w)
    ops = _ops(ctx, spans, w, flt, params, ext)
    edges = _edges(ctx, spans, w, services, operations)

    filters = []
    if services:
        filters.append(f"services {', '.join(services)}")
    if operations:
        filters.append(f"operations {', '.join(operations)}")
    lines = [
        fmt.how_measured(
            "every span in the window, per service and operation and per call between services",
            period=w.describe(),
            filters="; ".join(filters) or None,
        ),
        f"Trace changes in {', '.join(t.name for t in tables)} around the pivot {fmt_us(w.pivot_us)} UTC "
        f"({before_minutes:g} min before, {after_minutes:g} min after; the 10/10 default is RCAEval's window).",
        f"statistic: {STATISTIC}. Self time = span duration minus the time its child spans cover. "
        "Volume z uses spans per whole minute the data covers. Error rate counts only spans with a status; NULL status is unknown.",
        *([note] if note else []),
        "",
    ]
    ranked = [o for o in ops if o.self_change.kind in ("z", "unchanged")]
    ranked.sort(key=_op_key(sort))
    shown, more = fmt.cut(ranked, limit, "operations")
    label = {"self_time": "self-time change (|z|)", "errors": "error-rate change", "volume": "volume change (|z|)"}[sort]
    lines.append(f"operations by {label}" + (f" ({more})" if more else "") + ":")
    lines += [o.line() for o in shown] or ["  none in the window"]
    lines.append("")
    rose = [o for o in ops if o.self_change.kind == "rose_from_zero"]
    lines.append("self time rose from zero (not ranked by z):" + ("" if rose else " none"))
    lines += [o.line() for o in rose]
    thin = [o for o in ops if o.self_change.kind == "too_little_data"]
    if thin:
        lines.append(f"too little data (fewer than {MIN_POINTS} spans on a side):")
        lines += [o.line() for o in thin[:limit]]
        if len(thin) > limit:
            lines.append(f"  … and {len(thin) - limit} more")
    lines.append("")

    edges.sort(key=lambda e: -e.size)
    shown_e, more_e = fmt.cut(edges, limit, "edges")
    lines.append(
        "edges (caller -> callee: the callee's span is a child of a caller's span; call latency = callee span "
        "duration; network time = caller span minus callee span where the caller span has exactly one child), "
        "by the larger |z|" + (f" ({more_e})" if more_e else "") + ":"
    )
    lines += [e.line() for e in shown_e] or ["  none (no parent and child spans in different services)"]
    lines.append("")

    if found is not None:
        lines += coverage_lines(services_by_source(ctx, found))
    else:
        svc = sorted({o.service for o in ops})
        lines.append(
            "coverage: only this trace table was read (pass prefix to see logs and metrics too); services with "
            "spans in the window: " + (", ".join(svc) if svc else "none")
        )
    return "\n".join(lines)


# ------------------------------------------------------------------ get_trace


def get_trace(ctx: AppContext, table: str, trace_id: str) -> str:
    tt = TelemetryStore(ctx.db).get_trace_table(table)
    rows = ctx.db.read(
        f"SELECT span_id, parent_span_id, service, operation, start_us, duration_us, self_time_us, status "
        f"FROM {tt.relation} WHERE trace_id = %(t)s ORDER BY start_us, span_id LIMIT {MAX_TRACE_SPANS + 1}",
        {"t": trace_id},
        what=f"reading trace {trace_id}",
    ).dicts()
    head = fmt.how_measured(f"every span of trace {trace_id} in {table}")
    if not rows:
        return f"{head}\nTrace {trace_id} has no spans in {table}."
    cut = len(rows) > MAX_TRACE_SPANS
    rows = rows[:MAX_TRACE_SPANS]
    ids = {r["span_id"] for r in rows}
    children: dict[str, list[dict[str, Any]]] = {}
    roots = []
    for r in rows:
        if r["parent_span_id"] is not None and r["parent_span_id"] in ids and r["parent_span_id"] != r["span_id"]:
            children.setdefault(r["parent_span_id"], []).append(r)
        else:
            roots.append(r)
    t0 = min(int(r["start_us"]) for r in rows)
    lines = [
        head,
        f"Trace {trace_id} in {table}: {len(rows)} spans, starting {fmt_us(t0)} UTC. "
        "Each line: service operation, start offset from the trace's first span, duration, self time, status.",
    ]
    seen: set[str] = set()

    def walk(r: dict[str, Any], depth: int) -> None:
        if r["span_id"] in seen:
            return
        seen.add(r["span_id"])
        orphan = " (parent span not in the trace)" if depth == 0 and r["parent_span_id"] is not None else ""
        lines.append(
            f"{'  ' * depth}{r['service']} {r['operation']}  start +{_ms(int(r['start_us']) - t0)} ms  "
            f"duration {_ms(float(r['duration_us']))} ms  self {_ms(float(r['self_time_us']))} ms  "
            f"status {r['status'] or 'unknown'}{orphan}"
        )
        for c in children.get(r["span_id"], []):
            walk(c, depth + 1)

    for r in roots:
        walk(r, 0)
    for r in rows:  # spans in a parent cycle are never reached from a root
        if r["span_id"] not in seen:
            walk(r, 0)
    if cut:
        lines.append(f"showing the first {MAX_TRACE_SPANS} spans by start time; the trace has more")
    return "\n".join(lines)


_trace_changes = trace_changes
_get_trace = get_trace


def register(mcp: Any, runner: Any) -> None:
    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def trace_changes(
        pivot: str,
        prefix: str | None = None,
        table: str | None = None,
        before_minutes: float = 10,
        after_minutes: float = 10,
        services: list[str] | None = None,
        operations: list[str] | None = None,
        sort: str = "self_time",
        top: int = 20,
        timezone: str | None = None,
    ) -> str:
        """Compare spans before and after a time (the pivot): what changed per service and operation, and per call between services. Reports changes; it does not name a cause.
        Use when: an incident time is known and the system has a trace table; to see which operations got slower in their own code (self time), started failing, or changed volume, and which calls between services got slower in the callee or on the network. For a short incident (shorter than half the after-window) the medians barely move: use sort="volume" or a shorter after_minutes.
        Inputs: pivot (ISO time); prefix (e.g. 'shop_', every trace table of a system, adds coverage of logs and metrics) or table (one trace table); before_minutes and after_minutes (default 10 each); services and operations to filter; sort: self_time (default), errors or volume; top (default 20); timezone for a pivot without an offset (default UTC).
        Returns: per (service, operation): self-time p50 before -> after with a robust z, self p95, duration p50, error rate before -> after ('unknown' when spans have no status), spans per minute with a z, and up to 3 slowest trace ids after the pivot; a 'rose from zero' group; per edge (caller -> callee): call latency, network time and callee errors before -> after with z; coverage per service."""
        return await runner.run_tool(
            _trace_changes,
            pivot=pivot,
            prefix=prefix,
            table=table,
            before_minutes=before_minutes,
            after_minutes=after_minutes,
            services=services,
            operations=operations,
            sort=sort,
            top=top,
            timezone=timezone,
        )

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def get_trace(table: str, trace_id: str) -> str:
        """Show one trace as an indented span tree.
        Use when: trace_changes named a slow or failing trace id and you want to see where its time went.
        Inputs: table (a trace table); trace_id.
        Returns: each span with service, operation, start offset in ms from the trace's first span, duration ms, self time ms and status ('unknown' when absent), children indented under their parent."""
        return await runner.run_tool(_get_trace, table=table, trace_id=trace_id)
