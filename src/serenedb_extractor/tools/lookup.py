"""search_logs: filtered and text search for ad-hoc lookups, cost-checked before it runs."""

from datetime import datetime
from typing import Any

from serenedb_extractor import format as fmt
from serenedb_extractor.catalog.models import LogTable
from serenedb_extractor.context import AppContext
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
    time_clause,
)
from serenedb_extractor.query.stats import role_columns
from serenedb_extractor.setup.paths import pct, sql_literal
from serenedb_extractor.setup.roles import is_temporal, resolve_column, role_column
from serenedb_extractor.setup.sniff import readable
from serenedb_extractor.tools.describe import known_columns, like_pattern

DEFAULT_LIMIT = 50
ORDERS = ("newest", "oldest")

# TEST-ONLY HOOK: SQL appended to the search WHERE (it must start with " AND "). Tests set it to
# force a slow query and check that the timeout cancels it; it is always "" in normal use.
SEARCH_SQL_SUFFIX = ""

FUZZY_NEEDS_INDEX = (
    "fuzzy search needs a search index (see create_index with dry_run for its size and build time); "
    "without one, search for an exact word or phrase (fuzzy=false)."
)
NARROW = (
    "narrow it: a shorter period (start/end), filters such as level or service, or a longer, rarer phrase; "
    "or build a search index (create_index with dry_run)."
)


def _ts_select(lt: LogTable, cols: dict[str, str]) -> str:
    if lt.roles.timestamp is None:
        return "NULL::timestamptz AS occ_ts"
    expr = role_sql(lt, "timestamp")
    typ = cols.get(role_column(lt.roles.timestamp) or "", "").upper()
    if not is_temporal(typ):
        return f"({expr})::varchar AS occ_ts"
    if "WITH TIME ZONE" in typ or typ.startswith("TIMESTAMPTZ"):
        return f"({expr})::timestamptz AS occ_ts"
    return f"({expr})::timestamp AT TIME ZONE {sql_literal(lt.timezone)} AS occ_ts"


def _order_sql(lt: LogTable, order: str) -> str:
    direction = "DESC" if order == "newest" else "ASC"
    keys = [role_sql(lt, r) for r in ("timestamp", "order") if getattr(lt.roles, r) is not None]
    return ("ORDER BY " + ", ".join(f"{k} {direction} NULLS LAST" for k in keys)) if keys else ""


def columns_read(lt: LogTable, f: Filters, cols: dict[str, str], text: str | None) -> list[str]:
    """The columns search_logs reads, once per scan: the count reads the time, the filters and (for a
    text) the message; the listing reads those again plus the shown roles and the order."""
    def of(roles: list[str]) -> list[str]:
        out: list[str] = []
        for r in roles:
            out += role_columns(getattr(lt.roles, r))
        return out

    filter_cols = of([k for k, _ in f.items() if k in FILTER_ROLES])
    filter_cols += [c for k, _ in f.items() if k not in FILTER_ROLES and (c := resolve_column(k, cols))]
    count = of(["timestamp"]) + filter_cols + (of(["message"]) if text else [])
    shown = list(dict.fromkeys(of(list(lt.roles.present())) + filter_cols))
    return count + shown


def _scope_text(f: Filters, text: str | None) -> str | None:
    parts = []
    for key, wanted in f.items():
        parts.append(f"{key} in ({', '.join(repr(w) for w in wanted)})" if isinstance(wanted, list) else f"{key}={wanted!r}")
    if text:
        parts.append(f"message contains {text!r} (any case)")
    return ", ".join(parts) or None


def _show_ts(value: Any, tr: TimeRange) -> str:
    if isinstance(value, datetime):
        return tr.fmt(value)
    return "(no timestamp)" if value is None else str(value)


def _line(lt: LogTable, row: dict[str, Any], tr: TimeRange) -> str:
    roles = " ".join(f"{r}={row[f'occ_{r}']}" for r in FILTER_ROLES if row.get(f"occ_{r}") is not None)
    parts = [_show_ts(row["occ_ts"], tr), occurrence.encode_occurrence(lt, row), roles, fmt.shorten(str(row["occ_msg"] or ""))]
    return "  " + "  ".join(p for p in parts if p)


def _ask(lt: LogTable, tr: TimeRange, f: Filters, text: str | None, tz: str, message: str) -> str:
    head = fmt.how_measured(cost.ASKED_HOW, tr.describe() if tr.bounded else None, _scope_text(f, text), tz=tz)
    return head + "\n" + message


