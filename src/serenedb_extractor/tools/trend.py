"""trend: chosen templates (or the catalog's top ones) over a period against the preceding period of
equal length, per hour or day. Estimated from a block sample by default, exact on request; both go
through the cost check. A comparison is only made where the data covers both periods, and nothing is
called new, or risen without limit, because data is missing."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from serenedb_extractor import format as fmt
from serenedb_extractor.catalog.models import LogTable, Template
from serenedb_extractor.context import AppContext
from serenedb_extractor.errors import UserFacingError
from serenedb_extractor.query import cost, sampling
from serenedb_extractor.query.filters import (
    FILTER_ROLES,
    DataRange,
    Filters,
    ScanTooExpensive,
    TimeRange,
    build_where,
    data_range,
    parse_time_range,
    role_sql,
    time_clause,
)
from serenedb_extractor.query.stats import collect, role_columns
from serenedb_extractor.setup.paths import sql_literal
from serenedb_extractor.setup.roles import is_temporal, resolve_column, role_column
from serenedb_extractor.setup.sniff import readable
from serenedb_extractor.templating.regex import compile_template
from serenedb_extractor.timezones import get_zone
from serenedb_extractor.tools.describe import known_columns, like_pattern

BUCKETS = {"hour": timedelta(hours=1), "day": timedelta(days=1)}
DEFAULT_TOP_N = 10
MIN_BUCKET_SAMPLE = 2000  # entries sampled per bucket, at least (spec: max(2000, sample_size / buckets))
MAX_BUCKETS = 1000  # across both periods; more would make an unreadable answer
SHOWN_COMPONENTS = 5
SERIES_NUMBERS_MAX = 31
_BARS = "▁▂▃▄▅▆▇█"
NARROW = "narrow it: a shorter period (start/end), fewer templates, or filters such as level or service."
NEED_PERIOD = (
    "Which period should I use? trend compares a period with the one before it, so it needs both start and end, "
    "for example start='2026-03-15', end='2026-03-29' (the end is exclusive)."
)


@dataclass(frozen=True)
class Coverage:
    status: str  # "full" | "partial" | "none" | "unknown"
    why: str = ""


def _buckets(start: datetime, end: datetime, zone: Any, bucket: str) -> list[datetime]:
    """The local (naive) bucket starts that overlap [start, end)."""
    lo = start.astimezone(zone).replace(tzinfo=None, minute=0, second=0, microsecond=0)
    if bucket == "day":
        lo = lo.replace(hour=0)
    hi = end.astimezone(zone).replace(tzinfo=None)
    out = []
    while lo < hi:
        out.append(lo)
        lo += BUCKETS[bucket]
    return out


def _coverage(rng: DataRange | None, checked: bool, a: datetime, b: datetime, step: timedelta, tr: TimeRange, what: str) -> Coverage:
    """Does the data's span cover [a, b)? The last bucket may be only partly filled, so the data's last
    entry may fall up to one bucket before `b`."""
    if not checked:
        return Coverage("unknown", f"whether the data covers {what} was not checked (reading the time range was too expensive)")
    if rng is None:
        return Coverage("none", f"the log table has no timestamps to cover {what}")
    span = f"the data covers {tr.fmt(rng.first)} to {tr.fmt(rng.last)} {tr.tz}"
    if rng.last < a or rng.first >= b:
        return Coverage("none", f"{span}, nothing of {what}")
    if rng.first <= a and rng.last >= b - step:
        return Coverage("full")
    return Coverage("partial", f"{span}, only part of {what}")


def _ts_local(lt: LogTable, cols: dict[str, str], tz: str) -> str:
    """The timestamp as a naive local time in `tz` (an expression for SELECT, never for a WHERE)."""
    expr = role_sql(lt, "timestamp")
    typ = cols.get(role_column(lt.roles.timestamp or "") or "", "").upper()
    naive = is_temporal(typ) and "WITH TIME ZONE" not in typ and not typ.startswith("TIMESTAMPTZ")
    zone = sql_literal(tz)
    if naive:
        return f"((({expr}) AT TIME ZONE {sql_literal(lt.timezone)}) AT TIME ZONE {zone})"
    return f"((({expr})::timestamptz) AT TIME ZONE {zone})"


def _columns_read(lt: LogTable, f: Filters, cols: dict[str, str]) -> list[str]:
    out: list[str] = []
    for role in ["timestamp", "message", *(["component"] if lt.roles.component else [])]:
        out += role_columns(getattr(lt.roles, role))
    for key, _ in f.items():
        if key in FILTER_ROLES:
            out += role_columns(getattr(lt.roles, key))
        elif (c := resolve_column(key, cols)):
            out.append(c)
    return out


def _fixed_like(i: int, t: Template, msg: str, params: dict[str, Any]) -> list[str]:
    like = []
    for j, w in enumerate(compile_template(t.template).fixed_words):
        params[f"fw_{i}_{j}"] = like_pattern(w)
        like.append(f"{msg} LIKE %(fw_{i}_{j})s ESCAPE '\\'")
    return like


def _classify(templates: list[Template], msg: str, params: dict[str, Any]) -> tuple[str, str | None]:
    """CASE giving the 1-based position of the first matching template (ID order), and a prefilter
    (fixed words of any template, on `msg`) or None when some template has no fixed word."""
    whens, pre = [], []
    for i, t in enumerate(templates, 1):
        like = _fixed_like(i, t, "msg", params)
        params[f"rx_{i}"] = t.regex
        whens.append(f"WHEN {' AND '.join([*like, f'regexp_full_match(msg, %(rx_{i})s)'])} THEN {i}")
        pre.append(" AND ".join(_fixed_like(i, t, msg, params)))
    prefilter = None if "" in pre else "(" + " OR ".join(f"({p})" for p in pre) + ")"
    return "CASE " + " ".join(whens) + " END", prefilter


def _run_sql(
    lt: LogTable,
    cols: dict[str, str],
    tr_all: TimeRange,
    cur_start: datetime,
    f: Filters,
    templates: list[Template],
    plan: cost.Plan,
    bucket: str,
    tz: str,
) -> tuple[str, dict[str, Any]]:
    """Rows of (bucket, in current period, [block,] component, template position, entries)."""
    where, params = build_where(lt, tr_all, f, cols)
    cur_sql, cur_params = time_clause(lt, TimeRange(start=cur_start), cols, prefix="c")
    params.update(cur_params)
    msg = f"coalesce(({role_sql(lt, 'message')})::varchar, '')"
    case, prefilter = _classify(templates, msg, params)
    comp = f"({role_sql(lt, 'component')})::varchar" if lt.roles.component else "NULL::varchar"
    block = f"{sampling.block_id_sql(plan)} AS b, " if plan.sampling else ""
    if plan.sampling:
        where += " AND " + sampling.clause(plan)
    elif prefilter:  # a sample keeps every entry: the ratio needs the entries that match nothing too
        where += " AND " + prefilter
    inner = (
        f"SELECT date_trunc('{bucket}', {_ts_local(lt, cols, tz)}) AS bucket, "
        f"CASE WHEN {cur_sql} THEN 1 ELSE 0 END AS p, {block}{comp} AS comp, {msg} AS msg "
        f"FROM {lt.relation} WHERE {where}"
    )
    keys = "bucket, p, " + ("b, " if plan.sampling else "") + "comp"
    sql = (
        f"SELECT {keys}, k, count(*) AS n FROM (SELECT {keys}, {case} AS k FROM ({inner})) "
        + ("" if plan.sampling else "WHERE k IS NOT NULL ")
        + f"GROUP BY {keys}, k"
    )
    return sql, params


@dataclass
class Series:
    """One template's counts. `blocks` (block sample only): per period and per bucket, the sampled
    blocks' (entries in scope, hits)."""

    hits: dict[tuple[int, datetime], int]
    comps: dict[str, int]


