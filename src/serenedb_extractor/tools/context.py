"""get_context: the entries shortly before and after one occurrence, cost-checked."""

from datetime import datetime, timedelta
from typing import Any

from serenedb_extractor import format as fmt
from serenedb_extractor.context import AppContext
from serenedb_extractor.errors import UserFacingError
from serenedb_extractor.query import cost, occurrence
from serenedb_extractor.query.filters import (
    FILTER_ROLES,
    Filters,
    TimeRange,
    build_where,
    role_sql,
    time_clause,
)
from serenedb_extractor.query.stats import role_columns
from serenedb_extractor.query.tags import tag_entries, tag_text
from serenedb_extractor.setup.sniff import readable
from serenedb_extractor.tools.describe import context_scopes, known_columns
from serenedb_extractor.tools.lookup import NARROW, _ts_select

DEFAULT_SIDE = 10
SAME_TS_CAP = 200
_TICK = timedelta(microseconds=1)


def _scope_roles(lt: Any, scope: str | list[str] | None, row: dict[str, Any]) -> tuple[list[str], str]:
    """(roles to hold equal to the occurrence's values, how the scope was chosen)."""
    available = context_scopes(lt.roles)
    if scope is None:
        if row.get("occ_trace") is not None and lt.roles.trace:
            return ["trace"], "the narrowest available scope: the same trace"
        both = [r for r in ("service", "host") if getattr(lt.roles, r) and row.get(f"occ_{r}") is not None]
        if both:
            return both, "the narrowest available scope: the same " + " and ".join(both)
        return [], "no narrower scope is available: everything"
    wanted = [scope] if isinstance(scope, str) else list(scope)
    bad = [s for s in wanted if s not in available]
    if bad or not wanted:
        raise UserFacingError(
            f"This log table has no {', '.join(repr(b) for b in bad) or 'scope'} field to scope by. "
            f"The available scopes are: {', '.join(available)}."
        )
    if "everything" in wanted:
        return [], "everything (no scope limit)"
    for r in wanted:
        if row.get(f"occ_{r}") is None:
            raise UserFacingError(f"That entry has no {r} value, so its {r} cannot scope the context; try scope='everything'.")
    return wanted, "the same " + " and ".join(wanted)


def _entry_line(lt: Any, row: dict[str, Any], tr: TimeRange, mark: str, tag: str | None, templates: bool) -> str:
    ts = tr.fmt(row["occ_ts"]) if isinstance(row["occ_ts"], datetime) else str(row["occ_ts"])
    roles = " ".join(f"{r}={row[f'occ_{r}']}" for r in FILTER_ROLES if row.get(f"occ_{r}") is not None)
    parts = [mark, ts, occurrence.encode_occurrence(lt, row), roles, tag_text(tag) if templates else "", fmt.shorten(str(row["occ_msg"] or ""))]
    return " ".join(p for p in parts if p)


