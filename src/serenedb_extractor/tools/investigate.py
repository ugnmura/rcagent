"""Exact investigation of chosen templates: locate_occurrences (counts + examples) and extract_params."""

import re
from dataclasses import dataclass
from typing import Any

from serenedb_extractor import format as fmt
from serenedb_extractor.catalog.models import LogTable, Template
from serenedb_extractor.context import AppContext
from serenedb_extractor.db import quote_ident
from serenedb_extractor.errors import UserFacingError
from serenedb_extractor.query import cost, occurrence, sampling
from serenedb_extractor.query.filters import (
    FILTER_ROLES,
    Filters,
    TimeRange,
    build_where,
    diagnose_empty,
    parse_time_range,
    role_sql,
    shown_zone,
    time_clause,
    ts_tz_sql,
)
from serenedb_extractor.query.stats import role_columns
from serenedb_extractor.setup.paths import sql_literal
from serenedb_extractor.setup.roles import resolve_column
from serenedb_extractor.setup.sniff import readable
from serenedb_extractor.query.templatematch import fixed_word_prefilter, template_match_sql
from serenedb_extractor.query.coverage import untimestamped_note
from serenedb_extractor.tools.describe import known_columns
from serenedb_extractor.timezones import get_zone

DEFAULT_GROUPS = 20
DEFAULT_VALUES = 10
BY_GROUPS = 10
BY_VALUES = 5
NONE_LABEL = "(none)"
NONE_SQL = sql_literal(NONE_LABEL)
_TIME = re.compile(r"time:(\d+)([mhd])")
_UNIT_SECONDS = {"m": 60, "h": 3600, "d": 86400}
_UNIT_NAME = {"m": "minute", "h": "hour", "d": "day"}

NEED_TEMPLATE = "Say which templates to locate: run a survey first and pick template IDs (T1, T2, ...) from its result."
NARROW = (
    "narrow it: a shorter period (start/end), filters such as level or service; "
    "or build a search index (create_index with dry_run)."
)


# ---- grouping --------------------------------------------------------------------------------


def _int(n: int) -> str:
    """An integer as SQL text: int() guarantees digits only, so it is safe to put in the SQL."""
    return str(int(n))


def _bucket_sql(lt: LogTable, cols: dict[str, str], n: int, unit: str, tz: str) -> str:
    secs = _int(n * _UNIT_SECONDS[unit])
    local = f"({ts_tz_sql(lt, cols)} AT TIME ZONE {sql_literal(tz)})"
    shape = "%Y-%m-%d" if unit == "d" else "%Y-%m-%d %H:%M"
    start = f"(TIMESTAMP '1970-01-01' + to_seconds((floor(epoch({local}) / {secs}) * {secs})::bigint))"
    return f"coalesce(strftime({start}, {sql_literal(shape)}), {NONE_SQL})"


def parse_group_by(
    lt: LogTable, items: list[str] | None, known: dict[str, str], tz: str = "UTC"
) -> list[tuple[str, str]]:
    """(label, SQL expression yielding a varchar) per item: a role name, a column name or `time:<n>m|h|d`."""
    out: list[tuple[str, str]] = []
    for item in items or []:
        name = item.strip()
        if name.lower().startswith("time:"):
            m = _TIME.fullmatch(name.lower())
            if not m or int(m.group(1)) < 1:
                raise UserFacingError(
                    f"'{item}' is not a time bucket: use time:<n>m, time:<n>h or time:<n>d, e.g. time:15m or time:1d."
                )
            get_zone(tz)
            out.append((name.lower(), _bucket_sql(lt, known, int(m.group(1)), m.group(2), tz)))
        elif name in FILTER_ROLES:
            out.append((name, f"coalesce(({role_sql(lt, name)})::varchar, {NONE_SQL})"))
        elif (col := resolve_column(name, known)) is not None:
            out.append((col, f"coalesce({quote_ident(col)}::varchar, {NONE_SQL})"))
        else:
            raise UserFacingError(
                f"I can't group by '{item}': use a role ({', '.join(FILTER_ROLES)}), a column ({', '.join(known)}) "
                "or a time bucket such as time:1h."
            )
    return out


