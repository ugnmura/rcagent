"""describe_logs: what is set up, what values exist, and why a lookup came back empty."""

from dataclasses import dataclass, field

from serenedb_extractor import format as fmt
from serenedb_extractor.catalog.models import ROLE_FIELDS, FieldRoles, LogTable
from serenedb_extractor.context import AppContext
from serenedb_extractor.db import Database, quote_ident
from serenedb_extractor.errors import UserFacingError
from serenedb_extractor.query.templatematch import _like_pattern
from serenedb_extractor.query.filters import (
    FILTER_ROLES,
    Filters,
    ScanTooExpensive,
    TimeRange,
    build_where,
    data_range,
    diagnose_empty,
    parse_time_range,
    role_sql,
    time_clause,
)
from serenedb_extractor.query import cost, sampling
from serenedb_extractor.query.stats import role_columns
from serenedb_extractor.query import indexcover
from serenedb_extractor.setup.roles import resolve_column, role_column, role_lines
from serenedb_extractor.setup.sniff import readable, relation_columns

SAMPLE_ROWS = 10_000
TOP_N = 8
_TOP_ROLES = ("level", "service", "component")


def context_scopes(roles: FieldRoles) -> list[str]:
    scopes = [s for s, role in (("trace", roles.trace), ("service", roles.service), ("host", roles.host)) if role]
    return scopes + ["everything"]


def known_columns(db: Database, lt: LogTable) -> dict[str, str]:
    return dict(relation_columns(db, lt.relation, lt.source))


def _top_values(db: Database, lt: LogTable, role: str, where: str, params: dict[str, object]) -> str:
    expr = role_sql(lt, role)
    rows = db.read(
        f"SELECT v, c, count(*) OVER () AS n FROM (SELECT e::varchar AS v, count(*) AS c FROM "
        f"(SELECT {expr} AS e FROM {lt.relation} WHERE {where} LIMIT {SAMPLE_ROWS}) GROUP BY 1) "
        f"ORDER BY c DESC, v LIMIT {TOP_N}",
        params,
    ).rows
    vals = [(r[0], r[1]) for r in rows if r[0] is not None]
    if not vals:
        return "no values in the sample"
    distinct = rows[0][2]
    shown = ", ".join(f"{v} ({c:,})" for v, c in vals)
    more = f", … ({distinct} distinct in the sample)" if distinct > len(rows) else ""
    return shown + more


def _top_values_indexed(
    ctx: AppContext, lt: LogTable, role: str, tr: TimeRange, cols: dict[str, str]
) -> tuple[str, str] | None:
    """(text, index name): the role's top values, exact, read from a filter or search index that covers
    it (and the timestamp when the period is bounded); None when no index serves it."""
    expr = getattr(lt.roles, role)
    col = role_column(expr) if expr else None
    if col is None:
        return None
    need = [col] + (role_columns(lt.roles.timestamp) if tr.bounded else [])
    db = ctx.db
    via = indexcover.covering(ctx.store, lt, need)
    if via is None:
        return None
    index = via[1]
    time_sql, params = time_clause(lt, tr, cols)
    ref = role_sql(lt, role)
    rows = db.read(
        f"SELECT t, c, count(*) OVER () AS n FROM (SELECT unnest(ts_dict_agg({ref})) AS t, "
        f"unnest(ts_dict_count({ref})) AS c FROM {index} WHERE {time_sql}) ORDER BY c DESC, t LIMIT {TOP_N}",
        params,
    ).rows
    if not rows:
        return "no values", index
    shown = ", ".join(f"{r[0]} ({int(r[1]):,})" for r in rows)
    more = f", … ({rows[0][2]} distinct)" if rows[0][2] > len(rows) else ""
    return shown + more, index


def _time_range_line(db: Database, lt: LogTable, cols: dict[str, str], tr: TimeRange) -> str:
    if lt.roles.timestamp is None:
        return "time range: unknown (no timestamp field)"
    try:
        rng = data_range(db, lt, cols)
    except ScanTooExpensive as exc:
        return f"time range: not measured ({exc})"
    if rng is None:
        return "time range: no timestamps found"
    if rng.from_stats:
        how = "from Parquet statistics"
    else:
        how = "from a scan of the timestamp column" + (f"; {rng.note}" if rng.note else "")
    return f"time range: {tr.fmt(rng.first)} to {tr.fmt(rng.last)} {tr.tz} ({how})"


