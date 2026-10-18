"""rank_problems: which observed problems deserve attention first, ranked by a stated score.

A problem is a message template among the entries at warning level or above. For each log table the
candidates come from a survey of those entries over the period; then every candidate is counted exactly
over the period and the preceding period of equal length, and scored on five measured factors:

    score = 2 x severity + change + persistence + spread + share       (0 to 18)

each factor 0-3 by the thresholds in SCORING below, so the order is reproducible and every point can be
checked against the numbers shown next to it. The score orders what to look at first; it does not measure
impact, and entries are not incidents.
"""

from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from serenedb_extractor import format as fmt
from serenedb_extractor.catalog.models import LogTable, Template
from serenedb_extractor.catalog.store import covering
from serenedb_extractor.context import AppContext
from serenedb_extractor.errors import UserFacingError
from serenedb_extractor.ownership import STAND_IN, UNASSIGNED, team_of
from serenedb_extractor.query import cost
from serenedb_extractor.query.filters import (
    Filters,
    MissingRole,
    ScanTooExpensive,
    diagnose_empty,
    TimeRange,
    build_where,
    data_range,
    parse_time_range,
    role_sql,
    shown_zone,
    time_clause,
)
from serenedb_extractor.query.stats import collect, role_columns
from serenedb_extractor.setup.paths import sql_literal
from serenedb_extractor.setup.sniff import readable
from serenedb_extractor.timezones import get_zone
from serenedb_extractor.tools import survey as survey_tool
from serenedb_extractor.tools.describe import known_columns
from serenedb_extractor.tools.trend import (
    Bucket,
    Coverage,
    _bounds,
    _buckets,
    _classify,
    _coverage,
    _gap_cover,
    _key,
    _seen_buckets,
    _tmpl_number,
    _ts_local,
    gap_buckets,
    pct_text,
    preceding_start,
)

# Severity of a level value (case-insensitive); levels not listed (INFO, DEBUG, ...) are not problems.
SEVERITY = {
    **dict.fromkeys(("FATAL", "CRITICAL", "CRIT", "EMERG", "EMERGENCY", "ALERT", "PANIC"), 3),
    **dict.fromkeys(("ERROR", "ERR", "SEVERE", "FAILURE", "FAIL"), 2),
    **dict.fromkeys(("WARNING", "WARN"), 1),
}
MIN_LEVELS = {"warning": 1, "error": 2, "fatal": 3}
SCORING = (
    "score = 2 x severity + change + persistence + spread + share (0-18). severity: fatal/critical 3, "
    "error/severe/failure 2, warning 1 (the level most of its entries have). change against the preceding "
    "period: new or +50% or more 3, +10% to +50% 2, within ±10% 1, falling 0, not comparable (the data does not "
    "cover both periods) 1. persistence, the share of whole {unit}s it appears in: 75% or more 3, 40% 2, 10% 1, "
    "else 0. spread, distinct {spot}s: 100 or more 3, 10 or more 2, 2 or more 1, one 0. share of all entries at "
    "the levels ranked: 10% or more 3, 1% 2, 0.1% 1, else 0. Ties: more entries first."
)
DEFAULT_LIMIT = 10
DEFAULT_CANDIDATES = 15
NARROW = "narrow it: a shorter period (start/end), fewer log tables, or a higher min_level."


@dataclass
class Problem:
    lt: LogTable
    template: Template
    now: int = 0
    before: int = 0
    spots: int = 0
    levels: dict[str, int] = field(default_factory=dict)
    owners: dict[str, int] = field(default_factory=dict)  # component (or service) -> entries, this period
    buckets: set[Any] = field(default_factory=set)
    points: dict[str, int] = field(default_factory=dict)
    change: str = ""

    @property
    def score(self) -> int:
        return sum(self.points.values())


@dataclass
class TableRun:
    lt: LogTable
    problems: list[Problem] = field(default_factory=list)
    note: str | None = None
    asked: str | None = None
    severe_total: int = 0
    whole: int = 0
    unit: Bucket = "day"
    spot: str = "component"
    comparable: bool = True
    limited: list[str] = field(default_factory=list)
    period: str = ""
    owner_role: str | None = None
    owner_rules: list[Any] = field(default_factory=list)