def _group_columns(lt: LogTable, items: list[str], known: dict[str, str]) -> list[str]:
    cols: list[str] = []
    for it in items:
        name = it.strip()
        if name.lower().startswith("time:"):
            cols += role_columns(lt.roles.timestamp)
        elif name in FILTER_ROLES:
            cols += role_columns(getattr(lt.roles, name))
        elif (c := resolve_column(name, known)) is not None:
            cols.append(c)
    return cols


# ---- shared scope ----------------------------------------------------------------------------


@dataclass
class Scope:
    db: Any
    lt: LogTable
    tr: TimeRange
    f: Filters
    tz: str
    cols: dict[str, str]
    templates: list[Template]
    time_sql: str
    match_sql: str  # filters + the fixed-word prefilter
    params: dict[str, Any]


def _filters_text(f: Filters, templates: list[Template]) -> str | None:
    parts = []
    for key, wanted in f.items():
        parts.append(f"{key} in ({', '.join(repr(w) for w in wanted)})" if isinstance(wanted, list) else f"{key}={wanted!r}")
    parts.append("templates " + ", ".join(t.template_id for t in templates))
    return ", ".join(parts)


def _msg(lt: LogTable) -> str:
    return f"coalesce(({role_sql(lt, 'message')})::varchar, '')"


def _prefilter(lt: LogTable, templates: list[Template], params: dict[str, Any]) -> str:
    """The shared fixed-word prefilter on the message ("TRUE" when some template has no fixed word)."""
    return fixed_word_prefilter(templates, _msg(lt), params, "w") or "TRUE"


def _resolve_templates(ctx: AppContext, log_table: str, given: list[str]) -> tuple[list[Template], list[str]]:
    live: dict[str, Template] = {}
    notes: list[str] = []
    for g in given:
        r = ctx.store.resolve(log_table, g)
        live.setdefault(r.template.template_id, r.template)
        if r.redirected_from:
            notes.append(f"{r.redirected_from} was merged into {r.template.template_id}; used that one.")
    ordered = sorted(live.values(), key=lambda t: int(t.template_id[1:]) if t.template_id[1:].isdigit() else 0)
    return ordered, notes


def _scope(ctx: AppContext, lt: LogTable, tr: TimeRange, f: Filters, tz: str, templates: list[Template]) -> Scope:
    cols = known_columns(ctx.db, lt)
    time_sql, time_params = time_clause(lt, tr, cols)
    match_sql, params = build_where(lt, TimeRange(), f, cols)
    params.update(time_params)
    pre = _prefilter(lt, templates, params)
    return Scope(ctx.db, lt, tr, f, tz, cols, templates, time_sql, f"({match_sql}) AND {pre}", params)


def _filter_columns(lt: LogTable, f: Filters, cols: dict[str, str]) -> list[str]:
    out: list[str] = []
    for k, _ in f.items():
        if k in FILTER_ROLES:
            out += role_columns(getattr(lt.roles, k))
        elif (c := resolve_column(k, cols)) is not None:
            out.append(c)
    return out


def _entries_per_block(sc: Scope, plan: cost.Plan, scope_sql: str, timeout: float, what: str) -> list[int]:
    rows = sc.db.read(
        f"SELECT {sampling.block_id_sql(plan)} AS b, count(*) FROM {sc.lt.relation} WHERE {scope_sql} GROUP BY 1",
        sc.params, timeout_s=timeout, what=what, how_to_narrow=NARROW,
    ).rows
    found = {int(r[0]): int(r[1]) for r in rows if r[0] is not None}
    return [found.get(i, 0) for i in range(len(plan.groups))]


def _sample_text(plan: cost.Plan) -> str | None:
    if plan.exact:
        return None
    upto = "" if plan.rows_exact else "up to "
    return (
        f"block sample of {plan.sample_rows or 0:,} of {upto}{plan.population_rows:,} entries "
        f"({len(plan.groups)} whole row group{'' if len(plan.groups) == 1 else 's'} overlapping the period; repeatable)"
    )


def _how(sc: Scope, plan: cost.Plan, exact_kind: str, est_kind: str) -> str:
    kind = exact_kind + (" (run as you confirmed)" if plan.confirmed else "") if plan.exact else est_kind
    return fmt.how_measured(
        kind, sc.tr.describe() if sc.tr.bounded else None, _filters_text(sc.f, sc.templates), _sample_text(plan), tz=sc.tz
    )


def _ask(sc: Scope, message: str) -> str:
    head = fmt.how_measured(
        cost.ASKED_HOW, sc.tr.describe() if sc.tr.bounded else None, _filters_text(sc.f, sc.templates), tz=sc.tz
    )
    return head + "\n" + message