def _affordable(db: Database, lt: LogTable, tr: TimeRange, columns: list[str]) -> str | None:
    """None when an exact scan of `columns` fits the cost check, else why it was skipped."""
    stats, decision = cost.check(db, lt, tr, columns)
    if decision.status == "run" and decision.plan.exact:
        return None
    return f"counting would need {cost.cost_text(cost.exact_plan(stats, columns))}; narrow the period, or build a filter index"


@dataclass
class _TopSources:
    """Where the top values shown came from, for the How-measured header."""

    sampled: bool = False
    indexes: set[str] = field(default_factory=set)


def _describe_one(ctx: AppContext, lt: LogTable, tr: TimeRange, top: _TopSources) -> list[str]:
    db = ctx.db
    cols = known_columns(db, lt)
    where, params = build_where(lt, tr, Filters(), cols)
    mode = lt.mode.replace("_", " ")
    out = [f"log table {lt.name}", f"  source: {lt.source} ({lt.source_format})", f"  mode: {mode}"]
    out.append("  roles:")
    out += role_lines(lt.roles, "    ")
    out.append(f"  entries: {lt.row_count:,}" if lt.row_count is not None else "  entries: not counted")
    out.append("  " + _time_range_line(db, lt, cols, tr))
    idx = [n for n in (lt.filter_index_name, lt.search_index_name) if n]
    ts_cols = role_columns(lt.roles.timestamp)
    if lt.mode == "copied":
        skipped = _affordable(db, lt, TimeRange(), ts_cols) if lt.roles.timestamp is not None else None
        if skipped:
            missing = 0
            out.append(f"  entries without a timestamp: not counted ({skipped})")
        elif lt.roles.timestamp is not None:
            missing = db.read(f"SELECT count(*) FROM {lt.relation} WHERE ({role_sql(lt, 'timestamp')}) IS NULL", {}).scalar()
        else:  # no timestamp field at all: every entry lacks one
            missing = db.read(f"SELECT count(*) FROM {lt.relation}", {}).scalar()
        if missing:
            out.append(
                f"  {missing:,} {'entry has' if missing == 1 else 'entries have'} no timestamp "
                "(kept, but not placed in any time range)"
            )
    out.append("  indexes: " + (", ".join(idx) if idx else "none"))
    out.append("  context scopes: " + ", ".join(context_scopes(lt.roles)))
    out.append(f"  catalog: {ctx.store.template_count(lt.name)} templates")
    if tr.bounded:
        skipped = _affordable(db, lt, tr, ts_cols)
        if skipped:
            out.append(f"  entries in {tr.describe()}: not counted ({skipped})")
            n = None
        else:
            n = db.read(f"SELECT count(*) FROM {lt.relation} WHERE {where}", params).scalar()
            out.append(f"  entries in {tr.describe()}: {n:,}")
        if n == 0:
            out += [f"  {line}" for line in diagnose_empty(db, lt, tr, Filters(), cols)]
            return out
    lines: list[str] = []
    used: set[str] = set()
    sampled = False
    for role in _TOP_ROLES:
        if getattr(lt.roles, role) is None:
            lines.append(f"    {role}: absent")
            continue
        via = _top_values_indexed(ctx, lt, role, tr, cols)
        if via is not None:
            used.add(via[1])
            lines.append(f"    {role}: {via[0]}" + ("" if via[0] == "no values" else "  [exact, from the index]"))
        else:
            sampled = True
            lines.append(f"    {role}: {_top_values(db, lt, role, where, params)}")
    top.sampled = top.sampled or sampled
    top.indexes |= used
    period = f" in {tr.describe()}" if tr.bounded else ""
    if sampled:
        label = "sampled — rare values may be missing"
        scope = f"the first {SAMPLE_ROWS:,} entries" + period
        out.append(f"  top values ({label}; from {scope}){' — values marked [exact] come from an index' if used else ''}:")
    else:
        out.append(f"  top values (exact, read from the index {', '.join(sorted(used))}; all entries{period}):")
        lines = [ln.replace("  [exact, from the index]", "") for ln in lines]
    return out + lines