def _gather(rows: list[Any], sampled: bool, n_templates: int) -> tuple[list[Series], dict[Any, int], dict[Any, int]]:
    """From result rows: per template the hits per (period, bucket) and components of the current
    period; and, for a block sample, the entries per (period, bucket, block) and the hits per
    (template, period, bucket, block)."""
    series = [Series({}, {}) for _ in range(n_templates)]
    entries: dict[Any, int] = defaultdict(int)
    block_hits: dict[Any, int] = defaultdict(int)
    for r in rows:
        if sampled:
            bucket, p, b, comp, k, n = r
        else:
            bucket, p, comp, k, n = r
            b = 0
        n = int(n)
        entries[(p, bucket, b)] += n
        if k is None:
            continue
        s = series[int(k) - 1]
        s.hits[(p, bucket)] = s.hits.get((p, bucket), 0) + n
        block_hits[(int(k) - 1, p, bucket, b)] += n
        if p == 1:
            s.comps[comp if comp is not None else "(none)"] = s.comps.get(comp if comp is not None else "(none)", 0) + n
    return series, entries, block_hits


def _unsampled(m: fmt.Measured) -> bool:
    """An estimate for a bucket that no sampled block overlaps says nothing, not zero."""
    return not m.exact and not m.sample_size


def _spark(ms: list[fmt.Measured]) -> str:
    top = max((m.value for m in ms), default=0)
    out = []
    for m in ms:
        if _unsampled(m):
            out.append("·")
        elif top <= 0 or m.value <= 0:
            out.append(_BARS[0])
        else:
            out.append(_BARS[min(len(_BARS) - 1, int(m.value / top * (len(_BARS) - 1) + 0.5))])
    return "".join(out)


