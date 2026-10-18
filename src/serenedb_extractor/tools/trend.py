"""trend: chosen templates (or the catalog's top ones) over a period against the preceding period of
equal length, per hour or day. Exact whenever every entry fits the time budget (or on request), else
estimated from a block sample; both go through the cost check. A comparison is only made where the data covers both periods (R69: when the
current period runs past the data's end, both are cut to the same whole buckets the data covers), and
nothing is called new, or risen without limit, because data is missing."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, tzinfo
from typing import Any, Literal

from serenedb_extractor import format as fmt
from serenedb_extractor.catalog.models import LogTable, Template
from serenedb_extractor.context import AppContext
from serenedb_extractor.ownership import team_of
from serenedb_extractor.errors import UserFacingError
from serenedb_extractor.query import cost, sampling
from serenedb_extractor.query.filters import (
    instant_sql,
    FILTER_ROLES,
    DataRange,
    Filters,
    ScanTooExpensive,
    TimeRange,
    build_where,
    covers_text,
    data_range,
    parse_time_range,
    role_sql,
    shown_zone,
    time_clause,
)
from serenedb_extractor.query.stats import collect, role_columns
from serenedb_extractor.setup.paths import sql_literal
from serenedb_extractor.setup.roles import is_temporal, resolve_column, role_column
from serenedb_extractor.setup.sniff import readable
from serenedb_extractor.query.templatematch import fixed_word_prefilter, fixed_words_sql, template_match_sql
from serenedb_extractor.timezones import get_zone
from serenedb_extractor.query.coverage import untimestamped_note
from serenedb_extractor.tools.describe import known_columns

Bucket = Literal["hour", "day"]
Status = Literal["full", "partial", "none", "unknown"]
HOUR = timedelta(hours=1)
DEFAULT_TOP_N = 10
# The sampler takes ONE block sample over both periods and re-slices it by bucket (R46); it does not
# sample each bucket on its own. Its size is max(sample_size, MIN_BUCKET_SAMPLE * buckets): the server's
# sample size governs scopes with few buckets, and the floor keeps every bucket's share at 2,000
# entries on average when there are many (so with more than 50 buckets the floor is what applies).
MIN_BUCKET_SAMPLE = 2000
EXACT_WITHIN_S = cost.BUDGET_SECONDS  # count every entry by default when the exact read fits this
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
    status: Status
    why: str = ""


def _as_bucket(bucket: str) -> Bucket:
    if bucket == "hour":
        return "hour"
    if bucket == "day":
        return "day"
    raise UserFacingError(f"bucket must be 'hour' or 'day', not '{bucket}'.")


def preceding_start(start: datetime, end: datetime, zone: tzinfo) -> datetime:
    """Start of the preceding period of equal length on the clock in `zone`: the same number of calendar days and
    clock hours, so a period that crosses a daylight-saving change still starts at local midnight (or the same
    local hour) instead of drifting by an hour."""
    a, b = start.astimezone(zone), end.astimezone(zone)
    wall = b.replace(tzinfo=None) - a.replace(tzinfo=None)
    return (a.replace(tzinfo=None) - wall).replace(tzinfo=zone).astimezone(start.tzinfo or UTC)


def _first_hour(start: datetime) -> datetime:
    return start.astimezone(UTC).replace(minute=0, second=0, microsecond=0)


def _count_buckets(start: datetime, end: datetime, zone: tzinfo, bucket: Bucket) -> int:
    """How many buckets overlap [start, end), by arithmetic (no list is built)."""
    if bucket == "hour":
        whole, rest = divmod(end - _first_hour(start), HOUR)
        return whole + (1 if rest else 0)
    first = start.astimezone(zone).date()
    last = (end - timedelta(microseconds=1)).astimezone(zone).date()
    return (last - first).days + 1


def _buckets(start: datetime, end: datetime, zone: tzinfo, bucket: Bucket) -> list[datetime]:
    """The buckets overlapping [start, end), in time order. An hour is a real hour, a UTC-aligned
    instant (aware, UTC), so each instant is in exactly one bucket whatever the zone does with its
    clocks. A day is a local calendar day in `zone` (naive midnight), 23 or 25 hours across a clock change."""
    out: list[datetime] = []
    if bucket == "hour":
        cur = _first_hour(start)
        while cur < end:
            out.append(cur)
            cur += HOUR
        return out
    day = start.astimezone(zone).replace(tzinfo=None, hour=0, minute=0, second=0, microsecond=0)
    last = end.astimezone(zone).replace(tzinfo=None)
    while day < last:
        out.append(day)
        day += timedelta(days=1)
    return out


def _bounds(b: datetime, zone: tzinfo, bucket: Bucket) -> tuple[datetime, datetime]:
    """The real (UTC) interval a bucket covers."""
    if bucket == "hour":
        return b, b + HOUR
    lo = b.replace(tzinfo=zone).astimezone(UTC)
    return lo, (b + timedelta(days=1)).replace(tzinfo=zone).astimezone(UTC)


def _key(raw: datetime, bucket: Bucket) -> datetime:
    """A bucket as SereneDB returns it (a naive datetime) in the form `_buckets` uses."""
    return raw.replace(tzinfo=UTC) if bucket == "hour" else raw


def _label(b: datetime, zone: tzinfo, bucket: Bucket) -> str:
    """A bucket for people: the date for a day; for an hour its start in `zone` with the UTC offset."""
    if bucket == "day":
        return b.strftime("%Y-%m-%d")
    local = b.astimezone(zone)
    off = local.strftime("%z")
    if off == "+0000" and local.tzname() == "UTC":
        return f"{local:%Y-%m-%d %H:%M} UTC"
    return f"{local:%Y-%m-%d %H:%M} UTC{off[:3]}:{off[3:]}"


def _clock_change(buckets: list[datetime], zone: tzinfo, bucket: Bucket) -> list[str]:
    """The local dates on which `zone`'s clocks change inside the buckets."""
    dates: list[str] = []
    prev_offset = None
    for b in buckets:
        lo, hi = _bounds(b, zone, bucket)
        if bucket == "day":
            if hi - lo != timedelta(days=1):
                dates.append(b.strftime("%Y-%m-%d"))
            continue
        offset = lo.astimezone(zone).utcoffset()
        if prev_offset is not None and offset != prev_offset:
            dates.append(lo.astimezone(zone).strftime("%Y-%m-%d"))
        prev_offset = offset
    return dates