def _resolve_field(lt: LogTable, name: str, cols: dict[str, str]) -> tuple[str, str]:
    """(label, SQL expression) for a role name or a real column."""
    key = name.strip()
    if key.lower() in ROLE_FIELDS and key.lower() not in ("order",):
        return key.lower(), role_sql(lt, key.lower())
    match = resolve_column(key, cols)
    if match is not None:
        return match, quote_ident(match)
    raise UserFacingError(
        f"'{name}' is neither a field role ({', '.join(FILTER_ROLES)}, timestamp, message) nor a column of "
        f"this log table. Columns: {', '.join(cols)}."
    )


def like_pattern(text: str) -> str:
    """An ILIKE pattern (ESCAPE '\\') matching `text` anywhere, with its own % and _ taken literally."""
    return _like_pattern(text)


_EXACT_LOOKUP = "exact distinct-value lookup in one field"
_LOOKUP_NARROW = "narrow it: a shorter period (start/end), or build a filter index (create_index with dry_run)."
_VALUES_CAP = 1000


def _find_values(
    ctx: AppContext, lt: LogTable, find: dict[str, str], tr: TimeRange, confirmed_cost: str | None = None
) -> tuple[str, str | None, list[str]]:
    """(how it was measured, sample label, lines). Cost-checked first; an ask returns the refusal."""
    field = find.get("role_or_column")
    like = find.get("like")
    if not field or like is None or str(like) == "":
        raise UserFacingError("find_values needs both 'role_or_column' (for example service) and 'like' (a word to look for).")
    db = ctx.db
    cols = known_columns(db, lt)
    label, expr = _resolve_field(lt, field, cols)
    time_sql, time_params = time_clause(lt, tr, cols)
    read = role_columns(expr) + (role_columns(lt.roles.timestamp) if tr.bounded else [])
    plain = role_column(expr)
    via = indexcover.covering(ctx.store, lt, read) if plain is not None and read else None
    _, decision = cost.check(
        db, lt, tr, read, confirmed_cost, indexed=read if via else (), index_hints=ctx.estimates.hints(lt)
    )
    if decision.status == "ask":
        return cost.ASKED_HOW, None, [decision.message]
    plan = decision.plan
    params = {**time_params, "like": like_pattern(str(like))}
    timeout = cost.run_timeout(plan, ctx.settings.default_timeout_s, ctx.settings.max_timeout_s)
    what = f"looking up values like '{like}' in {label} of log table {lt.name}"
    if plan.exact and via:  # the index lists every distinct term with its count; no entry is scanned
        found = db.read(
            f"SELECT v, c FROM (SELECT unnest(ts_dict_agg({expr}))::varchar AS v, unnest(ts_dict_count({expr})) AS c "
            f"FROM {via[1]} WHERE {time_sql}) WHERE v ILIKE %(like)s ESCAPE '\\' ORDER BY c DESC, v LIMIT {_VALUES_CAP}",
            params,
            timeout_s=timeout,
            what=what,
            how_to_narrow=_LOOKUP_NARROW,
        ).rows
        rows: list[tuple[str, str]] = [(str(v), f"{int(c):,}") for v, c in found]
    elif plan.exact:
        found = db.read(
            f"SELECT v, count(*) AS c FROM (SELECT ({expr})::varchar AS v FROM {lt.relation} WHERE {time_sql}) "
            f"WHERE v ILIKE %(like)s ESCAPE '\\' GROUP BY v ORDER BY c DESC, v LIMIT {_VALUES_CAP}",
            params,
            timeout_s=timeout,
            what=what,
            how_to_narrow=_LOOKUP_NARROW,
        ).rows
        rows = [(str(v), f"{c:,}") for v, c in found]
    else:
        rows = _sampled_values(db, lt, plan, expr, time_sql, params, timeout, what)
    where_txt = f" between {tr.describe()}" if tr.bounded else ""
    if plan.exact:
        kind, sample = _EXACT_LOOKUP + (" (run as you confirmed)" if plan.confirmed else ""), None
        if via:
            kind = f"{_EXACT_LOOKUP} read from the {via[0]} index {via[1]} (no entry was scanned)"
    else:
        kind = "estimated distinct-value lookup in one field: whole blocks of entries were read, so rare values may be missing"
        upto = "" if plan.rows_exact else "up to "
        sample = f"block sample of {plan.sample_rows or 0:,} of {upto}{plan.population_rows:,} entries"
    out = [f"log table {lt.name}", *("  " + fmt.sentence(n) for n in plan.notes)]
    if not rows:
        out.append(f"  no values like '{like}' in {label}{where_txt}" + ("" if plan.exact else " in the sample") + ".")
        if tr.bounded and plan.exact:
            out += ["  " + line for line in diagnose_empty(db, lt, tr, Filters(), cols)]
        return kind, sample, out
    shown, note = fmt.cut(rows, 50, "values")
    if len(rows) >= _VALUES_CAP:
        note = f"showing {len(shown)} of at least {_VALUES_CAP} values"
    counts = "exact counts" if plan.exact else "found in the sample, estimated counts"
    out.append(f"  values like '{like}' in {label}{where_txt} ({counts}):")
    out += [f"    {v} ({c})" if plan.exact else f"    {v}: {c}" for v, c in shown]
    if note:
        out.append("  " + note)
    return kind, sample, out