def _scope_sql(sc: Scope, plan: cost.Plan) -> str:
    return sc.time_sql + (" AND " + sampling.clause(plan) if plan.sampling else "")


# ---- locate_occurrences ----------------------------------------------------------------------


def locate_occurrences(
    ctx: AppContext,
    log_table: str,
    templates: list[str],
    start: str | None = None,
    end: str | None = None,
    filters: dict[str, Any] | None = None,
    group_by: list[str] | None = None,
    examples_per_group: int = 3,
    limit: int | None = None,
    timezone: str | None = None,
    confirmed_cost: str | None = None,
) -> str:
    if not templates:
        raise UserFacingError(NEED_TEMPLATE)
    lt = ctx.store.get_log_table(log_table)
    timezone = shown_zone(lt, timezone)
    tr = parse_time_range(start, end, timezone)
    f = Filters.from_dict(filters)
    tpls, notes = _resolve_templates(ctx, lt.name, templates)
    shown_limit = fmt.clamp_limit(limit, DEFAULT_GROUPS, DEFAULT_GROUPS * ctx.settings.limit_cap)
    per_group = max(0, min(int(examples_per_group), 20))
    db = ctx.db
    with readable(f"the source of log table '{lt.name}'"):
        sc = _scope(ctx, lt, tr, f, timezone, tpls)
        groups = parse_group_by(lt, group_by, sc.cols, timezone)
        has_ids = occurrence.kind(lt) is not None
        base = (
            role_columns(lt.roles.message)
            + role_columns(lt.roles.timestamp)
            + _filter_columns(lt, f, sc.cols)
            + _group_columns(lt, group_by or [], sc.cols)
        )
        scans = base * (2 if per_group and has_ids else 1)
        _, decision = cost.check(db, lt, tr, scans, confirmed_cost)
        if decision.status == "ask":
            return _ask(sc, decision.message)
        plan = decision.plan
        if (missing := untimestamped_note(db, lt, tr)) is not None:
            notes.append(missing)
        scope_sql = _scope_sql(sc, plan)
        what = f"locating occurrences in log table {lt.name}"
        timeout = cost.run_timeout(plan, ctx.settings.default_timeout_s, ctx.settings.max_timeout_s)
        case = "CASE " + " ".join(
            f"WHEN {template_match_sql(_msg(lt), f'r_{i}')} THEN {i}" for i in range(len(tpls))
        ) + " END"
        params = dict(sc.params)
        for i, t in enumerate(tpls):
            params[f"r_{i}"] = t.regex
        keys = "".join(f", {expr} AS k{i}" for i, (_, expr) in enumerate(groups))
        key_names = [f"k{i}" for i in range(len(groups))]
        blk = f", {sampling.block_id_sql(plan)} AS blk" if not plan.exact else ""
        inner = f"SELECT {case} AS tpl{keys}{blk} FROM {lt.relation} WHERE {scope_sql} AND {sc.match_sql}"
        gcols = ", ".join(["tpl", *key_names] + ([] if plan.exact else ["blk"]))
        rows = db.read(
            f"SELECT {gcols}, count(*) AS n FROM ({inner}) WHERE tpl IS NOT NULL GROUP BY {gcols}",
            params, timeout_s=timeout, what=what, how_to_narrow=NARROW,
        ).rows
        n_keys = len(groups)
        counts: dict[tuple[int, tuple[str, ...]], list[tuple[int, int]]] = {}
        for r in rows:
            key = (int(r[0]), tuple(str(x) for x in r[1 : 1 + n_keys]))
            b = 0 if plan.exact else int(r[1 + n_keys])
            counts.setdefault(key, []).append((b, int(r[-1])))
        entries = [] if plan.exact else _entries_per_block(sc, plan, scope_sql, timeout, what)
        measured = _measure(plan, counts, entries)
        ordered = _order(measured, groups, tpls)
        shown: dict[int, list[tuple[tuple[str, ...], fmt.Measured]]] = {}
        for (ti, gkey), m in ordered:
            shown.setdefault(ti, []).append((gkey, m))
        totals = _totals(plan, counts, entries, len(tpls))
        cut_groups = {ti: items[:shown_limit] for ti, items in shown.items()}
        examples: dict[tuple[int, tuple[str, ...]], list[str]] = {}
        if per_group and has_ids and cut_groups:
            examples = _examples(sc, plan, scope_sql, groups, cut_groups, per_group, case, params, timeout, what)
        empty_why = (
            diagnose_empty(db, lt, tr, f, sc.cols) if plan.exact and not counts and (f.items() or tr.bounded) else []
        )
    return _render_locate(sc, plan, groups, shown, cut_groups, totals, examples, notes, shown_limit, empty_why)