def _coverage(rng: DataRange | None, checked: bool, a: datetime, b: datetime, tr: TimeRange, what: str) -> Coverage:
    """Does the data's time range cover all of [a, b)? Only when it starts at or before `a` and runs
    to `b` or beyond: no tolerance for a last bucket that is only partly there."""
    if not checked:
        return Coverage("unknown", f"whether the data covers {what} was not checked (reading the time range was too expensive)")
    if rng is None:
        return Coverage("none", f"the log table has no timestamps to cover {what}")
    span = f"the data covers {tr.fmt(rng.first)} to {tr.fmt(rng.last)} {tr.tz}"
    if rng.last < a or rng.first >= b:
        return Coverage("none", f"{span}, nothing of {what}")
    if rng.first <= a and rng.last >= b:
        return Coverage("full")
    return Coverage("partial", f"{span}, only part of {what}")


def _seen_buckets(
    db: Any, lt: LogTable, cols: dict[str, str], tr_all: TimeRange, cur_start: datetime, unit: Bucket, tz: str,
    timeout: float,
) -> dict[int, set[datetime]] | None:
    """Per period (0 = preceding, 1 = current) the buckets holding at least one entry of any kind, from the
    timestamp column alone; None when even that scan does not fit the cost check."""
    ts_cols = role_columns(lt.roles.timestamp)
    _, decision = cost.check(db, lt, tr_all, ts_cols)
    if decision.status != "run" or not decision.plan.exact:
        return None
    where, params = time_clause(lt, tr_all, cols)
    cur_sql, cur_params = time_clause(lt, TimeRange(start=cur_start), cols, prefix="c")
    rows = db.read(
        f"SELECT DISTINCT date_trunc({sql_literal(unit)}, {_ts_local(lt, cols, 'UTC' if unit == 'hour' else tz)}) AS bucket, "
        f"CASE WHEN {cur_sql} THEN 1 ELSE 0 END AS p FROM {lt.relation} WHERE {where}",
        {**params, **cur_params},
        timeout_s=timeout,
        what=f"checking {lt.name} for gaps",
        how_to_narrow=NARROW,
    ).rows
    out: dict[int, set[datetime]] = {0: set(), 1: set()}
    for raw, p in rows:
        out[int(p)].add(_key(raw, unit))
    return out