def rank_problems(
    ctx: AppContext,
    start: str | None = None,
    end: str | None = None,
    log_tables: list[str] | None = None,
    min_level: str = "warning",
    filters: dict[str, Any] | None = None,
    limit: int | None = None,
    candidates: int | None = None,
    timezone: str | None = None,
    confirmed_cost: str | None = None,
) -> str:
    if not start or not end:
        raise UserFacingError(
            "Which period should I rank? rank_problems compares a period with the one before it, so it needs start "
            "and end, e.g. start='2005-12-01', end='2006-01-01' (end exclusive). describe_logs gives the time range."
        )
    floor = MIN_LEVELS.get((min_level or "").strip().lower())
    if floor is None:
        raise UserFacingError(f"min_level must be one of {', '.join(MIN_LEVELS)}.")
    parse_time_range(start, end, timezone or "UTC")  # a bad time or zone is explained before any query
    f = Filters.from_dict(filters)
    if f.level is not None:
        raise UserFacingError("Use min_level to choose the levels ranked, not a level filter.")
    if log_tables:
        tables = [ctx.store.get_log_table(n) for n in dict.fromkeys(log_tables)]
    else:
        tables = ctx.store.list_log_tables()
        if not tables:
            raise UserFacingError("There are no log tables yet; set one up first.")
    shown = fmt.clamp_limit(limit, DEFAULT_LIMIT, DEFAULT_LIMIT * ctx.settings.limit_cap)
    n_cand = fmt.clamp_limit(candidates, DEFAULT_CANDIDATES, DEFAULT_CANDIDATES * 4)
    runs: list[TableRun] = []
    for lt in tables:
        try:
            runs.append(_rank_one(ctx, lt, start, end, f, floor, n_cand, shown_zone(lt, timezone), confirmed_cost))
        except MissingRole as exc:
            if len(tables) == 1:
                raise
            runs.append(TableRun(lt, note=f"not ranked: {exc}"))
    return _render(runs, f, floor, shown)