def _measure(
    plan: cost.Plan, counts: dict[tuple[int, tuple[str, ...]], list[tuple[int, int]]], entries: list[int]
) -> dict[tuple[int, tuple[str, ...]], fmt.Measured]:
    out: dict[tuple[int, tuple[str, ...]], fmt.Measured] = {}
    for key, per in counts.items():
        out[key] = _one(plan, per, entries)
    return out


def _one(plan: cost.Plan, per: list[tuple[int, int]], entries: list[int]) -> fmt.Measured:
    if plan.exact:
        return fmt.Measured(float(sum(n for _, n in per)), True)
    hits = dict(per)
    return sampling.block_estimate([(entries[i], hits.get(i, 0)) for i in range(len(entries))], plan.fraction)


def _totals(
    plan: cost.Plan, counts: dict[tuple[int, tuple[str, ...]], list[tuple[int, int]]], entries: list[int], n_t: int
) -> dict[int, fmt.Measured]:
    out: dict[int, fmt.Measured] = {}
    for ti in range(n_t):
        merged: dict[int, int] = {}
        for (t, _), per in counts.items():
            if t == ti:
                for b, n in per:
                    merged[b] = merged.get(b, 0) + n
        out[ti] = _one(plan, list(merged.items()), entries)
    return out


def _order(
    measured: dict[tuple[int, tuple[str, ...]], fmt.Measured], groups: list[tuple[str, str]], tpls: list[Template]
) -> list[tuple[tuple[int, tuple[str, ...]], fmt.Measured]]:
    by_time = any(label.startswith("time:") for label, _ in groups)
    if by_time:
        return sorted(measured.items(), key=lambda kv: (kv[0][0], kv[0][1]))
    return sorted(measured.items(), key=lambda kv: (kv[0][0], -kv[1].value, kv[0][1]))


def _examples(
    sc: Scope,
    plan: cost.Plan,
    scope_sql: str,
    groups: list[tuple[str, str]],
    cut_groups: dict[int, list[tuple[tuple[str, ...], fmt.Measured]]],
    per_group: int,
    case: str,
    params: dict[str, Any],
    timeout: float,
    what: str,
) -> dict[tuple[int, tuple[str, ...]], list[str]]:
    lt = sc.lt
    keys = "".join(f", {expr} AS k{i}" for i, (_, expr) in enumerate(groups))
    key_names = [f"k{i}" for i in range(len(groups))]
    ors: list[str] = []
    p = dict(params)
    n = 0
    for ti, items in cut_groups.items():
        for key, _ in items:
            parts = [f"tpl = {ti}"]
            for j, v in enumerate(key):
                p[f"g{n}_{j}"] = v
                parts.append(f"k{j} = %(g{n}_{j})s")
            ors.append("(" + " AND ".join(parts) + ")")
            n += 1
    order = role_sql(lt, "timestamp") if lt.roles.timestamp is not None else "1"
    occ_cols = occurrence.select_sql(lt)
    occ_names = [c.split(" AS ")[-1].strip() for c in occ_cols.split(",") if c.strip()]
    part = ", ".join(["tpl", *key_names])
    inner = (
        f"SELECT {case} AS tpl{keys}, {order} AS ord_{occ_cols} FROM {lt.relation} "
        f"WHERE {scope_sql} AND {sc.match_sql}"
    )
    sql = (
        f"SELECT tpl, {', '.join(key_names + occ_names)} FROM ("
        f"SELECT *, row_number() OVER (PARTITION BY {part} ORDER BY ord_) AS rn FROM ({inner}) "
        f"WHERE tpl IS NOT NULL AND ({' OR '.join(ors)})) WHERE rn <= {_int(per_group)}"
    )
    out: dict[tuple[int, tuple[str, ...]], list[str]] = {}
    for r in sc.db.read(sql, p, timeout_s=timeout, what=what, how_to_narrow=NARROW).dicts():
        ekey = (int(r["tpl"]), tuple(str(r[k]) for k in key_names))
        out.setdefault(ekey, []).append(occurrence.encode_occurrence(lt, r))
    return out


