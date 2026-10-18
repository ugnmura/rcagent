"""get_context: the entries shortly before and after one occurrence, cost-checked."""

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Any

from rcagent import format as fmt
from rcagent.catalog.models import LogTable
from rcagent.context import AppContext
from rcagent.db import Database
from rcagent.errors import UserFacingError
from rcagent.query import cost
from rcagent.query import occurrence as occ_mod
from rcagent.query.filters import (
    FILTER_ROLES,
    Filters,
    TimeRange,
    build_where,
    role_sql,
    shown_zone,
    time_clause,
    ts_compare,
)
from rcagent.query.stats import ScopeStats, collect, role_columns
from rcagent.query.tags import tag_entries, tag_text
from rcagent.setup.sniff import readable
from rcagent.tools.describe import context_scopes, known_columns
from rcagent.tools.trend import _filters_text
from rcagent.tools.lookup import NARROW, ts_select

DEFAULT_SIDE = 10
SAME_TS_CAP = 200
_TICK = timedelta(microseconds=1)  # timestamps come back with microsecond precision

MAX_SIDE = 200  # entries shown at most on each side of the occurrence
MAX_WINDOW_MINUTES = 366 * 24 * 60


@dataclass(frozen=True)
class _Scope:
    roles: list[str]  # roles held equal to the occurrence's values (empty: everything)
    how: str


def _choose_scope(lt: LogTable, scope: str | list[str] | None, row: dict[str, Any]) -> _Scope:
    """The context scope: the default is the narrowest available one."""
    available = context_scopes(lt.roles)
    if scope is None:
        if row.get("occ_trace") is not None and lt.roles.trace:
            return _Scope(["trace"], "the narrowest available context scope: the same trace")
        both = [r for r in ("service", "host") if getattr(lt.roles, r) and row.get(f"occ_{r}") is not None]
        if both:
            return _Scope(both, "the narrowest available context scope: the same " + " and ".join(both))
        return _Scope([], "no narrower context scope is available: everything")
    wanted = [scope] if isinstance(scope, str) else list(scope)
    bad = [s for s in wanted if s not in available]
    if not wanted:
        raise UserFacingError(f"Give a scope, or leave it out for the narrowest one. The available scopes are: {', '.join(available)}.")
    if bad:
        raise UserFacingError(
            f"This log table has no {', '.join(repr(b) for b in bad)} field to scope by. "
            f"The available scopes are: {', '.join(available)}."
        )
    if "everything" in wanted:
        if len(wanted) > 1:
            raise UserFacingError("scope 'everything' means no limit, so it can't be combined with other scopes; give one or the other.")
        return _Scope([], "everything (no scope limit)")
    for r in wanted:
        if row.get(f"occ_{r}") is None:
            raise UserFacingError(f"That entry has no {r} value, so its {r} cannot scope the context; try scope='everything'.")
    return _Scope(wanted, "the same " + " and ".join(wanted))


def _exact_only(stats: ScopeStats) -> ScopeStats:
    """A context must be exact: never let the cost check fall back to a sample."""
    return replace(stats, can_sample=False, groups=())


def _decide(ctx: AppContext, stats: ScopeStats, columns: list[str], confirmed: str | None, options: list[str]) -> cost.Decision:
    s = ctx.settings
    return cost.decide(
        _exact_only(stats), columns, True, s.sample_size, confirmed, max_s=s.max_timeout_s, ask_options=options
    )


def _stopped(tr: TimeRange, decision: cost.Decision, tz: str, what: str) -> str | None:
    """The reply when the cost check did not allow the exact read (an ask with its token), else None."""
    if decision.status == "run":
        assert decision.plan.exact  # _exact_only: a context is never sampled
        return None
    head = fmt.how_measured(cost.ASKED_HOW, tr.describe() if tr.bounded else None, None, tz=tz)
    return head + "\n" + decision.message.replace("TOO EXPENSIVE: ", f"TOO EXPENSIVE: {what} ", 1)


def entry_id_is_key(db: Database, lt: LogTable) -> bool:
    """Whether the copied table's entry_id is its primary key, from the table metadata. Setup makes it
    one only when setup added the column itself; a source that brought its own entry_id has no key."""
    schema, _, table = lt.relation.rpartition(".")
    found = db.read(
        "SELECT count(*) FROM information_schema.table_constraints tc "
        "JOIN information_schema.key_column_usage k ON k.constraint_name = tc.constraint_name "
        "AND k.table_schema = tc.table_schema AND k.table_name = tc.table_name "
        "WHERE tc.constraint_type = 'PRIMARY KEY' AND tc.table_schema = %(s)s AND tc.table_name = %(t)s "
        "AND k.column_name = 'entry_id'",
        {"s": schema.strip('"'), "t": table.strip('"')},
        what=f"reading the key of {lt.name}",
    ).scalar()
    return bool(found)


