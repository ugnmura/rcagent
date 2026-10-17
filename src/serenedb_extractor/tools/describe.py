"""describe_logs: what is set up, what values exist, and why a lookup came back empty."""

from serenedb_extractor import format as fmt
from serenedb_extractor.catalog.models import ROLE_FIELDS, FieldRoles, LogTable
from serenedb_extractor.context import AppContext
from serenedb_extractor.db import Database, quote_ident
from serenedb_extractor.errors import UserFacingError
from serenedb_extractor.query.filters import (
    FILTER_ROLES,
    Filters,
    TimeRange,
    build_where,
    data_range,
    diagnose_empty,
    parse_time_range,
    role_sql,
    time_clause,
)
from serenedb_extractor.setup.roles import resolve_column, role_lines
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


def _time_range_line(db: Database, lt: LogTable, cols: dict[str, str], tr: TimeRange) -> str:
    if lt.roles.timestamp is None:
        return "time range: unknown (no timestamp field)"
    rng = data_range(db, lt, cols)
    if rng is None:
        return "time range: no timestamps found"
    if rng.from_stats:
        how = "from Parquet statistics"
    else:
        how = "from a scan of the timestamp column" + (f"; {rng.note}" if rng.note else "")
    return f"time range: {tr.fmt(rng.first)} to {tr.fmt(rng.last)} {tr.tz} ({how})"


def _describe_one(ctx: AppContext, lt: LogTable, tr: TimeRange) -> list[str]:
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
    if lt.mode == "copied" and lt.roles.timestamp is not None:
        missing = db.read(f"SELECT count(*) FROM {lt.relation} WHERE ({role_sql(lt, 'timestamp')}) IS NULL", {}).scalar()
        if missing:
            out.append(
                f"  {missing:,} {'entry has' if missing == 1 else 'entries have'} no timestamp "
                "(kept, but not placed in any time range)"
            )
    out.append("  indexes: " + (", ".join(idx) if idx else "none"))
    out.append("  context scopes: " + ", ".join(context_scopes(lt.roles)))
    out.append(f"  catalog: {ctx.store.template_count(lt.name)} templates")
    if tr.bounded:
        n = db.read(f"SELECT count(*) FROM {lt.relation} WHERE {where}", params).scalar()
        out.append(f"  entries in {tr.describe()}: {n:,}")
        if n == 0:
            out += [f"  {line}" for line in diagnose_empty(db, lt, tr, Filters(), cols)]
            return out
    label = "sampled — rare values may be missing"
    scope = f"the first {SAMPLE_ROWS:,} entries" + (f" in {tr.describe()}" if tr.bounded else "")
    out.append(f"  top values ({label}; from {scope}):")
    for role in _TOP_ROLES:
        if getattr(lt.roles, role) is None:
            out.append(f"    {role}: absent")
        else:
            out.append(f"    {role}: {_top_values(db, lt, role, where, params)}")
    return out


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


def _like_pattern(text: str) -> str:
    return "%" + text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def _find_values(ctx: AppContext, lt: LogTable, find: dict[str, str], tr: TimeRange) -> list[str]:
    field = find.get("role_or_column")
    like = find.get("like")
    if not field or like is None or str(like) == "":
        raise UserFacingError("find_values needs both 'role_or_column' (for example service) and 'like' (a word to look for).")
    db = ctx.db
    cols = known_columns(db, lt)
    label, expr = _resolve_field(lt, field, cols)
    time_sql, time_params = time_clause(lt, tr, cols)
    cap = 1000
    rows = db.read(
        f"SELECT v, count(*) AS c FROM (SELECT ({expr})::varchar AS v FROM {lt.relation} WHERE {time_sql}) "
        f"WHERE v ILIKE %(like)s ESCAPE '\\' GROUP BY v ORDER BY c DESC, v LIMIT {cap}",
        {**time_params, "like": _like_pattern(str(like))},
    ).rows
    where_txt = f" between {tr.describe()}" if tr.bounded else ""
    if not rows:
        out = [f"no values like '{like}' in {label}{where_txt}."]
        if tr.bounded:
            out += diagnose_empty(db, lt, tr, Filters(), cols)
        return out
    shown, note = fmt.cut(rows, 50, "values")
    if len(rows) >= cap:
        note = f"showing {len(shown)} of at least {cap} values"
    out = [f"values like '{like}' in {label}{where_txt} (exact counts):"]
    out += [f"  {v} ({c:,})" for v, c in shown]
    if note:
        out.append(note)
    return out


def describe_logs(
    ctx: AppContext,
    log_table: str | None = None,
    find_values: dict[str, str] | None = None,
    start: str | None = None,
    end: str | None = None,
    timezone: str = "UTC",
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
    header = fmt.how_measured(
        "catalog and metadata, a time range from Parquet statistics or a column scan, and a block sample; top values are sampled, counts of values found are exact"
        if not find_values
        else "exact distinct-value lookup in one field",
        period=tr.describe() if tr.bounded else None,
        sample=None if find_values else f"top values from a block of {SAMPLE_ROWS:,} entries",
        tz=timezone,
    )
    body: list[str] = []
    for lt in tables:
        with readable(f"the source of log table '{lt.name}'"):
            if find_values:
                body.append(f"log table {lt.name}")
                body += ["  " + line for line in _find_values(ctx, lt, find_values, tr)]
            else:
                body += _describe_one(ctx, lt, tr)
    return header + "\n" + "\n".join(body)