def _show(m: fmt.Measured) -> str:
    if not m.exact and (m.hits or 0) == 0:
        return "none in the sample (a rare template can be missed by a sample)"
    return fmt.render(m)


def _reliable(m: fmt.Measured) -> bool:
    return m.exact or (m.hits or 0) >= fmt.MIN_HITS


def _change(cur: fmt.Measured, prev: fmt.Measured, prev_cover: Coverage, cur_cover: Coverage) -> str:
    if prev_cover.status != "full" or cur_cover.status != "full":
        return "not given (limited comparison)"
    if (prev.exact and prev.value == 0) or (not prev.exact and (prev.hits or 0) == 0):
        if not prev.exact:
            return "not given: the preceding period's sample held none, and an estimate can't show that it had none"
        if cur.value == 0:
            return "none in either period"
        return "new in this period: none in the preceding period, which the data covers in full"
    if not (_reliable(cur) and _reliable(prev)):
        return "not given: too few sampled hits in one of the periods"
    if cur.exact and cur.value == 0:
        return "-100%"
    pct_change = (cur.value - prev.value) / prev.value * 100
    text = "no change" if round(pct_change) == 0 else f"{pct_change:+.0f}%"
    return text if cur.exact and prev.exact else f"≈{text} (from the two estimates above)"


def _filters_text(f: Filters) -> str | None:
    parts = []
    for key, wanted in f.items():
        parts.append(f"{key} in ({', '.join(repr(w) for w in wanted)})" if isinstance(wanted, list) else f"{key}={wanted!r}")
    return ", ".join(parts) or None


def _tmpl_number(t: Template) -> int:
    return int(t.template_id[1:]) if t.template_id[1:].isdigit() else 0


def _choose(ctx: AppContext, lt: LogTable, templates: list[str] | None, top_n: int | None) -> tuple[list[Template], list[str]]:
    notes: list[str] = []
    if templates:
        chosen: dict[str, Template] = {}
        for given in templates:
            r = ctx.store.resolve(lt.name, given)
            chosen.setdefault(r.template.template_id, r.template)
            if r.redirected_from:
                notes.append(f"{r.redirected_from} was merged into {r.template.template_id}; used that one.")
        return sorted(chosen.values(), key=_tmpl_number), notes
    every = ctx.store.templates(lt.name)
    if not every:
        raise UserFacingError(f"Log table '{lt.name}' has no templates in the catalog yet: run survey first, or name templates.")
    ranked = sorted(every, key=lambda t: (-(t.last_estimate or 0), _tmpl_number(t)))
    shown, note = fmt.cut(ranked, fmt.clamp_limit(top_n, DEFAULT_TOP_N, DEFAULT_TOP_N * ctx.settings.limit_cap), "templates")
    if note:
        notes.append(note + " in the catalog (largest by their last estimate)")
    return sorted(shown, key=_tmpl_number), notes