def _lookup_scope(lt: LogTable, stats: ScopeStats, params: dict[str, Any], keyed: bool = False) -> tuple[ScopeStats, str]:
    """What finding the occurrence's own row reads, and SQL that keeps the read to it.

    - one in-place Parquet file, `<file>#<row>`: only the row group holding that row (its
      `file_row_number` range, which SereneDB prunes on, as the block sampler does);
    - a copied table, `e:<n>`, whose entry_id is its primary key (`keyed`): a key lookup of one entry;
    - anything else (several files, JSON, a table's `pk:` order column, a copied entry_id that is not
      a key): every entry is read to find it, priced as such."""
    k = occ_mod.kind(lt)
    if k == "file" and stats.can_sample:
        row = int(params["occ_row"])
        for g in stats.groups:
            if g.first_row <= row < g.first_row + g.rows:
                one = replace(stats, rows_in_range=g.rows, bytes_by_column=dict(g.bytes_by_column), groups=(g,))
                return one, f" AND file_row_number BETWEEN {int(g.first_row)} AND {int(g.first_row + g.rows - 1)}"
        given = str(params.get("occ_file") or "")
        if given.startswith("%/"):  # a bare file name, matched in any folder
            given = given[2:].replace("\\_", "_").replace("\\%", "%").replace("\\\\", "\\")
        raise UserFacingError(f"No entry has the occurrence ID '{given}#{row}' in log table '{lt.name}'.")
    if k == "entry" and keyed:
        per_row = {c: -(-b // max(stats.total_rows, 1)) for c, b in stats.bytes_by_column.items()}
        return replace(stats, rows_in_range=1, bytes_by_column=per_row), ""
    return stats, ""


def _select(lt: LogTable, cols: dict[str, str]) -> str:
    role_sel = "".join(f", ({role_sql(lt, r)})::varchar AS occ_{r}" for r in FILTER_ROLES if getattr(lt.roles, r) is not None)
    return f"{ts_select(lt, cols)}, ({role_sql(lt, 'message')})::varchar AS occ_msg{role_sel}{occ_mod.select_sql(lt)}"


BOTH_STEPS = "finding the occurrence and showing its context (one confirmation covers both steps)"


def _scope_roles_bound(lt: LogTable, scope: str | list[str] | None) -> list[str]:
    """Every role the context scope may hold equal, before the occurrence is known: the default can
    pick the trace or the service and host, an explicit scope names its own."""
    if scope is None:
        wanted = ["trace", "service", "host"]
    else:
        wanted = [scope] if isinstance(scope, str) else list(scope)
    return [r for r in wanted if r in FILTER_ROLES and getattr(lt.roles, r) is not None]


def _both_steps(ctx: AppContext, lt: LogTable, lookup: ScopeStats, shown_cols: list[str], scope_roles: list[str],
                confirmed: str | None) -> cost.Decision:
    """The lookup and the window priced as one cost, for when the lookup alone is over budget: the
    window is bounded by every entry of the source (its time range is not known before the lookup),
    so one confirmation covers both steps and asks never alternate between them."""
    s = ctx.settings
    whole = collect(ctx.db, lt, TimeRange())
    wcols = shown_cols * 2 + [c for r in scope_roles for c in role_columns(getattr(lt.roles, r))]
    parts = {"lookup": cost.exact_plan(lookup, shown_cols), "window": cost.exact_plan(whole, wcols)}
    combined = ScopeStats(
        whole.total_rows, whole.total_rows, {k: int(p.bytes) for k, p in parts.items()}, False, whole.remote,
        whole.has_filter_index, whole.has_search_index,
    )
    # Each step runs as its own queries: only a step beyond the maximum query time can't be run.
    max_s = s.max_timeout_s if max(p.seconds for p in parts.values()) > s.max_timeout_s else None
    return cost.decide(combined, list(parts), True, s.sample_size, confirmed, max_s=max_s, ask_options=[], upper_bound=True)


def _fetch_occurrence(
    ctx: AppContext, lt: LogTable, occ: str, select: str, shown_cols: list[str], scope_roles: list[str],
    confirmed: str | None, tz: str,
) -> tuple[dict[str, Any], cost.Decision | None] | str:
    """The occurrence's row, with the confirmed decision covering the window too when the two steps
    were priced as one; or the reply text when the cost check stopped the lookup."""
    where, params = occ_mod.decode_occurrence(lt, occ)
    what = f"finding the context of occurrence {occ} in log table {lt.name}"
    whole = TimeRange(tz=tz)
    keyed = occ_mod.kind(lt) == "entry" and entry_id_is_key(ctx.db, lt)
    stats, keep = _lookup_scope(lt, collect(ctx.db, lt, whole), params, keyed)
    decision = _decide(ctx, stats, shown_cols, None, [])
    covered: cost.Decision | None = None
    if decision.status != "run":
        covered = _both_steps(ctx, lt, stats, shown_cols, scope_roles, confirmed)
        if (stop := _stopped(whole, covered, tz, BOTH_STEPS)) is not None:
            return stop
        decision = cost.Decision("run", replace(cost.exact_plan(_exact_only(stats), shown_cols), confirmed=True))
    timeout = cost.run_timeout(decision.plan, ctx.settings.default_timeout_s, ctx.settings.max_timeout_s)
    rows = ctx.db.read(
        f"SELECT {select} FROM {lt.relation} WHERE {where}{keep} LIMIT 1", params,
        timeout_s=timeout, what=what, how_to_narrow=NARROW,
    ).dicts()
    if not rows:
        raise UserFacingError(f"No entry has the occurrence ID '{occ}' in log table '{lt.name}'.")
    return rows[0], covered


SKIPPED = "skipped"  # the nearest entry outside the window was not looked up: too large a read


@dataclass
class _Window:
    prior: list[dict[str, Any]]
    following: list[dict[str, Any]]
    plan: cost.Plan
    # When a side has fewer entries than asked: the nearest entry's time outside the window, None for none,
    # SKIPPED when not looked up; "" when not needed.
    nearest_before: datetime | None | str = ""
    nearest_after: datetime | None | str = ""


def _fetch_window(
    ctx: AppContext, lt: LogTable, cols: dict[str, str], select: str, shown_cols: list[str], occ: str,
    occ_row: dict[str, Any], scope: _Scope, f: Filters, tr: TimeRange, before: int, after: int, confirmed: str | None,
    covered: cost.Decision | None = None,
) -> _Window | str:
    """The nearest entries either side of the occurrence, or the reply text when the cost check stopped it.
    `covered`: the confirmed price of lookup and window together, which already approves this read."""
    db, ts = ctx.db, occ_row["occ_ts"]
    wcols = shown_cols * 2 + [c for r in scope.roles for c in role_columns(getattr(lt.roles, r))]
    stats = collect(db, lt, tr)
    # A smaller window only helps where the time range skips row groups and this one spans several.
    options = (
        ["a smaller window_minutes (fewer row groups to read)"]
        if stats.time_skippable and (not stats.can_sample or len(stats.groups) > 1)
        else []
    )
    if covered is not None:  # bounded by the whole source, which the confirmed total already priced
        decision = cost.Decision("run", replace(cost.exact_plan(stats, wcols), confirmed=True, notes=covered.plan.notes))
    else:
        decision = _decide(ctx, stats, wcols, confirmed, options)
    if (stop := _stopped(tr, decision, tr.tz, "showing the context of the occurrence")) is not None:
        return stop
    timeout = cost.run_timeout(decision.plan, ctx.settings.default_timeout_s, ctx.settings.max_timeout_s)
    conds = ["TRUE"]
    params: dict[str, Any] = {}
    for i, r in enumerate(scope.roles):
        conds.append(f"({role_sql(lt, r)})::varchar = %(s_{i})s")
        params[f"s_{i}"] = occ_row[f"occ_{r}"]
    filt_sql, filt_params = build_where(lt, TimeRange(), f, cols)
    win_sql, win_params = time_clause(lt, tr, cols)
    params.update(filt_params | win_params)
    base = " AND ".join([win_sql, *conds, filt_sql])
    keys = [role_sql(lt, "timestamp")] + ([role_sql(lt, "order")] if lt.roles.order else [])
    what = f"finding the context of occurrence {occ} in log table {lt.name}"

    def fetch(cond: str, cond_params: dict[str, Any], direction: str, limit: int) -> list[dict[str, Any]]:
        order_by = ", ".join(f"{k} {direction}" for k in keys)
        return db.read(
            f"SELECT {select} FROM {lt.relation} WHERE {base} AND {cond} ORDER BY {order_by} LIMIT %(lim)s",
            {**params, **cond_params, "lim": limit}, timeout_s=timeout, what=what, how_to_narrow=NARROW,
        ).dicts()

    lt_sql, lt_p = ts_compare(lt, "<", ts, "c_lo", cols)
    ge_sql, ge_p = ts_compare(lt, ">=", ts, "c_lo", cols)
    same_hi_sql, same_hi_p = ts_compare(lt, "<", ts + _TICK, "c_hi", cols)
    later_sql, later_p = ts_compare(lt, ">=", ts + _TICK, "c_hi", cols)
    earlier = fetch(lt_sql, lt_p, "DESC", before)[::-1] if before else []
    same = fetch(f"{ge_sql} AND {same_hi_sql}", ge_p | same_hi_p, "ASC", SAME_TS_CAP)
    later = fetch(later_sql, later_p, "ASC", after) if after else []
    mine = occ_mod.encode_occurrence(lt, occ_row)  # its full ID, also when it was given as just the file name
    ids = [occ_mod.encode_occurrence(lt, r) for r in same]
    split = ids.index(mine) if mine in ids else 0
    others = [r for r, i in zip(same, ids, strict=True) if i != mine]
    prior = (earlier + others[:split])[-before:] if before else []
    following = (others[split:] + later)[:after]
    win = _Window(prior, following, decision.plan)
    # Fewer entries than asked on a side: the window ran out, so say when the nearest one outside it is.
    scoped = " AND ".join([*conds, filt_sql])
    scoped_params = {k: v for k, v in params.items() if k not in win_params}
    if before and len(prior) < before:
        win.nearest_before = _nearest(ctx, lt, cols, wcols, scoped, scoped_params, TimeRange(None, tr.start, tr.tz), "DESC", what)
    if after and len(following) < after:
        win.nearest_after = _nearest(ctx, lt, cols, wcols, scoped, scoped_params, TimeRange(tr.end, None, tr.tz), "ASC", what)
    return win


def _nearest(
    ctx: AppContext, lt: LogTable, cols: dict[str, str], wcols: list[str], scoped: str, params: dict[str, Any],
    side: TimeRange, direction: str, what: str,
) -> datetime | None | str:
    """The time of the nearest entry in scope on one side outside the window: a datetime, None when there is
    none, or SKIPPED when the cost check does not allow reading that side (no confirmation is asked for it)."""
    decision = _decide(ctx, collect(ctx.db, lt, side), wcols, None, [])
    if decision.status != "run":
        return SKIPPED
    timeout = cost.run_timeout(decision.plan, ctx.settings.default_timeout_s, ctx.settings.max_timeout_s)
    side_sql, side_params = time_clause(lt, side, cols, prefix="n")
    rows = ctx.db.read(
        f"SELECT {ts_select(lt, cols)} FROM {lt.relation} WHERE {side_sql} AND {scoped} "
        f"ORDER BY {role_sql(lt, 'timestamp')} {direction} LIMIT 1",
        {**params, **side_params}, timeout_s=timeout, what=what, how_to_narrow=NARROW,
    ).rows
    found = rows[0][0] if rows else None
    return found if isinstance(found, datetime) else None


def _span(d: timedelta) -> str:
    """A distance in time in the largest unit that keeps it readable."""
    s = abs(d.total_seconds())
    if s >= 2 * 86400:
        return f"{s / 86400:,.0f} days"
    if s >= 2 * 3600:
        return f"{s / 3600:,.0f} h"
    if s >= 120:
        return f"{s / 60:,.0f} min"
    return f"{s:,.0f} s" if s >= 1 else f"{s:.3g} s"


def _nearest_line(found: datetime | None | str, ts: datetime, tr: TimeRange, earlier: bool) -> str:
    word = "earlier" if earlier else "later"
    if found is SKIPPED:
        return f"{word} entries in this scope outside the window were not looked up (too large a read); widen window_minutes to see them"
    if found is None:
        return f"none {word} in this scope"
    assert isinstance(found, datetime)
    return (
        f"the nearest {word} entry in this scope is {_span(found - ts)} {'before' if earlier else 'after'} "
        f"({tr.fmt(found)})"
    )


def _entry_line(lt: LogTable, row: dict[str, Any], tr: TimeRange, mark: str, tag: str) -> str:
    ts = tr.fmt(row["occ_ts"]) if isinstance(row["occ_ts"], datetime) else str(row["occ_ts"])
    roles = " ".join(f"{r}={row[f'occ_{r}']}" for r in FILTER_ROLES if row.get(f"occ_{r}") is not None)
    parts = [mark, ts, occ_mod.encode_occurrence(lt, row), roles, tag, fmt.entry_text(str(row["occ_msg"] or ""))]
    return " ".join(p for p in parts if p)


def _minutes(m: float) -> str:
    return f"{m:,.0f}" if float(m).is_integer() else f"{m:,g}"


def _render(
    ctx: AppContext, lt: LogTable, tr: TimeRange, ts: datetime, window_minutes: float, scope: _Scope,
    occ_row: dict[str, Any], win: _Window, before: int, after: int, f: Filters,
) -> str:
    templates = ctx.store.templates(lt.name)
    entries = [(" ", r) for r in win.prior] + [("→", occ_row)] + [(" ", r) for r in win.following]
    tags = tag_entries(templates, [str(r["occ_msg"] or "") for _, r in entries]) if templates else []
    held = ", ".join(f"{r}={occ_row[f'occ_{r}']}" for r in scope.roles)
    assert tr.start is not None and tr.end is not None
    out = [
        fmt.how_measured(
            f"exact: the nearest entries around the occurrence within ±{_minutes(window_minutes)} min",
            f"{tr.fmt(tr.start)} to {tr.fmt(tr.end)} {tr.tz} (window ±{_minutes(window_minutes)} min around {tr.fmt(ts)})",
            "; ".join(x for x in (scope.how + (": " + held if held else ""), _filters_text(f)) if x),
            tz=tr.tz,
        ),
        *[fmt.sentence(n) for n in win.plan.notes],
        f"Window: ±{_minutes(window_minutes)} min around the occurrence; context scope: {scope.how}.",
        f"showing {len(win.prior)} of up to {before} entries before and {len(win.following)} of up to {after} entries after "
        "the occurrence (nearest first when more exist); → marks the occurrence",
    ]
    for found, earlier in ((win.nearest_before, True), (win.nearest_after, False)):
        if found != "":
            out.append(fmt.sentence(_nearest_line(found, ts, tr, earlier)))
    out += [_entry_line(lt, r, tr, mark, tag_text(tags[i]) if tags else "") for i, (mark, r) in enumerate(entries)]
    return "\n".join(out)


def get_context(
    ctx: AppContext,
    log_table: str,
    occurrence: str,
    scope: str | list[str] | None = None,
    window_minutes: float = 5.0,
    before: int = DEFAULT_SIDE,
    after: int = DEFAULT_SIDE,
    filters: dict[str, Any] | None = None,
    timezone: str | None = None,
    confirmed_cost: str | None = None,
) -> str:
    lt = ctx.store.get_log_table(log_table)
    timezone = shown_zone(lt, timezone)
    if not (0 < window_minutes <= MAX_WINDOW_MINUTES):  # also refuses NaN
        raise UserFacingError(f"window_minutes must be more than 0 and at most {MAX_WINDOW_MINUTES:,} (a year).")
    if before < 0 or after < 0 or before > MAX_SIDE or after > MAX_SIDE:
        raise UserFacingError(f"before and after are numbers of entries to show: 0 to {MAX_SIDE} each.")
    occ_mod.decode_occurrence(lt, occurrence)  # a malformed ID is explained before any query
    if lt.roles.timestamp is None:
        raise UserFacingError("This log table has no timestamp field, so there is no time window to show around an entry.")
    f = Filters.from_dict(filters)
    with readable(f"the source of log table '{lt.name}'"):
        cols = known_columns(ctx.db, lt)
        select = _select(lt, cols)
        shown_cols: list[str] = []
        for r in ("timestamp", "message", "order", *FILTER_ROLES):
            shown_cols += role_columns(getattr(lt.roles, r))
        found = _fetch_occurrence(
            ctx, lt, occurrence, select, shown_cols, _scope_roles_bound(lt, scope), confirmed_cost, timezone
        )
        if isinstance(found, str):
            return found
        occ_row, covered = found
        ts = occ_row["occ_ts"]
        if not isinstance(ts, datetime):
            raise UserFacingError("That entry has no readable timestamp, so there is no time window to show around it.")
        chosen = _choose_scope(lt, scope, occ_row)
        w = timedelta(minutes=window_minutes)
        tr = TimeRange(ts - w, ts + w + _TICK, timezone)
        win = _fetch_window(ctx, lt, cols, select, shown_cols, occurrence, occ_row, chosen, f, tr, before, after, confirmed_cost, covered)
        if isinstance(win, str):
            return win
    return _render(ctx, lt, tr, ts, window_minutes, chosen, occ_row, win, before, after, f)