def _sampled_values(
    db: Database,
    lt: LogTable,
    plan: cost.Plan,
    expr: str,
    time_sql: str,
    params: dict[str, object],
    timeout: float,
    what: str,
) -> list[tuple[str, str]]:
    """Per value, an estimate from per-block counts (between-block margin), largest first."""
    found = db.read(
        f"SELECT b, v, count(*) AS c FROM (SELECT {sampling.block_id_sql(plan)} AS b, "
        f"CASE WHEN ({expr})::varchar ILIKE %(like)s ESCAPE '\\' THEN ({expr})::varchar END AS v "
        f"FROM {lt.relation} WHERE {time_sql} AND {sampling.clause(plan)}) GROUP BY 1, 2",
        params,
        timeout_s=timeout,
        what=what,
        how_to_narrow=_LOOKUP_NARROW,
    ).rows
    n_block = [0] * len(plan.groups)
    hits: dict[str, list[int]] = {}
    for b, v, c in found:
        if b is None:
            continue
        n_block[int(b)] += int(c)
        if v is not None:
            hits.setdefault(str(v), [0] * len(plan.groups))[int(b)] += int(c)
    measured = {v: sampling.block_estimate(list(zip(n_block, ys, strict=True)), plan.fraction) for v, ys in hits.items()}
    ordered = sorted(measured, key=lambda v: (-measured[v].value, v))[:_VALUES_CAP]
    return [(v, fmt.render(measured[v])) for v in ordered]


def describe_logs(
    ctx: AppContext,
    log_table: str | None = None,
    find_values: dict[str, str] | None = None,
    start: str | None = None,
    end: str | None = None,
    timezone: str = "UTC",
    confirmed_cost: str | None = None,
) -> str:
    tr = parse_time_range(start, end, timezone)
    if log_table is None:
        tables = ctx.store.list_log_tables()
        if not tables:
            return (
                fmt.how_measured("exact, read from the extractor catalog")
                + "\nThere are no log tables yet. Set one up to start analysing logs."
            )
        if find_values:
            raise UserFacingError(f"Say which log table to look in. Known log tables: {', '.join(t.name for t in tables)}.")
    else:
        tables = [ctx.store.get_log_table(log_table)]
    period = tr.describe() if tr.bounded else None
    if find_values:
        lt = tables[0]
        with readable(f"the source of log table '{lt.name}'"):
            kind, sample, lines = _find_values(ctx, lt, find_values, tr, confirmed_cost)
        return fmt.how_measured(kind, period=period, sample=sample, tz=timezone) + "\n" + "\n".join(lines)
    body: list[str] = []
    top = _TopSources()
    for lt in tables:
        with readable(f"the source of log table '{lt.name}'"):
            body += _describe_one(ctx, lt, tr, top)
    via = ", ".join(sorted(top.indexes)) or None
    base = "catalog and metadata, a time range from Parquet statistics or a column scan"
    if top.sampled:
        kind = base + ", and a block sample; top values are sampled" + (
            " (those marked [exact] come from an index)" if via else ""
        ) + ", counts of values found are exact"
        top_sample: str | None = f"top values from a block of {SAMPLE_ROWS:,} entries"
    elif via:
        kind, top_sample = base + "; top values are exact, read from an index", None
    else:
        kind, top_sample = base, None
    header = fmt.how_measured(kind, period=period, sample=top_sample, index_used=via, tz=timezone)
    return header + "\n" + "\n".join(body)
