"""count_logs: counts of log entries over one, several or all log tables, grouped by team, component, level,
any other role or column, or a time bucket; optionally only entries whose message contains a text.

This is the aggregation that needs no templates: "how many FATAL entries per team over the whole corpus",
"errors per day for the Cloud API team", "how often does 'timeout' appear per component". Each log table is
counted on its own (exactly, when the cost check allows it; otherwise from a block sample, said so) and the
results are reported together, with a combined line per group when several tables share group values.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from rcagent import format as fmt
from rcagent.catalog.models import LogTable
from rcagent.context import AppContext
from rcagent.errors import UserFacingError
from rcagent.query import cost, sampling, textmatch
from rcagent.query.coverage import untimestamped_note
from rcagent.query.filters import (
    Filters,
    MissingRole,
    TimeRange,
    build_where,
    diagnose_empty,
    parse_time_range,
    role_sql,
    shown_zone,
    time_clause,
)
from rcagent.query.stats import role_columns
from rcagent.setup.sniff import readable
from rcagent.timezones import get_zone
from rcagent.tools.describe import check_text, known_columns
from rcagent.tools.investigate import (
    NAME_OMITTED,
    _TIME,
    _UNIT_NAME,
    _UNIT_SECONDS,
    _filter_columns,
    _group_columns,
    _one,
    omitted_line,
    ordered,
    parse_group_by,
    real_keys,
)

DEFAULT_GROUPS = 25
NARROW = "narrow it: a shorter period (start/end), filters such as level or team, or fewer log tables."


@dataclass
class TableCount:
    lt: LogTable
    plan: cost.Plan | None
    total: fmt.Measured | None
    groups: list[tuple[tuple[str, ...], fmt.Measured]]
    labels: list[str]
    note: str | None = None  # why the table was not counted, or something to know about its count
    asked: str | None = None  # a TOO EXPENSIVE message
    empty_why: list[str] | None = None
    n_groups: int | None = None  # all groups, when only the first ones were fetched


def _scope_text(f: Filters, text: str | None) -> str | None:
    parts = [f"{k} in ({', '.join(repr(w) for w in v)})" if isinstance(v, list) else f"{k}={v!r}" for k, v in f.items()]
    if text:
        parts.append(f"message contains {text!r} (any case)")
    return ", ".join(parts) or None


def _count_one(
    ctx: AppContext,
    lt: LogTable,
    tr: TimeRange,
    f: Filters,
    text: str | None,
    group_by: list[str],
    tz: str,
    confirmed_cost: str | None,
    keep: int | None = None,
) -> TableCount:
    """`keep`: fetch only the first `keep` groups in reading order (exact counts only), with the number of
    all groups, so a grouping with millions of groups costs one scan and not millions of rows here."""
    db = ctx.db
    with readable(f"the source of log table '{lt.name}'"):
        cols = known_columns(db, lt)
        groups = parse_group_by(lt, group_by, cols, tz)
        time_sql, time_params = time_clause(lt, tr, cols)
        match_sql, params = build_where(lt, TimeRange(), f, cols)
        params.update(time_params)
        if text:
            check_text(text)
            text_sql, text_params = textmatch.contains_sql(role_sql(lt, "message"), text)
            match_sql += " AND " + text_sql
            params.update(text_params)
        read = (
            (role_columns(lt.roles.timestamp) if tr.bounded or any(g.startswith("time:") for g in group_by) else [])
            + _filter_columns(lt, f, cols)
            + _group_columns(lt, group_by, cols)
            + (role_columns(lt.roles.message) if text else [])
        )
        _, decision = cost.check(db, lt, tr, read, confirmed_cost)
        labels = [label for label, _ in groups]
        if decision.status == "ask":
            return TableCount(lt, None, None, [], labels, asked=decision.message)
        plan = decision.plan
        note = untimestamped_note(db, lt, tr)
        scope_sql = time_sql + (" AND " + sampling.clause(plan) if plan.sampling else "")
        timeout = cost.run_timeout(plan, ctx.settings.default_timeout_s, ctx.settings.max_timeout_s)
        what = f"counting entries in log table {lt.name}"
        keys = "".join(f", {expr} AS k{i}" for i, (_, expr) in enumerate(groups))
        key_names = [f"k{i}" for i in range(len(groups))]
        blk = [] if plan.exact else ["blk"]
        blk_sel = "" if plan.exact else f", {sampling.block_id_sql(plan)} AS blk"
        gcols = ", ".join(key_names + blk)
        inner = f"SELECT 1 AS one{keys}{blk_sel} FROM {lt.relation} WHERE {scope_sql} AND {match_sql}"
        sql = (
            f"SELECT {gcols}, count(*) AS n FROM ({inner}) GROUP BY {gcols}"
            if gcols
            else f"SELECT count(*) AS n FROM ({inner})"
        )
        if keep is not None and plan.exact and key_names:
            top = _top_groups(db, lt, plan, labels, key_names, inner, params, timeout, what, keep, note, tz)
            if top.total is not None and top.total.value == 0:
                top.empty_why = _why_empty(db, lt, tr, f, cols, text)
            return top
        rows = db.read(sql, params, timeout_s=timeout, what=what, how_to_narrow=NARROW).rows
        per_key: dict[tuple[str, ...], list[tuple[int, int]]] = {}
        all_blocks: dict[int, int] = {}
        for r in rows:
            key = real_keys(tuple(str(x) for x in r[: len(key_names)]), labels, tz)
            b = 0 if plan.exact else int(r[len(key_names)])
            n = int(r[-1])
            per_key.setdefault(key, []).append((b, n))
            all_blocks[b] = all_blocks.get(b, 0) + n
        entries: list[int] = []
        if not plan.exact:
            block_rows = db.read(
                f"SELECT {sampling.block_id_sql(plan)} AS b, count(*) FROM {lt.relation} WHERE {scope_sql} GROUP BY 1",
                params if "text_pattern" not in params else {k: v for k, v in params.items() if k in time_params},
                timeout_s=timeout,
                what=what,
                how_to_narrow=NARROW,
            ).rows
            found = {int(r[0]): int(r[1]) for r in block_rows if r[0] is not None}
            entries = [found.get(i, 0) for i in range(len(plan.groups))]
        total = _one(plan, list(all_blocks.items()), entries)
        measured = [(k, _one(plan, v, entries)) for k, v in per_key.items()]
        by_key = dict(measured)
        measured = [(k, by_key[k]) for k in ordered(list(by_key), labels, {k: m.value for k, m in by_key.items()})]
        empty_why = None
        if plan.exact and total.value == 0:
            empty_why = _why_empty(db, lt, tr, f, cols, text)
        return TableCount(lt, plan, total, measured, labels, note=note, empty_why=empty_why)


def _why_empty(db: Any, lt: LogTable, tr: TimeRange, f: Filters, cols: dict[str, str], text: str | None) -> list[str]:
    """Why an exact count is 0: the period or a filter that matched nothing, as search_logs says it; with a text
    and nothing else to blame, that no entry in scope contains it."""
    why = diagnose_empty(db, lt, tr, f, cols) if (f.items() or tr.bounded) else []
    if not text:
        return why
    # "each filter matches on its own, but not all together" was not checked with the text: leave it out.
    why = [w for w in why if not w.startswith("Each filter matches entries on its own")]
    blamed = [w for w in why if not w.startswith("Whether")]
    return why + ([] if blamed else [f"No entry in this scope contains '{text}' (searched in any case)."])


_EPOCH = datetime(1970, 1, 1)


def _partial_buckets(group_by: list[str], tr: TimeRange) -> list[str]:
    """Time buckets cut by the period: a period that starts (or ends) inside a bucket leaves that bucket holding
    only part of its span, which its label (the bucket's start) does not show."""
    if not tr.bounded:
        return []
    zone = get_zone(tr.tz)
    out: list[str] = []
    for g in group_by:
        m = _TIME.fullmatch(g.strip().lower())
        if m is None:
            continue
        n, unit = int(m.group(1)), m.group(2)
        secs = n * _UNIT_SECONDS[unit]
        monday = 4 * 86400 if unit == "d" and n > 1 else 0  # as investigate._bucket_sql cuts them
        noun = _UNIT_NAME[unit] if n == 1 else f"{n}-{_UNIT_NAME[unit]}"

        def show(dt: datetime, day: bool) -> str:
            return dt.strftime("%Y-%m-%d") if day and dt.time() == datetime.min.time() else dt.strftime("%Y-%m-%d %H:%M")

        for edge, at in (("first", tr.start), ("last", tr.end)):
            if at is None:
                continue
            local = at.astimezone(zone).replace(tzinfo=None)
            since = (local - _EPOCH).total_seconds()
            start = _EPOCH + timedelta(seconds=((since - monday) // secs) * secs + monday)
            if start == local:
                continue
            label = show(start, unit == "d")
            if edge == "first":
                out.append(
                    f"partial bucket: the first {noun} bucket, {label}, holds only entries from {show(local, True)} on "
                    "(the period starts inside it)"
                )
            else:
                out.append(
                    f"partial bucket: the last {noun} bucket, {label}, holds only entries before {show(local, True)} "
                    "(the period ends inside it)"
                )
    return out


def _top_groups(
    db: Any, lt: LogTable, plan: cost.Plan, labels: list[str], key_names: list[str], inner: str,
    params: dict[str, Any], timeout: float, what: str, keep: int, note: str | None, tz: str,
) -> TableCount:
    """The first `keep` groups in the order `ordered` gives, ordered and cut inside SereneDB, plus the next
    NAME_OMITTED ones, so a few left-out time buckets can be named."""
    # The largest `keep` groups (ties by key), then put in reading order here, so a cut never hides the peaks.
    gcols = ", ".join(key_names)
    sql = (
        f"SELECT {gcols}, n, count(*) OVER () AS all_groups, sum(n) OVER () AS all_n "
        f"FROM (SELECT {gcols}, count(*) AS n FROM ({inner}) GROUP BY {gcols}) ORDER BY n DESC, {gcols} "
        f"LIMIT {int(keep) + NAME_OMITTED}"
    )
    rows = db.read(sql, params, timeout_s=timeout, what=what, how_to_narrow=NARROW).rows
    k = len(key_names)
    found = {real_keys(tuple(str(x) for x in r[:k]), labels, tz): fmt.Measured(float(r[k]), True) for r in rows}
    groups = [(key, found[key]) for key in ordered(list(found), labels, {key: m.value for key, m in found.items()})]
    n_groups = int(rows[0][k + 1]) if rows else 0
    total = fmt.Measured(float(rows[0][k + 2]) if rows else 0.0, True)
    return TableCount(lt, plan, total, groups, labels, note=note, n_groups=n_groups)


def _largest(groups: list[tuple[tuple[str, ...], fmt.Measured]], limit: int) -> list[tuple[tuple[str, ...], fmt.Measured]]:
    """The `limit` largest groups, kept in the reading order they come in."""
    if len(groups) <= limit:
        return groups
    keep = {k for k, _ in sorted(groups, key=lambda g: (-g[1].value, g[0]))[:limit]}
    return [g for g in groups if g[0] in keep]


def _left_out(t: TableCount, cut: list[tuple[tuple[str, ...], fmt.Measured]], n_all: int) -> str:
    """What the cut left out: the groups fetched but not shown, and, when only the first groups were fetched,
    the rest from the totals (all groups and all entries are known)."""
    kept = {k for k, _ in cut}
    left = [(k, m) for k, m in t.groups if k not in kept]
    assert t.total is not None
    if len(t.groups) == n_all:
        entries, exact = sum(m.value for _, m in left), all(m.exact for _, m in left)
    else:
        entries, exact = t.total.value - sum(m.value for _, m in cut), t.total.exact
    n_left = n_all - len(cut)
    return omitted_line(t.labels, n_left, entries, exact, left if len(left) == n_left else None, sep=" · ")


def _share(part: fmt.Measured, whole: fmt.Measured | None) -> str:
    if whole is None or not whole.value:
        return ""
    return f", {100 * part.value / whole.value:.1f}%"


def _how(tables: list[TableCount], tr: TimeRange, f: Filters, text: str | None, tz: str, period: str | None) -> str:
    plans = [t.plan for t in tables if t.plan is not None]
    exact = all(p.exact for p in plans)
    kind = (
        "exact count: every entry in scope of each log table was counted inside SereneDB"
        if exact
        else "count per log table: exact where marked exact, else estimated from a block sample (said per table)"
    )
    if any(p.confirmed for p in plans):
        kind += " (run as you confirmed)"
    sample = None if exact else "block sample where marked"
    shown = period or (tr.describe() if tr.bounded else None)
    return fmt.how_measured(kind, shown, _scope_text(f, text), sample, tz=tz)


def _key_text(labels: list[str], key: tuple[str, ...]) -> str:
    if not labels:
        return "all entries"
    return " · ".join(key)


def count_logs(
    ctx: AppContext,
    log_tables: list[str] | None = None,
    group_by: list[str] | None = None,
    start: str | None = None,
    end: str | None = None,
    filters: dict[str, Any] | None = None,
    text: str | None = None,
    limit: int | None = None,
    timezone: str | None = None,
    confirmed_cost: str | None = None,
) -> str:
    parse_time_range(start, end, timezone or "UTC")  # a bad time or zone is explained before any query
    f = Filters.from_dict(filters)
    text = text.strip() if text and text.strip() else None
    group_by = [g for g in (group_by or []) if g and g.strip()]
    if len(group_by) > 3:
        raise UserFacingError("Group by at most three things at once, e.g. ['team', 'level'] or ['component', 'time:1d'].")
    if log_tables:
        tables = [ctx.store.get_log_table(n) for n in dict.fromkeys(log_tables)]
    else:
        tables = ctx.store.list_log_tables()
        if not tables:
            raise UserFacingError("There are no log tables yet; set one up first.")
    shown_limit, cap_note = fmt.limit_and_note(limit, DEFAULT_GROUPS, DEFAULT_GROUPS * ctx.settings.limit_cap)
    # One table: exactly the groups shown. Several: more of each, so the combined lines see the values they share.
    fetch = shown_limit if len(tables) == 1 else shown_limit * 10
    # Each log table is read and shown in its own zone unless one is given.
    ranges = {lt.name: parse_time_range(start, end, shown_zone(lt, timezone)) for lt in tables}
    one_zone = len({r.tz for r in ranges.values()}) == 1
    results: list[TableCount] = []
    for lt in tables:
        tr = ranges[lt.name]
        try:
            results.append(_count_one(ctx, lt, tr, f, text, group_by, tr.tz, confirmed_cost, keep=fetch))
        except MissingRole as exc:
            if len(tables) == 1:
                raise
            results.append(TableCount(lt, None, None, [], [], note=f"not counted: {exc}"))
    tr = ranges[tables[0].name]
    if one_zone:
        return _render(results, tr, f, text, tr.tz, group_by, shown_limit, None, cap_note)
    period = f"{start or 'the beginning'} to {end or 'the end'} in each log table's own time zone" if tr.bounded else None
    return _render(
        results, tr, f, text, "each log table's own time zone (see describe_logs)", group_by, shown_limit, period,
        cap_note,
    )


def _render(
    results: list[TableCount],
    tr: TimeRange,
    f: Filters,
    text: str | None,
    tz: str,
    group_by: list[str],
    limit: int,
    period: str | None,
    cap_note: str | None = None,
) -> str:
    lines = [_how(results, tr, f, text, tz, period)]
    many = len(results) > 1
    if many:
        lines.append(
            f"Counted {len(results)} log tables separately ({', '.join(t.lt.name for t in results)}) and reported "
            "together; the tables are not merged."
        )
    if group_by:
        timed = [g for g in group_by if g.startswith("time:")]
        order = (
            "largest first"
            if not timed
            else "in time order" if len(timed) == len(group_by) else "each series largest first, in time order inside"
        )
        lines.append("grouped by " + ", ".join(group_by) + "; " + order)
        lines += _partial_buckets(group_by, tr)
    for t in results:
        lines.append("")
        if t.asked:
            lines.append(f"Log table {t.lt.name}: TOO EXPENSIVE to count. {t.asked}")
            continue
        if t.total is None:
            lines.append(f"Log table {t.lt.name}: {t.note}")
            continue
        total_text = _num(t.total)
        one = t.total.exact and round(t.total.value) == 1
        lines.append(
            f"Log table {t.lt.name}: {total_text} matching {'entry' if one else 'entries'}" + (" (exact)." if t.total.exact else ".")
        )
        if t.note:
            lines.append(f"  note: {t.note}")
        for n in t.plan.notes if t.plan is not None else ():
            lines.append(f"  note: {n}")
        if t.groups and t.total.value:
            cut = _largest(t.groups, limit)
            n_all = t.n_groups if t.n_groups is not None else len(t.groups)
            if len(cut) < n_all:
                more = cap_note or "raise limit to see more"
                lines.append(f"  showing the {len(cut):,} largest of {n_all:,} groups ({more})")
            for key, m in cut:
                lines.append(f"  {_key_text(t.labels, key)}: {_num(m)}{_share(m, t.total)}")
            if len(cut) < n_all:
                lines.append("  " + _left_out(t, cut, n_all))
        for why in t.empty_why or []:
            lines.append(f"  {why}")
    # Time buckets of tables in different zones are different hours: no combined line for them.
    if many and group_by and (period is None or not any(g.startswith("time:") for g in group_by)):
        combined: dict[tuple[str, ...], float] = {}
        exact = True
        for t in results:
            for key, m in t.groups:
                combined[key] = combined.get(key, 0.0) + m.value
                exact = exact and m.exact
        tables_with = {k: sum(any(g[0] == k for g in t.groups) for t in results) for k in combined}
        shared = [k for k in combined if tables_with[k] > 1]
        partial = any(t.n_groups is not None and t.n_groups > len(t.groups) for t in results)
        if shared:
            lines.append("")
            lines.append(
                "combined over the log tables, for group values found in more than one of them"
                + (" (among each table's largest groups)" if partial else "")
                + ("" if exact else " (sums of estimates: estimates)")
                + ":"
            )
            ranked = sorted(shared, key=lambda k: (-combined[k], k))
            if len(ranked) > limit:
                lines.append(f"  showing {limit:,} of {len(ranked):,} shared values (raise limit to see more)")
            for key in ranked[:limit]:
                lines.append(f"  {' · '.join(key)}: {int(round(combined[key])):,}")
    return "\n".join(lines)


def _num(m: fmt.Measured) -> str:
    """Exact counts as plain numbers (the header says they are exact); estimates with their margin."""
    return f"{round(m.value):,}" if m.exact else fmt.render(m)
