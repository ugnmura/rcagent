"""run_sql: the read-only escape hatch. One guarded statement on the reader connection, limited,
timed out, and cost-checked from its query plan before it runs."""

import math
import re
from dataclasses import replace

import psycopg
from sqlglot import exp

from rcagent import format as fmt
from rcagent.catalog.models import LogTable
from rcagent.context import AppContext
from rcagent.db import Database, Rows
from rcagent.errors import UserFacingError
from rcagent.query import cost
from rcagent.query.filters import TimeRange
from rcagent.query.guard import Checked, check_read_only
from rcagent.query.stats import WHOLE, ScopeStats, collect
from rcagent.timezones import is_utc

DEFAULT_LIMIT = 50
MAX_LIMIT = 500
CELL_CHARS = 200
UNKNOWN_SCAN_BYTES_PER_ROW = 100  # a Parquet scan that is not a log table: rows from the plan x this
PLAN_BYTES = "plan"  # the one pseudo-column of the plan-based ScopeStats: the whole predicted read
NARROW = "add a LIMIT, a narrower filter or fewer columns, then try again."
_ROWS = re.compile(r"~\s*([0-9][0-9,]*)\s+rows")


class SqlFailed(UserFacingError):
    def __init__(self, detail: str) -> None:
        super().__init__(f"SereneDB could not run this query: {re.sub(r'\s+', ' ', detail).strip()}")


def execute_user_sql(db: Database, sql: str, timeout: float | None, what: str, zone: str | None = None) -> Rows:
    """Run user SQL on the reader. `params` is None on purpose: the text is never %-parsed (a `%` in
    a LIKE pattern is literal). `prepared=True` sends it over the extended protocol, so SereneDB
    itself refuses a string holding several statements even if the guard missed one. `zone`: the
    session time zone the statement runs in."""
    try:
        return db.read(sql, None, timeout, what, NARROW, prepared=True, zone=zone)
    except psycopg.Error as exc:
        raise SqlFailed(str(exc).splitlines()[0] if str(exc) else "unknown error") from exc


def _read(ctx: AppContext, sql: str, timeout: float | None, what: str, zone: str | None = None) -> Rows:
    return execute_user_sql(ctx.db, sql, timeout, what, zone)


def query_zone(tables: list[LogTable]) -> tuple[str | None, str]:
    """(zone, why) the statement runs in: the log tables' own zone when they share one, so their
    timestamps print, truncate and compare as their own clock; UTC when they differ; None (the
    session's own) when it reads no log table."""
    zones = {t.timezone for t in tables}
    if not zones:
        return None, ""
    if len(zones) == 1:
        return zones.pop(), f"the time zone of {', '.join(t.name for t in tables)}"
    return "UTC", "the log tables' own time zones differ (" + ", ".join(f"{t.name} {t.timezone}" for t in tables) + ")"


def _key(name: str) -> str:
    return name.replace('"', "").lower()


def _referenced(checked: Checked, tables: list[LogTable]) -> tuple[list[LogTable], list[str], bool]:
    """The log tables the query reads, the column names it mentions (lower case), and whether it uses *."""
    by_relation = {_key(t.relation): t for t in tables}
    ctes = {c.alias_or_name.lower() for c in checked.tree.find_all(exp.CTE)}
    hit: dict[str, LogTable] = {}
    for t in checked.tree.find_all(exp.Table):
        full = _key(".".join(p for p in (t.db, t.name) if p))
        if t.name.lower() in ctes and not t.db:
            continue
        lt = by_relation.get(full) or by_relation.get(_key(t.name)) or by_relation.get(f"extractor.{_key(t.name)}")
        if lt is not None:
            hit[lt.name] = lt
    cols = [c.name.lower() for c in checked.tree.find_all(exp.Column) if c.name]
    star = any(True for _ in checked.tree.find_all(exp.Star))
    return list(hit.values()), cols, star


def _table_bytes(stats: ScopeStats, cols: list[str], star: bool) -> float:
    """A full-scan bound over every period: the columns named (all of them for *), else the cheapest column."""
    sizes = {k.lower(): v for k, v in stats.bytes_by_column.items() if k != WHOLE}
    whole = stats.bytes_by_column.get(WHOLE, 0)
    if star:
        return float(sum(sizes.values()) + whole)
    named = [sizes[c] for c in cols if c in sizes]
    if named:
        return float(sum(named) + whole)
    return float(min((v for v in sizes.values() if v > 0), default=0) + whole)


def _predict(ctx: AppContext, checked: Checked, plan_text: str, timeout: float | None) -> tuple[ScopeStats, str]:
    """A conservative scope for the cost check and how it was predicted."""
    db = ctx.db
    tables, cols, star = _referenced(checked, ctx.store.list_log_tables())
    total, rows, remote = 0.0, 0, False
    for lt in tables:
        s = collect(db, lt, TimeRange())
        total += _table_bytes(s, cols, star)
        rows += s.total_rows
        remote = remote or s.remote
    how = "predicted from the query plan (EXPLAIN)"
    if tables:
        how += f" and a full scan of {', '.join(t.name for t in tables)} (all periods, "
        how += "every column" if star else "the columns the query names"
        how += ")"
    scans = [int(m.replace(",", "")) for m in _ROWS.findall(plan_text)]
    if "READ_PARQUET" in plan_text.upper() and not tables:
        guess = max(scans, default=0)
        total += guess * UNKNOWN_SCAN_BYTES_PER_ROW
        rows += guess
        how += f" and the plan's row estimate x {UNKNOWN_SCAN_BYTES_PER_ROW} bytes per row for the Parquet scan"
    stats = ScopeStats(
        total_rows=rows,
        rows_in_range=rows,
        bytes_by_column={PLAN_BYTES: int(total)},
        time_skippable=False,
        remote=remote,
        has_filter_index=False,
        has_search_index=False,
    )
    return stats, how