# A gap in the data is a run of empty buckets at least this long: one quiet hour is normal for many logs, while
# hours on end (or a whole day) with no entry at all means the logs are missing.
MIN_GAP_RUN = {"hour": 3, "day": 1}


def gap_buckets(buckets: list[datetime], seen: set[datetime], whole: Any, unit: Bucket) -> list[datetime]:
    """The whole buckets that lie in a gap: runs of at least MIN_GAP_RUN consecutive buckets with no entry at all."""
    out: list[datetime] = []
    run: list[datetime] = []
    for b in [*buckets, None]:
        if b is not None and whole(b) and b not in seen:
            run.append(b)
            continue
        if len(run) >= MIN_GAP_RUN[unit]:
            out += run
        run = []
    return out


def _gap_cover(
    cover: Coverage, buckets: list[datetime], seen: set[datetime], whole: Any, unit: Bucket, what: str, zone: Any
) -> Coverage:
    """Downgrade a coverage when the period holds a gap in the data (see MIN_GAP_RUN). A full coverage becomes
    partial (or none); a partial one (the period runs past the data's edge) keeps its reason and also names the
    gaps inside the data's span, which `whole` limits the search to."""
    if cover.status not in ("full", "partial"):
        return cover
    empty = gap_buckets(buckets, seen, whole, unit)
    if not empty:
        return cover
    n, total = len(empty), len(buckets)
    shown = ", ".join(_label(b, zone, unit) for b in empty[:3]) + (", …" if n > 3 else "")
    if cover.status == "partial":
        spanned = sum(1 for b in buckets if whole(b))
        return Coverage(
            "partial",
            f"{cover.why}; and inside the data's span the logs have no entries at all in {n} of the {spanned} whole "
            f"{unit}s ({shown}): a gap in the data",
        )
    if n == total:
        return Coverage("none", f"the logs have no entries at all in {what} (a gap in the data)")
    return Coverage(
        "partial",
        f"the logs have no entries at all in {n} of the {total} {unit}s of {what} ({shown}): a gap in the data, "
        "so it is only partly covered",
    )


def _ts_local(lt: LogTable, cols: dict[str, str], tz: str) -> str:
    """The timestamp as a naive local time in `tz` (an expression for SELECT, never for a WHERE)."""
    expr = role_sql(lt, "timestamp")
    typ = cols.get(role_column(lt.roles.timestamp or "") or "", "").upper()
    naive = is_temporal(typ) and "WITH TIME ZONE" not in typ and not typ.startswith("TIMESTAMPTZ")
    zone = sql_literal(tz)
    if naive:
        return f"((({expr}) AT TIME ZONE {sql_literal(lt.timezone)}) AT TIME ZONE {zone})"
    return f"({instant_sql(expr, typ, lt.timezone)} AT TIME ZONE {zone})"


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


def _classify(templates: list[Template], msg: str, params: dict[str, Any]) -> tuple[str, str | None]:
    """CASE giving the 1-based position of the first matching template (ID order), and the shared
    fixed-word prefilter on `msg`, or None when some template has no fixed word."""
    whens = []
    for i, t in enumerate(templates, 1):
        like = fixed_words_sql(t, "msg", params, f"fw_{i}")
        params[f"rx_{i}"] = t.regex
        whens.append(f"WHEN {' AND '.join([*([like] if like else []), template_match_sql('msg', f'rx_{i}')])} THEN {i}")
    return "CASE " + " ".join(whens) + " END", fixed_word_prefilter(templates, msg, params, "pf")