def get_context(
    ctx: AppContext,
    log_table: str,
    occurrence: str,  # noqa: A002  (the tool's argument name)
    scope: str | list[str] | None = None,
    window_minutes: float = 5.0,
    before: int = DEFAULT_SIDE,
    after: int = DEFAULT_SIDE,
    filters: dict[str, Any] | None = None,
    timezone: str = "UTC",
    confirmed_cost: str | None = None,
) -> str:
    from serenedb_extractor.query import occurrence as occ_mod

    lt = ctx.store.get_log_table(log_table)
    if window_minutes <= 0:
        raise UserFacingError("window_minutes must be greater than 0.")
    before, after = max(before, 0), max(after, 0)
    where_occ, occ_params = occ_mod.decode_occurrence(lt, occurrence)
    if lt.roles.timestamp is None:
        raise UserFacingError("This log table has no timestamp field, so there is no time window to show around an entry.")
    f = Filters.from_dict(filters)
    db = ctx.db
    unbounded = TimeRange(tz=timezone)
    with readable(f"the source of log table '{lt.name}'"):
        cols = known_columns(db, lt)
        role_sel = "".join(f", ({role_sql(lt, r)})::varchar AS occ_{r}" for r in FILTER_ROLES if getattr(lt.roles, r) is not None)
        select = f"{_ts_select(lt, cols)}, ({role_sql(lt, 'message')})::varchar AS occ_msg{role_sel}{occ_mod.select_sql(lt)}"
        shown_cols: list[str] = []
        for r in ("timestamp", "message", "order", *FILTER_ROLES):
            shown_cols += role_columns(getattr(lt.roles, r))
        what = f"finding the context of occurrence {occurrence} in log table {lt.name}"
        # 1. the occurrence itself (unbounded in time, so it is cost-checked on its own)
        _, decision = cost.check(db, lt, unbounded, shown_cols, confirmed_cost)
        if decision.status == "ask":
            return fmt.how_measured(cost.ASKED_HOW, None, None, tz=timezone) + "\n" + decision.message
        timeout = cost.run_timeout(decision.plan, ctx.settings.default_timeout_s, ctx.settings.max_timeout_s)
        found = db.read(
            f"SELECT {select} FROM {lt.relation} WHERE {where_occ} LIMIT 1",
            occ_params, timeout_s=timeout, what=what, how_to_narrow=NARROW,
        ).dicts()
        if not found:
            raise UserFacingError(f"No entry has the occurrence ID '{occurrence}' in log table '{lt.name}'.")
        occ_row = found[0]
        ts = occ_row["occ_ts"]
        if not isinstance(ts, datetime):
            raise UserFacingError("That entry has no readable timestamp, so there is no time window to show around it.")
        roles, scope_how = _scope_roles(lt, scope, occ_row)
        # 2. the window
        w = timedelta(minutes=window_minutes)
        tr = TimeRange(ts - w, ts + w + _TICK, timezone)
        wcols = shown_cols * 2 + [c for r in roles for c in role_columns(getattr(lt.roles, r))]
        _, decision = cost.check(db, lt, tr, wcols, confirmed_cost)
        if decision.status == "ask":
            return fmt.how_measured(cost.ASKED_HOW, tr.describe(), None, tz=timezone) + "\n" + decision.message
        if not decision.plan.exact:
            return fmt.how_measured(cost.ASKED_HOW, tr.describe(), None, tz=timezone) + "\n" + fmt.refusal(
                "showing the context exactly would read more than the time budget allows",
                ["use a shorter window_minutes", "narrow it with a scope or filters"],
            )
        timeout = cost.run_timeout(decision.plan, ctx.settings.default_timeout_s, ctx.settings.max_timeout_s)
        scope_sql, params = [], {}
        for i, r in enumerate(roles):
            scope_sql.append(f"({role_sql(lt, r)})::varchar = %(s_{i})s")
            params[f"s_{i}"] = occ_row[f"occ_{r}"]
        filt_sql, filt_params = build_where(lt, TimeRange(), f, cols)
        params.update(filt_params)
        extra = " AND ".join(["TRUE", *scope_sql, filt_sql])
        win_sql, win_params = time_clause(lt, tr, cols)
        params.update(win_params)
        ts_expr = role_sql(lt, "timestamp")
        keys = [role_sql(lt, "timestamp")] + ([role_sql(lt, "order")] if lt.roles.order else [])
        t_lo, t_hi = ts.isoformat(), (ts + _TICK).isoformat()
        typ = cols.get(next(iter(role_columns(lt.roles.timestamp)), ""), "").upper()
        naive = "TIME ZONE" not in typ and not typ.startswith("TIMESTAMPTZ") and typ.startswith("TIMESTAMP")
        if naive:
            from zoneinfo import ZoneInfo

            zone = ZoneInfo(lt.timezone)
            t_lo = ts.astimezone(zone).replace(tzinfo=None).isoformat(sep=" ")
            t_hi = (ts + _TICK).astimezone(zone).replace(tzinfo=None).isoformat(sep=" ")
        lit = "timestamp_ns" if typ.endswith("_NS") and naive else ("timestamptz_ns" if typ.endswith("_NS") else ("timestamp" if naive else "timestamptz"))
        if not typ.startswith("TIMESTAMP") and not typ == "DATE":
            ts_expr = f"({ts_expr})::timestamptz"
            lit = "timestamptz"
        params.update({"c_lo": t_lo, "c_hi": t_hi})

        def fetch(cond: str, direction: str, limit: int) -> list[dict[str, Any]]:
            order_by = ", ".join(f"{k} {direction}" for k in keys)
            return db.read(
                f"SELECT {select} FROM {lt.relation} WHERE {win_sql} AND {extra} AND {cond} ORDER BY {order_by} LIMIT {limit}",
                params, timeout_s=timeout, what=what, how_to_narrow=NARROW,
            ).dicts()

        earlier = fetch(f"{ts_expr} < %(c_lo)s::{lit}", "DESC", before)[::-1] if before else []
        same = fetch(f"{ts_expr} >= %(c_lo)s::{lit} AND {ts_expr} < %(c_hi)s::{lit}", "ASC", SAME_TS_CAP)
        later = fetch(f"{ts_expr} >= %(c_hi)s::{lit}", "ASC", after) if after else []
    mine = occurrence.strip()
    ids = [occ_mod.encode_occurrence(lt, r) for r in same]
    pos = ids.index(mine) if mine in ids else None
    others = [r for r, i in zip(same, ids, strict=True) if i != mine]
    split = (pos if pos is not None else 0)
    prior = earlier + others[:split]
    following = others[split:] + later
    prior = prior[-before:] if before else []
    following = following[:after]
    templates = ctx.store.templates(lt.name)
    entries = [(" ", r) for r in prior] + [("→", occ_row)] + [(" ", r) for r in following]
    tags = tag_entries(templates, [str(r["occ_msg"] or "") for _, r in entries]) if templates else [None] * len(entries)
    out = [
        fmt.how_measured(
            f"exact: the nearest entries around the occurrence within ±{window_minutes:g} min",
            f"{tr.fmt(tr.start)} to {tr.fmt(tr.end)} {timezone}"  # type: ignore[arg-type]
            + f" (window ±{window_minutes:g} min around {tr.fmt(ts)})",
            scope_how + (": " + ", ".join(f"{r}={occ_row[f'occ_{r}']}" for r in roles) if roles else ""),
            tz=timezone,
        ),
        *[fmt.sentence(n) for n in decision.plan.notes],
        f"Window: ±{window_minutes:g} min around the occurrence; scope: {scope_how}.",
        f"showing {len(prior)} of up to {before} entries before and {len(following)} of up to {after} entries after the occurrence "
        "(nearest first when more exist); → marks the occurrence",
    ]
    out += [_entry_line(lt, r, tr, mark, tag, bool(templates)) for (mark, r), tag in zip(entries, tags, strict=True)]
    return "\n".join(out)
