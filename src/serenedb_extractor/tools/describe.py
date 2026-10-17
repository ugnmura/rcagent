"""describe_logs: what is set up, what values exist, and why a lookup came back empty."""

import psycopg

from serenedb_extractor import format as fmt
from serenedb_extractor.catalog.models import ROLE_FIELDS, FieldRoles, LogTable
from serenedb_extractor.context import AppContext
from serenedb_extractor.db import Database, quote_ident
from serenedb_extractor.errors import UserFacingError
from serenedb_extractor.query.filters import (
    FILTER_ROLES,
    TimeRange,
    build_where,
    data_range,
    diagnose_empty,
    Filters,
    parse_time_range,
    role_expr,
    time_clause,
)
from serenedb_extractor.setup.roles import display_role
from serenedb_extractor.setup.sniff import relation_columns

SAMPLE_ROWS = 10_000
TOP_N = 8
_TOP_ROLES = ("level", "service", "component")
_ROLE_ORDER = ("timestamp", "message", "level", "service", "host", "component", "trace", "order")


def role_lines(roles: FieldRoles, indent: str = "  ") -> list[str]:
    """One line per role, absent ones listed as absent (ruling R1: simple identifiers unquoted)."""
    return [f"{indent}{r}: {display_role(getattr(roles, r))}" for r in _ROLE_ORDER if r in ROLE_FIELDS]


def context_scopes(roles: FieldRoles) -> list[str]:
    scopes = [s for s, role in (("trace", roles.trace), ("service", roles.service), ("host", roles.host)) if role]
    return scopes + ["everything"]


def known_columns(db: Database, lt: LogTable) -> dict[str, str]:
    return dict(relation_columns(db, lt.relation, lt.source))


def _top_values(db: Database, lt: LogTable, role: str, where: str, params: dict[str, object]) -> str:
    expr = str(getattr(lt.roles, role))
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
    src = "from Parquet statistics" if lt.source_format == "parquet" and _plain(lt) else "from the data"
    return f"time range: {tr.fmt(rng[0])} to {tr.fmt(rng[1])} {tr.tz} ({src})"


def _plain(lt: LogTable) -> bool:
    return bool(lt.roles.timestamp) and str(lt.roles.timestamp).startswith('"') and "->>" not in str(lt.roles.timestamp)


def _describe_one(ctx: AppContext, lt: LogTable, tr: TimeRange) -> list[str]:
    db = ctx.db
    cols = known_columns(db, lt)
    where, params = build_where(lt, tr, Filters(), cols)
    src_kind = {"in_place": "in place"}.get(lt.mode, lt.mode)
    out = [f"log table {lt.name}", f"  source: {lt.source} ({lt.source_format}, read {src_kind})", f"  mode: {src_kind}"]
    out.append("  roles:")
    out += role_lines(lt.roles, "    ")
    out.append(f"  rows: {lt.row_count:,}" if lt.row_count is not None else "  rows: not recorded")
    out.append("  " + _time_range_line(db, lt, cols, tr))
    idx = [n for n in (lt.filter_index_name, lt.search_index_name) if n]
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
        return key.lower(), role_expr(lt, key.lower())
    match = [c for c in cols if c == key] or [c for c in cols if c.lower() == key.lower()]
    if len(match) == 1:
        return match[0], quote_ident(match[0])
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
        "catalog, Parquet statistics and a block sample; top values are sampled, counts of values found are exact"
        if not find_values
        else "exact distinct-value lookup in one field",
        period=tr.describe() if tr.bounded else None,
        sample=None if find_values else f"top values from a block of {SAMPLE_ROWS:,} entries",
        tz=timezone,
    )
    body: list[str] = []
    for lt in tables:
        try:
            if find_values:
                body.append(f"log table {lt.name}")
                body += ["  " + line for line in _find_values(ctx, lt, find_values, tr)]
            else:
                body += _describe_one(ctx, lt, tr)
        except psycopg.Error as exc:
            raise UserFacingError(
                f"SereneDB could not read the source of log table '{lt.name}': {' '.join(str(exc).split())[:300]}"
            ) from exc
    return header + "\n" + "\n".join(body)