def _label(groups: list[tuple[str, str]], key: tuple[str, ...]) -> str:
    return ", ".join(key) if groups else "all matching entries"


def _render_locate(
    sc: Scope,
    plan: cost.Plan,
    groups: list[tuple[str, str]],
    shown: dict[int, list[tuple[tuple[str, ...], fmt.Measured]]],
    cut_groups: dict[int, list[tuple[tuple[str, ...], fmt.Measured]]],
    totals: dict[int, fmt.Measured],
    examples: dict[tuple[int, tuple[str, ...]], list[str]],
    notes: list[str],
    shown_limit: int,
    empty_why: list[str],
) -> str:
    multi = len(sc.templates) > 1
    out = [
        _how(
            sc,
            plan,
            "exact count: every entry in scope was checked against each template's pattern"
            + (f", grouped by {', '.join(g for g, _ in groups)}" if groups else ""),
            "estimated: whole blocks of entries were checked against each template's pattern and the counts scaled up from them"
            + (f", grouped by {', '.join(g for g, _ in groups)}" if groups else ""),
        )
    ]
    out += [fmt.sentence(n) for n in [*notes, *plan.notes]]
    if multi:
        out.append("An entry that matches several of these templates is counted under the first one (by template ID) only.")
    if not plan.exact:
        out.append("Example occurrences come from the sampled blocks.")
    for ti, t in enumerate(sc.templates):
        out.append("")
        out.append(f"{t.template_id}  {fmt.template_text(t.template)}")
        items = cut_groups.get(ti, [])
        if not items:
            out.append("    no matching entries" + ("" if plan.exact else " in the sample (some may exist outside it)"))
            continue
        out.append(f"    total: {_num(totals[ti])}")
        for key, m in items:
            ex = examples.get((ti, key))
            if groups:
                out.append(f"    {_label(groups, key)}: {_num(m)}")
            if ex:
                out.append(f"    {'    ' if groups else ''}examples: {', '.join(ex)}")
        if len(shown[ti]) > len(items):
            out.append(f"    showing {len(items)} of {len(shown[ti])} groups")
    if not any(cut_groups.values()):
        out += empty_why
    return "\n".join(out)


def _num(m: fmt.Measured) -> str:
    return f"{round(m.value):,}" if m.exact else fmt.render(m)


# ---- extract_params --------------------------------------------------------------------------


def extract_params(
    ctx: AppContext,
    log_table: str,
    template: str,
    start: str | None = None,
    end: str | None = None,
    filters: dict[str, Any] | None = None,
    by: str | None = None,
    limit: int | None = None,
    timezone: str | None = None,
    confirmed_cost: str | None = None,
) -> str:
    lt = ctx.store.get_log_table(log_table)
    timezone = shown_zone(lt, timezone)
    tr = parse_time_range(start, end, timezone)
    f = Filters.from_dict(filters)
    tpls, notes = _resolve_templates(ctx, lt.name, [template])
    t = tpls[0]
    if not t.params:
        raise UserFacingError(f"{t.template_id} ({t.template}) has no parameters to extract.")
    shown_limit = fmt.clamp_limit(limit, DEFAULT_VALUES, DEFAULT_VALUES * ctx.settings.limit_cap)
    db = ctx.db
    with readable(f"the source of log table '{lt.name}'"):
        sc = _scope(ctx, lt, tr, f, timezone, tpls)
        by_items = parse_group_by(lt, [by] if by else [], sc.cols, timezone)
        by_expr = by_items[0][1] if by_items else None
        numeric = [p for p in t.params if p.kind == "num"]
        base = (
            role_columns(lt.roles.message)
            + role_columns(lt.roles.timestamp)
            + _filter_columns(lt, f, sc.cols)
            + _group_columns(lt, [by] if by else [], sc.cols)
        )
        n_scans = 1 + (1 if numeric else 0) + (2 + (1 if numeric else 0) if by else 0)
        _, decision = cost.check(db, lt, tr, base * n_scans, confirmed_cost)
        if decision.status == "ask":
            return _ask(sc, decision.message)
        plan = decision.plan
        if (missing := untimestamped_note(db, lt, tr)) is not None:
            notes.append(missing)
        run = _ParamRun(sc, plan, t, by_expr, shown_limit, ctx)
        result = run.go()
    return _render_params(sc, plan, t, by_items[0][0] if by_items else None, result, shown_limit, notes)