def _rank_one(
    ctx: AppContext, lt: LogTable, start: str, end: str, f: Filters, floor: int, n_cand: int, tz: str,
    confirmed_cost: str | None,
) -> TableRun:
    run = TableRun(lt)
    if lt.roles.level is None:
        run.note = "not ranked: it has no level field, so there is no severity to rank by"
        return run
    if lt.roles.timestamp is None:
        run.note = "not ranked: it has no timestamp field, so there is no period to compare"
        return run
    cur = parse_time_range(start, end, tz)
    assert cur.start is not None and cur.end is not None
    prev_start = preceding_start(cur.start, cur.end, get_zone(tz))
    prev = TimeRange(prev_start, cur.start, tz)
    tr_all = TimeRange(prev_start, cur.end, tz)
    run.period = f"{cur.describe()} against {prev.describe()}"
    run.unit = "day" if cur.end - cur.start >= timedelta(days=3) else "hour"
    spot_role = next((r for r in ("host", "service", "component") if getattr(lt.roles, r) is not None), None)
    run.spot = spot_role or "entry"
    found = ctx.store.ownership.for_table(lt.name, lt.roles.present())
    if found is not None:
        run.owner_role, run.owner_rules = found
    else:
        run.owner_role = "component" if lt.roles.component is not None else None
    db = ctx.db
    with readable(f"the source of log table '{lt.name}'"):
        cols = known_columns(db, lt)
        # 1. Which level values count as problems, and how many entries they have this period.
        levels = _levels(ctx, lt, cur, f, cols, confirmed_cost)
        if isinstance(levels, str):
            run.asked = levels
            return run
        severe = {v: n for v, n in levels.items() if SEVERITY.get(v.upper(), 0) >= floor}
        if not levels and f.items():  # the filters matched nothing: say which, as count_logs does
            why = diagnose_empty(db, lt, cur, f, cols)
            run.note = "nothing matched the filters in this period" + (": " + " ".join(why) if why else "")
            return run
        if not levels:
            try:
                rng = data_range(db, lt, cols)
            except ScanTooExpensive:
                rng = None
            where = f"; the data covers {cur.fmt(rng.first)} to {cur.fmt(rng.last)} {tz}" if rng else ""
            run.note = f"no entries at all in this period{where}"
            return run
        if not severe:
            names = ", ".join(sorted(levels)) or "none"
            run.note = f"no entries at {_floor_name(floor)} level or above in this period (levels seen: {names})"
            return run
        run.severe_total = sum(severe.values())
        scope = {**dict(f.items()), "level": sorted(severe)}
        # 2. The candidates: a survey of those entries this period (it also saves them to the catalog).
        got: list[tuple[Template, fmt.Measured]] = []
        text = survey_tool.survey(
            ctx, lt.name, start=start, end=end, filters=scope, limit=1, timezone=tz, confirmed_cost=confirmed_cost,
            found=got,
        )
        if not got:
            run.asked = text.split("\n", 1)[1] if "TOO EXPENSIVE" in text else None
            run.note = None if run.asked else "the survey found no templates"
            return run
        # A survey of one period can find a narrower form of a template the catalog already holds (one variant of
        # a message family): rank the catalog's broadest covering template, so IDs and counts agree with trend.
        catalog = ctx.store.templates(lt.name)
        chosen = sorted({covering(t, catalog).template_id: covering(t, catalog) for t, _ in got[:n_cand]}.values(), key=_tmpl_number)
        # 3. Exact counts of every candidate over both periods.
        sf = Filters.from_dict(scope)
        read = role_columns(lt.roles.timestamp) + role_columns(lt.roles.message) + role_columns(lt.roles.level)
        for r in {spot_role, run.owner_role} - {None}:
            read += role_columns(getattr(lt.roles, str(r)))
        stats = collect(db, lt, tr_all)
        decision = cost.decide(stats, read * 2, True, ctx.settings.sample_size, confirmed_cost, max_s=ctx.settings.max_timeout_s)
        if decision.status == "ask":
            run.asked = decision.message
            return run
        plan = decision.plan
        if not plan.exact:
            exact = cost.exact_plan(stats, read * 2)
            run.asked = fmt.refusal(
                f"ranking needs exact counts, which need {cost.cost_text(exact)} (more than the time budget)",
                [f"run it anyway: repeat the same call with confirmed_cost={exact.cost_token()}", NARROW],
            )
            return run
        timeout = cost.run_timeout(plan, ctx.settings.default_timeout_s, ctx.settings.max_timeout_s)
        run.problems = _measure(ctx, lt, cols, tr_all, cur.start, sf, chosen, spot_role, run.owner_role, run.unit, tz, timeout)
        # 4. Coverage: a change is only given where the data covers both periods without a gap.
        try:
            rng, checked = data_range(db, lt, cols), True
        except ScanTooExpensive:
            rng, checked = None, False
        cur_cover = _coverage(rng, checked, cur.start, cur.end, cur, "this period")
        prev_cover = _coverage(rng, checked, prev_start, cur.start, cur, "the preceding period")
        zone = get_zone(tz)
        cur_b, prev_b = _buckets(cur.start, cur.end, zone, run.unit), _buckets(prev_start, cur.start, zone, run.unit)

        def whole(b: Any, period: TimeRange) -> bool:
            lo, hi = _bounds(b, zone, run.unit)
            assert period.start is not None and period.end is not None
            return period.start <= lo and hi <= period.end and (rng is None or (rng.first <= lo and hi <= rng.last))

        seen = _seen_buckets(db, lt, cols, tr_all, cur.start, run.unit, tz, timeout)
        if seen is not None:
            prev_cover = _gap_cover(prev_cover, prev_b, seen[0], lambda b: whole(b, prev), run.unit, "the preceding period", zone)
            cur_cover = _gap_cover(cur_cover, cur_b, seen[1], lambda b: whole(b, cur), run.unit, "this period", zone)
        run.limited = [c.why for c in (prev_cover, cur_cover) if c.status != "full"]
        run.comparable = not run.limited
        whole_now = {b for b in cur_b if whole(b, cur)}
        if seen is not None:  # buckets in a gap in the data say nothing about persistence
            whole_now -= set(gap_buckets(cur_b, seen[1], lambda b: whole(b, cur), run.unit))
        run.whole = len(whole_now)
    for p in run.problems:
        _score(p, run, whole_now)
    return run


def _levels(
    ctx: AppContext, lt: LogTable, cur: TimeRange, f: Filters, cols: dict[str, str], confirmed_cost: str | None
) -> dict[str, int] | str:
    """Entries per level value this period, or the TOO EXPENSIVE message."""
    db = ctx.db
    where, params = build_where(lt, cur, f, cols)
    read = role_columns(lt.roles.timestamp) + role_columns(lt.roles.level)
    _, decision = cost.check(db, lt, cur, read, confirmed_cost)
    if decision.status == "ask":
        return decision.message
    if not decision.plan.exact:  # severity needs every level present, not a sample's
        exact = cost.exact_plan(collect(db, lt, cur), read)
        return fmt.refusal(
            f"ranking needs the exact levels of the period, which need {cost.cost_text(exact)}",
            [f"run it anyway: repeat the same call with confirmed_cost={exact.cost_token()}", NARROW],
        )
    timeout = cost.run_timeout(decision.plan, ctx.settings.default_timeout_s, ctx.settings.max_timeout_s)
    rows = db.read(
        f"SELECT ({role_sql(lt, 'level')})::varchar AS lvl, count(*) FROM {lt.relation} WHERE {where} GROUP BY 1",
        params, timeout_s=timeout, what=f"counting levels in {lt.name}", how_to_narrow=NARROW,
    ).rows
    return {str(v): int(n) for v, n in rows if v is not None}