def _build_sql(
    lt: LogTable,
    cols: dict[str, str],
    tr_all: TimeRange,
    cur_start: datetime,
    f: Filters,
    templates: list[Template],
    plan: cost.Plan,
    bucket: Bucket,
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
        f"SELECT date_trunc({sql_literal(bucket)}, {_ts_local(lt, cols, 'UTC' if bucket == 'hour' else tz)}) AS bucket, "
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
    """One template's entries per (period, bucket) (period 1 = current) and the components of the
    current period with their entries."""

    hits: dict[tuple[int, datetime], int]
    comps: dict[str, int]


def _gather(rows: list[Any], sampled: bool, n_templates: int, bucket: Bucket) -> tuple[list[Series], dict[Any, int], dict[Any, int]]:
    """From result rows: per template the hits per (period, bucket) and components of the current
    period; and, for a block sample, the entries per (period, bucket, block) and the hits per
    (template, period, bucket, block)."""
    series = [Series({}, {}) for _ in range(n_templates)]
    entries: dict[Any, int] = defaultdict(int)
    block_hits: dict[Any, int] = defaultdict(int)
    for r in rows:
        if sampled:
            raw, p, b, comp, k, n = r
        else:
            raw, p, comp, k, n = r
            b = 0
        n = int(n)
        key = _key(raw, bucket)
        entries[(p, key, b)] += n
        if k is None:
            continue
        s = series[int(k) - 1]
        s.hits[(p, key)] = s.hits.get((p, key), 0) + n
        block_hits[(int(k) - 1, p, key, b)] += n
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


def _change(cur: fmt.Measured, prev: fmt.Measured, cur_cover: Coverage, prev_cover: Coverage) -> str:
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
    text = "no change" if round(pct_change) == 0 else pct_text(pct_change)
    return text if cur.exact and prev.exact else f"≈{text} (from the two estimates above)"


def pct_text(pct: float) -> str:
    """A change in percent, never rounded to -100% while something is left (or to +0%/-0% while it changed)."""
    if -100 < pct <= -99.5:
        return f"{max(pct, -99.9):+.1f}%"
    return f"{pct:+.0f}%"


def _amount(m: fmt.Measured) -> str:
    return f"{round(m.value):,}" if m.exact else _show(m)


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


def _top_of_period(
    ctx: AppContext, lt: LogTable, start: str, end: str, filters: dict[str, Any] | None, top_n: int | None, tz: str,
    confirmed_cost: str | None,
) -> tuple[list[Template], list[str]]:
    """The largest templates of this period and these filters, from a survey of them (mapped to the broadest
    template the catalog has for each, as rank_problems does); the catalog's largest when that survey is refused."""
    from serenedb_extractor.catalog.store import covering
    from serenedb_extractor.tools import survey as survey_tool

    n = fmt.clamp_limit(top_n, DEFAULT_TOP_N, DEFAULT_TOP_N * ctx.settings.limit_cap)
    got: list[tuple[Template, fmt.Measured]] = []
    survey_tool.survey(ctx, lt.name, start=start, end=end, filters=filters, limit=1, timezone=tz,
                       confirmed_cost=confirmed_cost, found=got)
    if not got:
        chosen, notes = _choose(ctx, lt, None, top_n)
        return chosen, [*notes, "the period could not be surveyed, so these are the catalog's largest templates overall"]
    catalog = ctx.store.templates(lt.name)
    every: dict[str, Template] = {}
    for t, _ in got:  # largest first
        wide = covering(t, catalog)
        every.setdefault(wide.template_id, wide)
    picked = dict(list(every.items())[:n])
    note = (
        f"showing {len(picked)} of {len(every)} templates: the largest of this period and filters (from a survey of them)"
        if len(every) > len(picked)
        else "the templates of this period and filters (from a survey of them)"
    )
    return sorted(picked.values(), key=_tmpl_number), [note]


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
    timezone: str | None = None,
    confirmed_cost: str | None = None,
) -> str:
    lt = ctx.store.get_log_table(log_table)
    timezone = shown_zone(lt, timezone)
    unit = _as_bucket(bucket)
    if not start or not end:
        raise UserFacingError(NEED_PERIOD)
    if lt.roles.timestamp is None:
        raise UserFacingError(f"Log table '{lt.name}' has no timestamp field, so there is nothing to trend over time.")
    cur = parse_time_range(start, end, timezone)
    assert cur.start is not None and cur.end is not None
    zone = get_zone(timezone)
    prev_start = preceding_start(cur.start, cur.end, zone)
    prev = TimeRange(prev_start, cur.start, timezone)
    tr_all = TimeRange(prev_start, cur.end, timezone)
    n_buckets = _count_buckets(prev_start, cur.start, zone, unit) + _count_buckets(cur.start, cur.end, zone, unit)
    if n_buckets > MAX_BUCKETS:
        raise UserFacingError(
            f"That would be {n_buckets:,} {unit}s across both periods (at most {MAX_BUCKETS:,}): "
            "use a shorter period or bigger buckets."
        )
    cur_buckets = _buckets(cur.start, cur.end, zone, unit)
    prev_buckets = _buckets(prev_start, cur.start, zone, unit)
    if templates:
        chosen, notes = _choose(ctx, lt, templates, top_n)
    else:
        chosen, notes = _top_of_period(ctx, lt, start, end, filters, top_n, timezone, confirmed_cost)
    from serenedb_extractor.catalog.store import covering

    for t in chosen:  # overlapping templates: an entry counts once, under the lowest ID
        wide = covering(t, [o for o in chosen if o is not t])
        if wide is not t and _tmpl_number(wide) < _tmpl_number(t):
            notes.append(
                f"{t.template_id} is a narrower form of {wide.template_id}, so its entries are counted under "
                f"{wide.template_id}; ask for {t.template_id} alone to count it on its own"
            )
    f = Filters.from_dict(filters)
    db = ctx.db
    with readable(f"the source of log table '{lt.name}'"):
        cols = known_columns(db, lt)
        try:
            rng, checked = data_range(db, lt, cols), True
        except ScanTooExpensive:
            rng, checked = None, False
        cur_cover = _coverage(rng, checked, cur.start, cur.end, cur, "this period")
        prev_cover = _coverage(rng, checked, prev_start, cur.start, cur, "the preceding period")
        stats = collect(db, lt, tr_all)
        target = max(ctx.settings.sample_size, MIN_BUCKET_SAMPLE * n_buckets)
        read = _columns_read(lt, f, cols)
        # A comparison of two periods from a few sampled blocks can be far off (whole blocks cluster in time), so
        # every entry is counted whenever that fits the time budget; a sample is used only when it does not.
        affordable = cost.exact_plan(stats, read).seconds <= EXACT_WITHIN_S
        decision = cost.decide(stats, read, exact or affordable, target, confirmed_cost, max_s=ctx.settings.max_timeout_s)
        if decision.status == "ask":
            head = fmt.how_measured(cost.ASKED_HOW, tr_all.describe(), _filters_text(f), tz=timezone)
            return head + "\n" + decision.message
        plan = decision.plan
        if (missing := untimestamped_note(db, lt, tr_all)) is not None:
            notes.append(missing)
        sql, params = _build_sql(lt, cols, tr_all, cur.start, f, chosen, plan, unit, timezone)
        timeout = cost.run_timeout(plan, ctx.settings.default_timeout_s, ctx.settings.max_timeout_s)
        rows = db.read(sql, params, timeout_s=timeout, what=f"counting trends in {lt.name}", how_to_narrow=NARROW).rows
        seen = _seen_buckets(db, lt, cols, tr_all, cur.start, unit, timezone, timeout)
    series, entries, block_hits = _gather(rows, bool(plan.sampling), len(chosen), unit)
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

    def complete(b: datetime, period: TimeRange) -> bool:
        """The whole bucket lies inside the period and inside the data's time range."""
        lo, hi = _bounds(b, zone, unit)
        assert period.start is not None and period.end is not None
        inside = period.start <= lo and hi <= period.end
        return inside and (rng is None or (rng.first <= lo and hi <= rng.last))

    # R69: a current period running past the data's last entry is compared over the whole buckets the
    # data covers, against as many buckets ending where the current period starts.
    truncated: tuple[list[datetime], list[datetime]] | None = None
    if rng is not None and cur_cover.status == "partial" and rng.last < cur.end and rng.first <= cur.start:
        cmp_cur = [b for b in cur_buckets if complete(b, cur)]
        n_cmp = len(cmp_cur)
        if n_cmp and cmp_cur == cur_buckets[:n_cmp] and n_cmp <= len(prev_buckets):
            cmp_prev = prev_buckets[-n_cmp:]
            if all(complete(b, prev) for b in cmp_prev):
                truncated = (cmp_cur, cmp_prev)
    # A gap in the logs (whole buckets with no entry at all) inside the data's span: those buckets are not
    # covered, so the comparison is limited there and nothing is called new across the gap.
    if seen is not None:
        prev_cover = _gap_cover(prev_cover, prev_buckets, seen[0], lambda b: complete(b, prev), unit, "the preceding period", zone)
        cur_cover = _gap_cover(cur_cover, cur_buckets, seen[1], lambda b: complete(b, cur), unit, "this period", zone)
        if truncated is not None and (set(truncated[1]) - seen[0] or set(truncated[0]) - seen[1]):
            truncated = None
    else:
        notes.append("whether the logs have gaps (hours or days with no entries at all) was not checked: too expensive")
    over = ""
    if truncated is not None:
        n_cmp = len(truncated[0])
        over = f"compared over the {n_cmp} {unit}{'' if n_cmp == 1 else 's'} the data covers in both periods"
    if truncated is None and prev_cover.status == "full" and not any(complete(b, prev) for b in prev_buckets):
        # Shorter than one bucket: a gap in the data can't be seen, so "none before" proves nothing.
        prev_cover = Coverage("partial", f"the preceding period is shorter than one whole {unit}, so a gap in the data there can't be ruled out (use bucket='hour' or a longer period)")
    limited = [] if truncated else [c.why for c in (prev_cover, cur_cover) if c.status != "full"]
    out = [_head(lt, cur, prev, f, plan, timezone, unit)]
    out += [n if n.startswith('showing') else fmt.sentence(n) for n in [*plan.notes, *notes]]
    if len(chosen) > 1:
        out.append("Templates that overlap: an entry that matches several is counted once, under the one with the lowest ID.")
    if truncated is not None and rng is not None:
        out.append(
            f"{fmt.sentence(covers_text(rng, cur))} The data ends inside this period, so the change is {over}: "
            f"the first {len(truncated[0])} {unit}{'' if len(truncated[0]) == 1 else 's'} of this period against the "
            f"last {len(truncated[1])} of the preceding one."
        )
    if limited:
        out.append("limited comparison: " + "; ".join(limited) + ". Counts are shown; no change is given where a period is not fully covered.")
    out.append(
        f"Each period is split into {unit}s: this period has {len(cur_buckets)} ({_label(cur_buckets[0], zone, unit)} to "
        f"{_label(cur_buckets[-1], zone, unit)}), the preceding one {len(prev_buckets)}."
    )
    if unit == "hour":
        out.append(f"Hours are real hours (every instant is in exactly one), labelled in {timezone} with the UTC offset in force.")
    else:
        out.append(f"Days are calendar days in {timezone}.")
    changes = _clock_change([*prev_buckets, *cur_buckets], zone, unit)
    if changes:
        effect = (
            "so the local day of the change has 23 or 25 hours, with no hour skipped or merged"
            if unit == "hour"
            else "so those days have 23 or 25 hours"
        )
        out.append(f"clock change in {timezone} on {', '.join(changes)}: {effect}.")
    whole_cur = [b for b in cur_buckets if complete(b, cur)]
    # Buckets in a gap in the data (no entry of any kind) say nothing about whether a problem was there, so
    # presence is counted over the whole buckets with data, as rank_problems does.
    gapped = set(gap_buckets(cur_buckets, seen[1], lambda b: complete(b, cur), unit)) if seen is not None else set()
    whole_now = [b for b in whole_cur if b not in gapped]
    edge = len(cur_buckets) - len(whole_cur)
    left_out = [f"{edge} partial {unit}{'' if edge == 1 else 's'} at the edge of the period or the data"] if edge else []
    if gapped:
        g = len(gapped)
        left_out.append(f"{g} {unit}{'' if g == 1 else 's'} in a gap in the data with no entries at all")
    skipped = f" (not counted: {'; '.join(left_out)})" if left_out else ""
    with_data = " with data" if gapped else ""
    for i, t in enumerate(chosen):
        now, before = measure(i, 1, cur_buckets), measure(i, 0, prev_buckets)
        per_now = [measure(i, 1, [b]) for b in cur_buckets]
        per_before = [measure(i, 0, [b]) for b in prev_buckets]
        present = sum(1 for b, m in zip(cur_buckets, per_now, strict=True) if b in whole_now and m.value > 0)
        out += ["", f"{t.template_id}  {fmt.template_text(t.template)}"]
        out.append(f"    this period: {_show(now)}; preceding period: {_show(before)}")
        if truncated is not None:
            now_t, before_t = measure(i, 1, truncated[0]), measure(i, 0, truncated[1])
            full = Coverage("full")
            out.append(
                f"    change: {over}, {_amount(now_t)} against {_amount(before_t)}: {_change(now_t, before_t, full, full)}"
            )
        else:
            out.append(f"    change: {_change(now, before, cur_cover, prev_cover)}")
        late = ""
        if not plan.exact:
            blind = sum(1 for b, m in zip(cur_buckets, per_now, strict=True) if b in whole_now and _unsampled(m))
            late = f" in the sample (a {unit} with no sampled entry may still have some; {blind} had no sampled entries at all)"
        out.append(f"    present in {present} of {len(whole_now)} {unit}s{with_data}{late}{skipped}")
        out.append("    " + _components(series[i], lt, plan))
        if (teams := _teams(ctx, series[i], lt, plan)) is not None:
            out.append("    " + teams)
        out += _series_lines(per_now, per_before, unit, plan.exact)
    return "\n".join(out)