def trend(
    ctx: AppContext,
    log_table: str,
    templates: list[str] | None = None,
    start: str | None = None,
    end: str | None = None,
    bucket: str = "day",
    exact: bool = False,
    filters: dict[str, Any] | None = None,
    top_n: int | None = None,
    timezone: str = "UTC",
    confirmed_cost: str | None = None,
) -> str:
    lt = ctx.store.get_log_table(log_table)
    if bucket not in BUCKETS:
        raise UserFacingError(f"bucket must be 'hour' or 'day', not '{bucket}'.")
    if not start or not end:
        raise UserFacingError(NEED_PERIOD)
    if lt.roles.timestamp is None:
        raise UserFacingError(f"Log table '{lt.name}' has no timestamp field, so there is nothing to trend over time.")
    cur = parse_time_range(start, end, timezone)
    assert cur.start is not None and cur.end is not None
    span = cur.end - cur.start
    prev_start = cur.start - span
    prev = TimeRange(prev_start, cur.start, timezone)
    tr_all = TimeRange(prev_start, cur.end, timezone)
    zone = get_zone(timezone)
    cur_buckets = _buckets(cur.start, cur.end, zone, bucket)
    prev_buckets = _buckets(prev_start, cur.start, zone, bucket)
    if len(cur_buckets) + len(prev_buckets) > MAX_BUCKETS:
        raise UserFacingError(
            f"That period has {len(cur_buckets) + len(prev_buckets)} {bucket}s across both periods (at most {MAX_BUCKETS}): "
            "use a shorter period or bigger buckets."
        )
    chosen, notes = _choose(ctx, lt, templates, top_n)
    f = Filters.from_dict(filters)
    db = ctx.db
    unit = bucket
    with readable(f"the source of log table '{lt.name}'"):
        cols = known_columns(db, lt)
        try:
            rng, checked = data_range(db, lt, cols), True
        except ScanTooExpensive:
            rng, checked = None, False
        step = BUCKETS[bucket]
        cur_cover = _coverage(rng, checked, cur.start, cur.end, step, cur, "this period")
        prev_cover = _coverage(rng, checked, prev_start, cur.start, step, cur, "the preceding period")
        stats = collect(db, lt, tr_all)
        n_buckets = len(cur_buckets) + len(prev_buckets)
        per_bucket = max(MIN_BUCKET_SAMPLE, ctx.settings.sample_size // max(n_buckets, 1))
        decision = cost.decide(
            stats, _columns_read(lt, f, cols), exact, per_bucket * n_buckets, confirmed_cost, max_s=ctx.settings.max_timeout_s
        )
        if decision.status == "ask":
            head = fmt.how_measured(cost.ASKED_HOW, tr_all.describe(), _filters_text(f), tz=timezone)
            return head + "\n" + decision.message
        plan = decision.plan
        sql, params = _run_sql(lt, cols, tr_all, cur.start, f, chosen, plan, bucket, timezone)
        timeout = cost.run_timeout(plan, ctx.settings.default_timeout_s, ctx.settings.max_timeout_s)
        rows = db.read(sql, params, timeout_s=timeout, what=f"counting trends in {lt.name}", how_to_narrow=NARROW).rows
    series, entries, block_hits = _gather(rows, bool(plan.sampling), len(chosen))
    sampled_blocks = range(len(plan.groups)) if plan.sampling else range(1)

    def measure(i: int, p: int, buckets: list[datetime]) -> fmt.Measured:
        """The template's count over the given buckets of period p (1 = current)."""
        if not plan.sampling:
            return fmt.Measured(float(sum(series[i].hits.get((p, b), 0) for b in buckets)), True)
        blocks = []
        for blk in sampled_blocks:
            n = sum(entries.get((p, b, blk), 0) for b in buckets)
            if n:
                blocks.append((n, sum(block_hits.get((i, p, b, blk), 0) for b in buckets)))
        return sampling.block_estimate(blocks, plan.fraction)

    limited = [c.why for c in (prev_cover, cur_cover) if c.status != "full"]
    out = [_head(lt, cur, prev, f, plan, timezone, bucket)]
    out += [n if n.startswith('showing') else fmt.sentence(n) for n in [*plan.notes, *notes]]
    if len(chosen) > 1:
        out.append("Templates that overlap: an entry that matches several is counted once, under the one with the lowest ID.")
    if limited:
        out.append("limited comparison: " + "; ".join(limited) + ". Counts are shown; no change is given where a period is not fully covered.")
    out.append(f"Each period is split into {unit}s in {timezone}: this period has {len(cur_buckets)}, the preceding one {len(prev_buckets)}.")
    for i, t in enumerate(chosen):
        now, before = measure(i, 1, cur_buckets), measure(i, 0, prev_buckets)
        per_now = [measure(i, 1, [b]) for b in cur_buckets]
        per_before = [measure(i, 0, [b]) for b in prev_buckets]
        present = sum(1 for m in per_now if m.value > 0)
        out += ["", f"{t.template_id}  {t.template}"]
        out.append(f"    this period: {_show(now)}; preceding period: {_show(before)}")
        out.append(f"    change: {_change(now, before, prev_cover, cur_cover)}")
        late = ""
        if not plan.exact:
            blind = sum(1 for m in per_now if _unsampled(m))
            late = f" in the sample (a {unit} with no sampled entry may still have some; {blind} had no sampled entries at all)"
        out.append(f"    present in {present} of {len(cur_buckets)} {unit}s{late}")
        out.append("    " + _components(series[i], lt, plan))
        out += _series_lines(per_now, per_before, unit, plan.exact)
    return "\n".join(out)


def _components(s: Series, lt: LogTable, plan: cost.Plan) -> str:
    if lt.roles.component is None:
        return "components: this log table has no component field"
    top = sorted(s.comps, key=lambda c: (-s.comps[c], c))
    shown = ", ".join(top[:SHOWN_COMPONENTS]) + (", …" if len(top) > SHOWN_COMPONENTS else "")
    where = "" if plan.exact else " (in the sample)"
    return f"components affected this period{where}: {shown} ({len(top)})" if top else "components affected this period: none"


def _series_lines(now: list[fmt.Measured], before: list[fmt.Measured], unit: str, exact: bool) -> list[str]:
    def one(label: str, ms: list[fmt.Measured]) -> str:
        values = [m.value for m in ms]
        if exact and len(values) <= SERIES_NUMBERS_MAX:
            return f"    {label} by {unit}: " + " ".join(f"{round(v):,}" for v in values)
        shape = "" if exact else " (estimated shape; · = no sampled entries)"
        return f"    {label} by {unit}{shape}: {_spark(ms)}"

    return [one("this period", now), one("preceding period", before)]


def _head(lt: LogTable, cur: TimeRange, prev: TimeRange, f: Filters, plan: cost.Plan, tz: str, bucket: str) -> str:
    if plan.exact:
        kind = (
            f"trend, exact: every entry in both periods was read once and counted per template and {bucket}"
            + (" (run as you confirmed)" if plan.confirmed else "")
        )
        sample = None
    else:
        kind = (
            f"trend, estimated: whole blocks of entries were read and each count scaled up from them; "
            f"counts per {bucket} are rougher than the period totals"
        )
        upto = "" if plan.rows_exact else "up to "
        sample = (
            f"block sample of {plan.sample_rows or 0:,} of {upto}{plan.population_rows:,} entries "
            f"({len(plan.groups)} whole row group{'' if len(plan.groups) == 1 else 's'} overlapping the periods; repeatable)"
        )
    period = f"{cur.describe()} against the preceding period {prev.describe()}"
    return fmt.how_measured(kind, period, _filters_text(f), sample, tz=tz)