def _measure(
    ctx: AppContext, lt: LogTable, cols: dict[str, str], tr_all: TimeRange, cur_start: Any, f: Filters,
    chosen: list[Template], spot_role: str | None, owner_role: str | None, unit: Bucket, tz: str, timeout: float,
) -> list[Problem]:
    db = ctx.db
    where, params = build_where(lt, tr_all, f, cols)
    cur_sql, cur_params = time_clause(lt, TimeRange(start=cur_start), cols, prefix="c")
    params.update(cur_params)
    msg = f"coalesce(({role_sql(lt, 'message')})::varchar, '')"
    case, prefilter = _classify(chosen, msg, params)
    if prefilter:
        where += " AND " + prefilter
    spot = f"({role_sql(lt, spot_role)})::varchar" if spot_role else "NULL::varchar"
    owner = f"({role_sql(lt, owner_role)})::varchar" if owner_role else "NULL::varchar"
    rows = (
        f"SELECT {msg} AS msg, CASE WHEN {cur_sql} THEN 1 ELSE 0 END AS p, ({role_sql(lt, 'level')})::varchar AS lvl, "
        f"{spot} AS spot, {owner} AS own, "
        f"date_trunc({sql_literal(unit)}, {_ts_local(lt, cols, 'UTC' if unit == 'hour' else tz)}) AS bucket "
        f"FROM {lt.relation} WHERE {where}"
    )
    inner = f"SELECT {case} AS k, p, lvl, spot, own, bucket FROM ({rows})"
    what = f"ranking problems in {lt.name}"
    spots = db.read(
        f"SELECT k, count(DISTINCT spot) FROM ({inner}) WHERE k IS NOT NULL AND p = 1 GROUP BY k",
        params, timeout_s=timeout, what=what, how_to_narrow=NARROW,
    ).rows
    detail = db.read(
        f"SELECT k, p, bucket, lvl, own, count(*) FROM ({inner}) WHERE k IS NOT NULL GROUP BY k, p, bucket, lvl, own",
        params, timeout_s=timeout, what=what, how_to_narrow=NARROW,
    ).rows
    problems = [Problem(lt, t) for t in chosen]
    for k, n in spots:
        problems[int(k) - 1].spots = int(n)
    for k, p, bucket, lvl, own, n in detail:
        pr, n = problems[int(k) - 1], int(n)
        if int(p) == 0:
            pr.before += n
            continue
        pr.now += n
        pr.buckets.add(_key(bucket, unit))
        pr.levels[str(lvl)] = pr.levels.get(str(lvl), 0) + n
        pr.owners[str(own)] = pr.owners.get(str(own), 0) + n
    return [p for p in problems if p.now]


def _score(p: Problem, run: TableRun, whole_now: set[Any]) -> None:
    level = max(p.levels, key=lambda v: (p.levels[v], SEVERITY.get(v.upper(), 0)))
    severity = SEVERITY.get(level.upper(), 0)
    if not run.comparable:
        change_pts, p.change = 1, "not comparable (the data does not cover both periods)"
    elif p.before == 0:
        change_pts, p.change = 3, f"new: none in the preceding period ({p.now:,} now)"
    else:
        ratio = (p.now - p.before) / p.before
        change_pts = 3 if ratio >= 0.5 else 2 if ratio >= 0.1 else 1 if ratio > -0.1 else 0
        p.change = f"{pct_text(100 * ratio)} ({p.before:,} -> {p.now:,})"
    present = len(p.buckets & whole_now)
    share_present = present / run.whole if run.whole else 0.0
    persistence = 3 if share_present >= 0.75 else 2 if share_present >= 0.4 else 1 if share_present >= 0.1 else 0
    spread = 3 if p.spots >= 100 else 2 if p.spots >= 10 else 1 if p.spots >= 2 else 0
    share = p.now / run.severe_total if run.severe_total else 0.0
    volume = 3 if share >= 0.10 else 2 if share >= 0.01 else 1 if share >= 0.001 else 0
    p.points = {"severity": 2 * severity, "change": change_pts, "persistence": persistence, "spread": spread, "share": volume}
    p.levels = dict(sorted(p.levels.items(), key=lambda kv: -kv[1]))
    p.buckets = {b for b in p.buckets if b in whole_now}