def _components(s: Series, lt: LogTable, plan: cost.Plan) -> str:
    if lt.roles.component is None:
        return "components: this log table has no component field"
    top = sorted(s.comps, key=lambda c: (-s.comps[c], c))
    shown = ", ".join(top[:SHOWN_COMPONENTS]) + (", …" if len(top) > SHOWN_COMPONENTS else "")
    where = "" if plan.exact else " (in the sample)"
    return f"components affected this period{where}: {shown} ({len(top)})" if top else "components affected this period: none"


def _teams(ctx: AppContext, s: Series, lt: LogTable, plan: cost.Plan) -> str | None:
    """The owning teams of the components affected, from the ownership rules on component."""
    found = ctx.store.ownership.for_table(lt.name, lt.roles.present())
    if found is None or found[0] != "component" or not s.comps:
        return None
    counts: dict[str, int] = {}
    for comp, n in s.comps.items():
        team = team_of(None if comp == "(none)" else comp, found[1])
        counts[team] = counts.get(team, 0) + n
    top = sorted(counts, key=lambda t: (-counts[t], t))
    where = "" if plan.exact else " (in the sample)"
    return f"owning teams this period{where}: {', '.join(top)} ({len(top)})"


def _series_lines(now: list[fmt.Measured], before: list[fmt.Measured], unit: Bucket, exact: bool) -> list[str]:
    def one(label: str, ms: list[fmt.Measured]) -> str:
        values = [m.value for m in ms]
        if exact and len(values) <= SERIES_NUMBERS_MAX:
            return f"    {label} by {unit}: " + " ".join(f"{round(v):,}" for v in values)
        shape = "" if exact else " (estimated shape; · = no sampled entries)"
        return f"    {label} by {unit}{shape}: {_spark(ms)}"

    return [one("this period", now), one("preceding period", before)]


def _head(lt: LogTable, cur: TimeRange, prev: TimeRange, f: Filters, plan: cost.Plan, tz: str, bucket: Bucket) -> str:
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