Stats = tuple[int, float, float, float, float]


@dataclass
class ParamResult:
    matched: fmt.Measured
    top: dict[str, list[tuple[str, int]]]
    distinct: dict[str, int]
    values: dict[str, int]
    stats: dict[str, Stats]
    by_total: list[tuple[str, int]]
    by_distinct: int
    by_top: dict[tuple[str, str], list[tuple[str, int]]]
    by_stats: dict[tuple[str, str], Stats]


class _ParamRun:
    def __init__(self, sc: Scope, plan: cost.Plan, t: Template, by_expr: str | None, limit: int, ctx: AppContext) -> None:
        self.sc, self.plan, self.t, self.by_expr, self.limit = sc, plan, t, by_expr, limit
        self.db = ctx.db
        self.timeout = cost.run_timeout(plan, ctx.settings.default_timeout_s, ctx.settings.max_timeout_s)
        self.what = f"extracting parameters of {t.template_id} in log table {sc.lt.name}"
        self.params: dict[str, Any] = {**sc.params, "regex": t.regex}
        self.scope_sql = _scope_sql(sc, plan)
        names = [p.name for p in t.params]
        lt = sc.lt
        by_col = f", {by_expr} AS b" if by_expr else ", 'all' AS b"
        blk = f", {sampling.block_id_sql(plan)} AS blk" if not plan.exact else ""
        extract = f"regexp_extract(m, %(regex)s, [{', '.join(sql_literal(n) for n in names)}])"
        self.matched = (
            f"SELECT {extract} AS x, b{'' if plan.exact else ', blk'} FROM ("
            f"SELECT {_msg(lt)} AS m{by_col}{blk} FROM {lt.relation} "
            f"WHERE {self.scope_sql} AND {sc.match_sql}) WHERE {template_match_sql('m', 'regex')}"
        )
        vals = ", ".join(f"struct_extract(x, {sql_literal(n)})" for n in names)
        self.unpivot = (
            f"SELECT b, unnest([{', '.join(sql_literal(n) for n in names)}]) AS p, unnest([{vals}]) AS v "
            f"FROM ({self.matched})"
        )
        self.numeric = [p.name for p in t.params if p.kind == "num"]

    def q(self, sql: str, params: dict[str, Any] | None = None) -> list[tuple[Any, ...]]:
        return [tuple(r) for r in self.db.read(sql, params or self.params, timeout_s=self.timeout, what=self.what, how_to_narrow=NARROW).rows]

    def _stats_sql(self, per_b: bool, where: str = "") -> str:
        names = ", ".join(sql_literal(n) for n in self.numeric)
        b = "b, " if per_b else ""
        return (
            f"SELECT {b}p, count(x), min(x), quantile_cont(x, 0.5), quantile_cont(x, 0.95), max(x) FROM ("
            f"SELECT b, p, try_cast(v AS DOUBLE) AS x FROM ({self.unpivot}) WHERE p IN ({names}){where}) "
            f"WHERE x IS NOT NULL GROUP BY {b}p"
        )

    def go(self) -> ParamResult:
        sc, plan = self.sc, self.plan
        if plan.exact:
            matched = fmt.Measured(float(self.q(f"SELECT count(*) FROM ({self.matched})")[0][0]), True)
        else:
            hits = {int(r[0]): int(r[1]) for r in self.q(f"SELECT blk, count(*) FROM ({self.matched}) GROUP BY 1") if r[0] is not None}
            entries = _entries_per_block(sc, plan, self.scope_sql, self.timeout, self.what)
            matched = sampling.block_estimate([(entries[i], hits.get(i, 0)) for i in range(len(entries))], plan.fraction)
        top: dict[str, list[tuple[str, int]]] = {}
        distinct: dict[str, int] = {}
        values: dict[str, int] = {}
        for p, v, c, d, tot in self.q(
            "SELECT p, v, c, d, tot FROM (SELECT p, v, c, row_number() OVER (PARTITION BY p ORDER BY c DESC, v) AS rn, "
            "count(*) OVER (PARTITION BY p) AS d, sum(c) OVER (PARTITION BY p) AS tot FROM ("
            f"SELECT p, v, count(*) AS c FROM ({self.unpivot}) WHERE v IS NOT NULL GROUP BY 1, 2)) WHERE rn <= {_int(self.limit)}"
        ):
            top.setdefault(p, []).append((str(v), int(c)))
            distinct[p], values[p] = int(d), int(tot)
        stats = {}
        if self.numeric:
            for r in self.q(self._stats_sql(False)):
                stats[r[0]] = (int(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5]))
        res = ParamResult(matched, top, distinct, values, stats, [], 0, {}, {})
        if self.by_expr:
            self._by(res)
        return res

    def _by(self, res: ParamResult) -> None:
        rows = self.q(
            f"SELECT b, count(*) AS c, count(*) OVER () AS g FROM ({self.matched}) GROUP BY b ORDER BY c DESC, b LIMIT {_int(BY_GROUPS)}"
        )
        res.by_total = [(str(r[0]), int(r[1])) for r in rows]
        res.by_distinct = int(rows[0][2]) if rows else 0
        if not rows:
            return
        p = dict(self.params)
        marks = []
        for i, (label, _) in enumerate(res.by_total):
            p[f"bv_{i}"] = label
            marks.append(f"%(bv_{i})s")
        where = f" AND b IN ({', '.join(marks)})"
        for b, name, v, c in self.q(
            "SELECT b, p, v, c FROM (SELECT b, p, v, c, row_number() OVER (PARTITION BY b, p ORDER BY c DESC, v) AS rn FROM ("
            f"SELECT b, p, v, count(*) AS c FROM ({self.unpivot}) WHERE v IS NOT NULL AND b IN ({', '.join(marks)}) GROUP BY 1, 2, 3)) "
            f"WHERE rn <= {_int(BY_VALUES)}",
            p,
        ):
            res.by_top.setdefault((str(b), name), []).append((str(v), int(c)))
        if self.numeric:
            for r in self.q(self._stats_sql(True, where), p):
                res.by_stats[(str(r[0]), r[1])] = (int(r[2]), float(r[3]), float(r[4]), float(r[5]), float(r[6]))