def _floor_name(floor: int) -> str:
    return next(k for k, v in MIN_LEVELS.items() if v == floor)


def _teams(p: Problem, run: TableRun) -> str | None:
    if not run.owner_rules:
        return None
    counts: dict[str, int] = {}
    for value, n in p.owners.items():
        team = team_of(None if value == "None" else value, run.owner_rules)
        counts[team] = counts.get(team, 0) + n
    top = sorted(counts, key=lambda t: -counts[t])
    text = ", ".join(t if len(top) == 1 else f"{t} {100 * counts[t] / p.now:.0f}%" for t in top[:3])
    stand_in = any(r.source == STAND_IN for r in run.owner_rules)
    if top == [UNASSIGNED]:
        return "owning team: none (no ownership rule covers it)"
    return f"owning team: {text}" + (" (from the stand-in ownership table, not an official mapping)" if stand_in else "")


def _render(runs: list[TableRun], f: Filters, floor: int, limit: int) -> str:
    ranked = sorted(
        (p for r in runs for p in r.problems), key=lambda p: (-p.score, -p.now, p.lt.name, _tmpl_number(p.template))
    )
    by_table = {r.lt.name: r for r in runs}
    filters = ", ".join(f"{k}={v!r}" for k, v in f.items())
    scope = f"entries at {_floor_name(floor)} level or above" + (f", {filters}" if filters else "")
    tz = {r.period.rsplit(" ", 1)[-1] for r in runs if r.period}
    head = fmt.how_measured(
        "ranking: candidates from a survey of each log table's entries in scope, then every candidate counted exactly "
        "over this period and the preceding one inside SereneDB",
        "; ".join(f"{r.lt.name}: {r.period}" for r in runs if r.period) or None,
        scope,
        tz=next(iter(tz)) if len(tz) == 1 else "each log table's own time zone",
    )
    units = {r.unit for r in runs if r.problems}
    spots = sorted({r.spot for r in runs if r.problems})
    out = [
        head,
        SCORING.format(unit="/".join(sorted(units)) or "day", spot="/".join(spots) or "host"),
        "The score orders what to look at first. It counts log entries, not incidents, and does not measure impact.",
    ]
    for r in runs:
        if r.asked:
            out.append(f"Log table {r.lt.name}: TOO EXPENSIVE to rank. {r.asked}")
        elif r.note:
            out.append(f"Log table {r.lt.name}: {r.note}.")
        elif r.limited:
            out.append(f"Log table {r.lt.name}: limited comparison: {'; '.join(r.limited)}. No change is given there.")
    if not ranked:
        out.append("Nothing to rank.")
        return "\n".join(out)
    cut = ranked[:limit]
    if len(cut) < len(ranked):
        out.append(f"showing the top {len(cut)} of {len(ranked)} ranked problems (raise limit to see more)")
    for i, p in enumerate(cut, 1):
        r = by_table[p.lt.name]
        pts = p.points
        levels = ", ".join(f"{v} {n:,}" for v, n in p.levels.items())
        out += [
            "",
            f"{i}. score {p.score}/18  [{p.lt.name} {p.template.template_id}] {fmt.shorten(fmt.template_text(p.template.template), 160)}",
            f"    {p.now:,} entries this period (exact; {levels}), {100 * p.now / r.severe_total:.1f}% of the entries ranked in {p.lt.name}",
            f"    change: {p.change}",
            f"    present in {len(p.buckets)} of {r.whole} whole {r.unit}s" + (" with data" if r.limited else "") + "; "
            + (
                f"spread: {p.spots:,} distinct {r.spot}" + ("" if p.spots == 1 else "s")
                if r.spot != "entry"
                else "spread: not measured (no host, service or component field)"
            ),
        ]
        owners = sorted(p.owners, key=lambda v: -p.owners[v])
        if r.owner_role and owners and owners != ["None"]:
            out.append(f"    {r.owner_role}: " + ", ".join(owners[:3]) + (", …" if len(owners) > 3 else ""))
        if (teams := _teams(p, r)) is not None:
            out.append(f"    {teams}")
        out.append(
            f"    points: severity {pts['severity']}, change {pts['change']}, persistence {pts['persistence']}, "
            f"spread {pts['spread']}, share {pts['share']}"
        )
    return "\n".join(out)