def _cell(v: object) -> str:
    if v is None:
        return "NULL"
    s = re.sub(r"\s+", " ", str(v)).strip()
    return s if len(s) <= CELL_CHARS else s[:CELL_CHARS] + "…(cut)"


def _table(columns: list[str], rows: list[tuple[object, ...]]) -> str:
    lines = [" | ".join(columns), " | ".join("---" for _ in columns)]
    lines += [" | ".join(_cell(v) for v in r) for r in rows]
    return "\n".join(lines)


SINGLE_ROLE_REFUSAL = (
    "run_sql is switched off: only a reader URL is configured, so SereneDB is not enforcing read-only "
    "access and a query could slip past the checks. Set SERENEDB_WRITER_URL (and make the reader a "
    "SELECT-only role), or set SERENEDB_ALLOW_SQL=1 to allow it anyway."
)


def _timeout(ctx: AppContext, timeout_s: float | None) -> tuple[float, str]:
    """The timeout the query runs with, and a note when the one asked for was cut to the server's maximum.
    Not a number, infinite, zero or negative is refused: none of them is a time to wait."""
    if timeout_s is not None:
        if isinstance(timeout_s, bool) or not isinstance(timeout_s, (int, float)) or not math.isfinite(timeout_s):
            raise UserFacingError("timeout_s must be a number of seconds, e.g. 30 (or leave it out for the default).")
        if timeout_s <= 0:
            raise UserFacingError("timeout_s must be more than 0 seconds, e.g. 30 (or leave it out for the default).")
    most = ctx.settings.max_timeout_s
    if timeout_s is not None and timeout_s > most:
        return most, f"timeout cut to {most:g} s, the server's maximum (asked for {timeout_s:g} s)"
    return ctx.db.effective_timeout(timeout_s), ""


def run_sql(
    ctx: AppContext,
    sql: str,
    limit: int | None = None,
    timeout_s: float | None = None,
    confirmed_cost: str | None = None,
) -> str:
    if ctx.settings.single_role and not ctx.settings.allow_sql:
        raise UserFacingError(SINGLE_ROLE_REFUSAL)
    checked = check_read_only(sql)
    timeout, cut = _timeout(ctx, timeout_s)
    if checked.explain:
        rows = _read(ctx, f"EXPLAIN {checked.sql}", timeout, "explaining the query")
        return fmt.PREFIX + "EXPLAIN only; the query was not run.\n" + "\n".join(str(r[0]) for r in rows.rows)
    shown = fmt.clamp_limit(limit, DEFAULT_LIMIT, MAX_LIMIT)
    plan = _read(ctx, f"EXPLAIN {checked.sql}", timeout, "planning the query")
    plan_text = "\n".join(str(r[0]) for r in plan.rows)
    stats, how = _predict(ctx, checked, plan_text, timeout)
    zone, zone_why = query_zone(_referenced(checked, ctx.store.list_log_tables())[0])
    s = ctx.settings
    # The prediction is a full-scan bound (WHERE clauses are not credited), so only fewer columns lower it.
    decision = cost.decide(
        stats, [PLAN_BYTES], True, s.sample_size, confirmed_cost, max_s=s.max_timeout_s, upper_bound=True,
        ask_options=["name fewer columns: the bound counts every column the query names (all of them for *)"],
    )
    if decision.status == "ask":
        return fmt.PREFIX + f"cost {how}; nothing was run.\n" + decision.message
    run_for = cost.run_timeout(decision.plan, timeout, s.max_timeout_s) if decision.plan.confirmed else timeout
    wrapped = f"SELECT * FROM (\n{checked.sql}\n) q LIMIT {shown + 1}"
    result = _read(ctx, wrapped, run_for, "running the query", zone)
    rows_out = result.rows[:shown]
    note = " ".join(decision.plan.notes)
    times = f"; {cut}" if cut else ""
    if zone is not None and is_utc(zone):
        times += f"; times in {zone}, {zone_why}"
    elif zone is not None:
        times += (
            f"; times in {zone} (not UTC), {zone_why}: timestamps print with their UTC offset, and dates, "
            "date_trunc and time literals are in it too (ts AT TIME ZONE 'UTC' gives UTC)"
        )
    out = [
        fmt.PREFIX
        + f"your SQL ran as a read-only query, cut to {shown} rows; cost {how}; {note or 'within the budget'}{times}."
    ]
    out.append(_table(result.columns, rows_out) if result.columns else "(no result columns)")
    if len(result.rows) > shown:
        # One extra row is fetched to know there is more; the total is not counted (that would
        # run the query again), so the note says "more than", never a number it doesn't have.
        out.append(f"showing {shown} of more than {shown} rows; add a LIMIT, filters or aggregation to see the rest")
    elif not rows_out:
        out.append("no rows")
    else:
        out.append(f"{len(rows_out)} row{'s' if len(rows_out) != 1 else ''}")
    return "\n".join(out)