def _g(x: float) -> str:
    return f"{x:,.6g}"


def _stats_line(s: tuple[int, float, float, float, float]) -> str:
    return f"min {_g(s[1])}, p50 {_g(s[2])}, p95 {_g(s[3])}, max {_g(s[4])}"


def _render_params(
    sc: Scope, plan: cost.Plan, t: Template, by: str | None, r: ParamResult, limit: int, notes: list[str]
) -> str:
    sampled = "" if plan.exact else " (counts are from the sample)"
    out = [
        _how(
            sc,
            plan,
            "exact: every entry in scope matching the template was read and its parameters extracted by its pattern",
            "estimated: whole blocks of entries were read and the template's parameters extracted; values and counts below are from the sample",
        )
    ]
    out += [fmt.sentence(n) for n in [*notes, *plan.notes]]
    out.append(f"{t.template_id}  {fmt.template_text(t.template)}")
    out.append(f"    matching entries: {_num(r.matched)}{sampled}")
    if plan.exact and r.matched.value == 0:
        out.append("    no entry matches this template in this scope.")
        return "\n".join(out)
    for p in t.params:
        out.append("")
        out.append(f"  parameter {p.name} ({p.kind}):")
        if p.name not in r.top:
            out.append("    no values")
            continue
        if p.name in r.stats:
            out.append(f"    {_stats_line(r.stats[p.name])}")
        out.append("    top values: " + ", ".join(f"{v} ({c:,})" for v, c in r.top[p.name]))
        if r.distinct[p.name] > len(r.top[p.name]):
            out.append(f"    showing {len(r.top[p.name])} of {r.distinct[p.name]:,} values")
    if by:
        out.append("")
        out.append(f"  by {by}:")
        for b, n in r.by_total:
            out.append(f"    {b}: {n:,} entries")
            for p in t.params:
                parts = []
                if (b, p.name) in r.by_stats:
                    parts.append(_stats_line(r.by_stats[(b, p.name)]))
                if (b, p.name) in r.by_top:
                    parts.append("top: " + ", ".join(f"{v} ({c:,})" for v, c in r.by_top[(b, p.name)]))
                if parts:
                    out.append(f"        {p.name}: " + "; ".join(parts))
        if r.by_distinct > len(r.by_total):
            out.append(f"    showing {len(r.by_total)} of {r.by_distinct:,} {by} values")
    return "\n".join(out)