def search_logs(
    ctx: AppContext,
    log_table: str,
    start: str | None = None,
    end: str | None = None,
    filters: dict[str, Any] | None = None,
    text: str | None = None,
    fuzzy: bool = False,
    order: str = "newest",
    limit: int | None = None,
    timezone: str = "UTC",
    confirmed_cost: str | None = None,
) -> str:
    lt = ctx.store.get_log_table(log_table)
    tr = parse_time_range(start, end, timezone)
    f = Filters.from_dict(filters)
    text = text if text else None
    if fuzzy:
        if lt.search_index_name is None:
            raise UserFacingError(FUZZY_NEEDS_INDEX)
        raise UserFacingError("Fuzzy search through the search index is not available yet; search without fuzzy.")
    if order not in ORDERS:
        raise UserFacingError(f"order must be 'newest' or 'oldest', not '{order}'.")
    shown_limit = fmt.clamp_limit(limit, DEFAULT_LIMIT, DEFAULT_LIMIT * ctx.settings.limit_cap)
    db = ctx.db
    with readable(f"the source of log table '{lt.name}'"):
        cols = known_columns(db, lt)
        time_sql, time_params = time_clause(lt, tr, cols)
        match_sql, params = build_where(lt, TimeRange(), f, cols)  # the filters alone
        params.update(time_params)
        if text:
            match_sql += f" AND ({role_sql(lt, 'message')})::varchar ILIKE %(text_pattern)s ESCAPE '\\'"
            params["text_pattern"] = like_pattern(text)
        match_sql += pct(SEARCH_SQL_SUFFIX)
        stats, decision = cost.check(db, lt, tr, columns_read(lt, f, cols, text), confirmed_cost)
        if decision.status == "ask":
            return _ask(lt, tr, f, text, timezone, decision.message)
        plan = decision.plan
        scope_sql = time_sql + (" AND " + sampling.clause(plan) if plan.sampling else "")
        what = f"searching log table {lt.name}" + (f" for '{text}'" if text else "")
        timeout = cost.run_timeout(plan, ctx.settings.default_timeout_s, ctx.settings.max_timeout_s)
        measured = _count(db, lt, plan, scope_sql, match_sql, params, timeout, what)
        total = int(measured.hits or 0) if not plan.exact else int(measured.value)
        rows: list[dict[str, Any]] = []
        if total:
            role_sel = "".join(
                f", ({role_sql(lt, r)})::varchar AS occ_{r}" for r in FILTER_ROLES if getattr(lt.roles, r) is not None
            )
            rows = db.read(
                f"SELECT {_ts_select(lt, cols)}, ({role_sql(lt, 'message')})::varchar AS occ_msg{role_sel}"
                f"{occurrence.select_sql(lt)} FROM {lt.relation} WHERE {scope_sql} AND {match_sql} "
                f"{_order_sql(lt, order)} LIMIT {shown_limit}",
                params,
                timeout_s=timeout,
                what=what,
                how_to_narrow=NARROW,
            ).dicts()
        empty_why = diagnose_empty(db, lt, tr, f, cols) if plan.exact and total == 0 else []
    return _render(lt, tr, f, text, timezone, plan, measured, rows, total, order, empty_why)


def _count(
    db: Any, lt: LogTable, plan: cost.Plan, scope_sql: str, match_sql: str, params: dict[str, Any], timeout: float, what: str
) -> fmt.Measured:
    """Matching entries: an exact count(*), or per sampled block (entries in scope, matches) for an estimate."""
    if plan.exact:
        n = db.read(
            f"SELECT count(*) FROM {lt.relation} WHERE {scope_sql} AND {match_sql}",
            params, timeout_s=timeout, what=what, how_to_narrow=NARROW,
        ).scalar()
        return fmt.Measured(float(n or 0), True)
    per_block = db.read(
        f"SELECT {sampling.block_id_sql(plan)} AS b, count(*) AS n, count(*) FILTER (WHERE {match_sql}) AS y "
        f"FROM {lt.relation} WHERE {scope_sql} GROUP BY 1",
        params, timeout_s=timeout, what=what, how_to_narrow=NARROW,
    ).rows
    found = {int(r[0]): (int(r[1]), int(r[2])) for r in per_block if r[0] is not None}
    blocks = [found.get(i, (0, 0)) for i in range(len(plan.groups))]
    return sampling.block_estimate(blocks, plan.fraction)


def _render(
    lt: LogTable,
    tr: TimeRange,
    f: Filters,
    text: str | None,
    tz: str,
    plan: cost.Plan,
    measured: fmt.Measured,
    rows: list[dict[str, Any]],
    total: int,
    order: str,
    empty_why: list[str],
) -> str:
    if plan.exact:
        kind = "exact search: every entry in scope was checked" + (" (run as you confirmed)" if plan.confirmed else "")
        sample = None
    else:
        kind = "estimated: whole blocks of entries were searched and the number of matching entries scaled up from them"
        upto = "" if plan.rows_exact else "up to "
        sample = (
            f"block sample of {plan.sample_rows or 0:,} of {upto}{plan.population_rows:,} entries "
            f"({len(plan.groups)} whole row group{'' if len(plan.groups) == 1 else 's'} overlapping the period; repeatable)"
        )
    out = [fmt.how_measured(kind, tr.describe() if tr.bounded else None, _scope_text(f, text), sample, tz=tz)]
    out += [fmt.sentence(n) for n in plan.notes]
    if plan.exact:
        out.append(f"{total:,} matching {'entry' if total == 1 else 'entries'} (exact)")
        if total > len(rows):
            out.append(f"showing {len(rows)} of {total:,} entries ({order} first)")
    else:
        out.append(f"matching entries: {fmt.render(measured)}")
        if rows:
            out.append(
                f"showing {len(rows)} of {total:,} matching entries found in the sample ({order} first among them; "
                "matching entries outside the sample are not listed)"
            )
    if not rows and not plan.exact:
        out.append("No matching entries in the sample; matching entries may still exist outside it.")
        return "\n".join(out)
    if not rows:
        lines = empty_why or ([f"No entry in this scope contains '{text}' (searched in any case)."] if text else ["No matching entries."])
        out += lines
        return "\n".join(out)
    out += [_line(lt, r, tr) for r in rows]
    return "\n".join(out)
