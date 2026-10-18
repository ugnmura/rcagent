"""search_logs: filtered and text search for ad-hoc lookups, cost-checked before it runs."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from serenedb_extractor import format as fmt
from serenedb_extractor.catalog.models import LogTable
from serenedb_extractor.context import AppContext
from serenedb_extractor.errors import UserFacingError
from serenedb_extractor.query import cost, occurrence, sampling
from serenedb_extractor.query.coverage import untimestamped_note
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
    ts_compare,
)
from serenedb_extractor.query.stats import role_columns
from serenedb_extractor.query.tags import tag_entries, tag_text
from serenedb_extractor.setup import indexes
from serenedb_extractor.query import indexcover
from serenedb_extractor.setup.paths import pct, sql_literal
from serenedb_extractor.setup.roles import HELPER_COLUMNS, is_temporal, resolve_column, role_column
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
WHOLE_WORDS = "whole words only — fragments like 'disk' inside 'diskfull' aren't matched"
NARROW = (
    "narrow it: a shorter period (start/end), filters such as level or service, or a longer, rarer phrase; "
    "or build a search index (create_index with dry_run)."
)


def ts_select(lt: LogTable, cols: dict[str, str]) -> str:
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


def _scope_text(f: Filters, text: str | None, how: str = "contains") -> str | None:
    parts = []
    for key, wanted in f.items():
        parts.append(f"{key} in ({', '.join(repr(w) for w in wanted)})" if isinstance(wanted, list) else f"{key}={wanted!r}")
    if text:
        parts.append(f"message {how} {fmt.shorten(text, 200)!r} (any case)")
    return ", ".join(parts) or None


def _show_ts(value: Any, tr: TimeRange) -> str:
    if isinstance(value, datetime):
        return tr.fmt(value)
    return "(no timestamp)" if value is None else str(value)


def _line(lt: LogTable, row: dict[str, Any], tr: TimeRange, tag: str = "") -> str:
    roles = " ".join(f"{r}={row[f'occ_{r}']}" for r in FILTER_ROLES if row.get(f"occ_{r}") is not None)
    try:
        occ = occurrence.encode_occurrence(lt, row)
    except KeyError:  # an entry found through the index that could not be placed in the source again
        occ = "(occurrence ID not available)"
    parts = [_show_ts(row["occ_ts"], tr), occ, roles, tag, fmt.entry_text(str(row["occ_msg"] or ""))]
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
    timezone: str | None = None,
    confirmed_cost: str | None = None,
) -> str:
    lt = ctx.store.get_log_table(log_table)
    timezone = shown_zone(lt, timezone)
    tr = parse_time_range(start, end, timezone)
    f = Filters.from_dict(filters)
    text = text if text else None
    if fuzzy:
        if lt.search_index_name is None:
            raise UserFacingError(FUZZY_NEEDS_INDEX)
        if not text:
            raise UserFacingError("Fuzzy search needs the text to look for (text=...).")
    if order not in ORDERS:
        raise UserFacingError(f"order must be 'newest' or 'oldest', not '{order}'.")
    shown_limit = fmt.clamp_limit(limit, DEFAULT_LIMIT, DEFAULT_LIMIT * ctx.settings.limit_cap)
    db = ctx.db
    with readable(f"the source of log table '{lt.name}'"):
        cols = known_columns(db, lt)
        ix = _index_path(ctx, lt, f, text, fuzzy, cols)
        if ix is not None and ix.fuzzy:
            return _search_via_index(ctx, lt, tr, f, text, ix, order, shown_limit, timezone, confirmed_cost, cols)
        time_sql, time_params = time_clause(lt, tr, cols)
        match_sql, params = build_where(lt, TimeRange(), f, cols)  # the filters alone
        params.update(time_params)
        if text:
            match_sql += f" AND ({role_sql(lt, 'message')})::varchar ILIKE %(text_pattern)s ESCAPE '\\'"
            params["text_pattern"] = like_pattern(text)
        match_sql += pct(SEARCH_SQL_SUFFIX)
        stats, decision = cost.check(
            db, lt, tr, columns_read(lt, f, cols, text), confirmed_cost, index_hints=ctx.estimates.hints(lt)
        )
        extra_notes: list[str] = []
        if ix is not None:
            if decision.status == "run" and decision.plan.exact:
                # A scan matches any part of a word and fits the budget: it gives the better answer.
                extra_notes.append(
                    "the search index wasn't needed: a scan of this scope fits the cost budget, so the entries were "
                    "searched directly (exact substring match)"
                )
            else:
                return _search_via_index(ctx, lt, tr, f, text, ix, order, shown_limit, timezone, confirmed_cost, cols)
        if decision.status == "ask":
            return _ask(lt, tr, f, text, timezone, decision.message)
        plan = decision.plan
        if (missing := untimestamped_note(db, lt, tr)) is not None:
            extra_notes.append(missing)
        scope_sql = time_sql + (" AND " + sampling.clause(plan) if plan.sampling else "")
        what = f"searching log table {lt.name}" + (f" for '{text}'" if text else "")
        timeout = cost.run_timeout(plan, ctx.settings.default_timeout_s, ctx.settings.max_timeout_s)
        measured = _count(db, lt, plan, scope_sql, match_sql, params, timeout, what)
        total = int(measured.hits or 0) if not plan.exact else int(measured.value)
        rows: list[dict[str, Any]] = []
        tags: list[str] = []
        if total:
            role_sel = "".join(
                f", ({role_sql(lt, r)})::varchar AS occ_{r}" for r in FILTER_ROLES if getattr(lt.roles, r) is not None
            )
            rows = db.read(
                f"SELECT {ts_select(lt, cols)}, ({role_sql(lt, 'message')})::varchar AS occ_msg{role_sel}"
                f"{occurrence.select_sql(lt)} FROM {lt.relation} WHERE {scope_sql} AND {match_sql} "
                f"{_order_sql(lt, order)} LIMIT %(shown_limit)s",
                {**params, "shown_limit": shown_limit},
                timeout_s=timeout,
                what=what,
                how_to_narrow=NARROW,
            ).dicts()
            templates = ctx.store.templates(lt.name)
            if templates:  # template tags once the catalog has templates
                tags = [tag_text(t) for t in tag_entries(templates, [str(r["occ_msg"] or "") for r in rows])]
        empty_why = diagnose_empty(db, lt, tr, f, cols) if plan.exact and total == 0 else []
    return _render(lt, tr, f, text, timezone, plan, measured, rows, tags, total, order, empty_why, notes=extra_notes)


@dataclass(frozen=True)
class _IndexPath:
    """A text search that can run on a search index relation alone."""

    name: str
    covered: frozenset[str]
    words: tuple[str, ...]  # the dictionary's tokens of the text
    fuzzy: bool


def _fuzzy_distance(word: str) -> int:
    return 2 if len(word) >= 4 else 1


def _index_path(
    ctx: AppContext, lt: LogTable, f: Filters, text: str | None, fuzzy: bool, cols: dict[str, str]
) -> "_IndexPath | None":
    """The search index to use for this search, or None (then the entries are scanned). A fuzzy search
    has no other way to run, so it explains what is missing instead of returning None."""
    name = lt.search_index_name
    covered = ctx.store.index_columns(lt.name).get("search")
    if not text or name is None or covered is None:
        return None
    db = ctx.db
    words = db.read("SELECT ts_lexize(%(d)s, %(t)s)", {"d": indexes.LOG_DICT, "t": text}).scalar() or []
    if not words:
        if fuzzy:
            raise UserFacingError(f"'{text}' has no searchable words (only punctuation or very common words); try other text.")
        return None  # e.g. "---": a substring scan can still find it
    need: list[str] = []
    for role in ("message", "timestamp", *FILTER_ROLES):
        expr = getattr(lt.roles, role)
        if expr is None:
            continue
        col = role_column(expr)
        need.append(col if col is not None else "")  # a JSON path can't be read from the index
    for key, _ in f.items():
        if key not in FILTER_ROLES:
            need.append(resolve_column(key, cols) or "")
    ok = lt.roles.timestamp is not None and all(c and c in covered for c in need)
    if not ok:
        if fuzzy:
            raise UserFacingError(
                "Fuzzy search can't use the search index for this question (a filter or field it needs is not in "
                "the index, or the log table has no timestamp); drop the column filters or search without fuzzy."
            )
        return None
    return _IndexPath(name, covered, tuple(str(w) for w in words), fuzzy)


def _text_predicate(lt: LogTable, ix: _IndexPath) -> tuple[str, dict[str, Any]]:
    """`@@` over the index relation: the words in order (ts_phrase), or each word within a typo or two."""
    msg = role_sql(lt, "message")
    if not ix.fuzzy:
        return f"{msg} @@ ts_phrase(%(text_phrase)s)", {"text_phrase": " ".join(ix.words)}
    parts, params = [], {}
    for i, w in enumerate(ix.words):
        parts.append(f"{msg} @@ ts_levenshtein(%(fz{i})s, {_fuzzy_distance(w)})")
        params[f"fz{i}"] = w
    return " AND ".join(parts), params


def _search_via_index(
    ctx: AppContext,
    lt: LogTable,
    tr: TimeRange,
    f: Filters,
    text: str | None,
    ix: _IndexPath,
    order: str,
    shown_limit: int,
    tz: str,
    confirmed_cost: str | None,
    cols: dict[str, str],
) -> str:
    """Count and list the matches from the index relation (spike sections 9, 10), then look up the matches'
    occurrence IDs in the source: the index relation can't give the Parquet helper columns."""
    db = ctx.db
    time_sql, time_params = time_clause(lt, tr, cols)
    where, params = build_where(lt, TimeRange(), f, cols)
    pred, text_params = _text_predicate(lt, ix)
    params.update(time_params)
    params.update(text_params)
    match_sql = f"{where} AND {pred}"
    read: list[str] = []  # what the index relation is asked for: all of it is served by the index
    for role in ("timestamp", "message", *FILTER_ROLES):
        read += role_columns(getattr(lt.roles, role))
    read += [c for key, _ in f.items() if key not in FILTER_ROLES and (c := resolve_column(key, cols))]
    _, decision = cost.check(
        db, lt, tr, read, confirmed_cost, indexed=ix.covered, index_hints=ctx.estimates.hints(lt)
    )
    how = "has the words" if not ix.fuzzy else "has words close to"
    if decision.status == "ask":
        head = fmt.how_measured(cost.ASKED_HOW, tr.describe() if tr.bounded else None, _scope_text(f, text, how), tz=tz)
        return head + "\n" + decision.message
    plan = decision.plan
    missing = untimestamped_note(db, lt, tr)
    what = f"searching log table {lt.name} through its search index for '{text}'"
    timeout = cost.run_timeout(plan, ctx.settings.default_timeout_s, ctx.settings.max_timeout_s)
    total = int(
        db.read(
            f"SELECT count(*) FROM {ix.name} WHERE {time_sql} AND {match_sql}",
            params, timeout_s=timeout, what=what, how_to_narrow=NARROW,
        ).scalar()
        or 0
    )
    rows: list[dict[str, Any]] = []
    tags: list[str] = []
    lookup_note: str | None = None
    if total:
        role_sel = "".join(
            f", ({role_sql(lt, r)})::varchar AS occ_{r}" for r in FILTER_ROLES if getattr(lt.roles, r) is not None
        )
        direction = "DESC" if order == "newest" else "ASC"
        rows = db.read(
            f"SELECT {ts_select(lt, cols)}, ({role_sql(lt, 'message')})::varchar AS occ_msg{role_sel} "
            f"FROM {ix.name} WHERE {time_sql} AND {match_sql} "
            f"ORDER BY {role_sql(lt, 'timestamp')} {direction} NULLS LAST LIMIT %(shown_limit)s",
            {**params, "shown_limit": shown_limit},
            timeout_s=timeout, what=what, how_to_narrow=NARROW,
        ).dicts()
        lookup_note = _attach_occurrences(ctx, lt, rows, cols, confirmed_cost, what)
        templates = ctx.store.templates(lt.name)
        if templates:
            tags = [tag_text(t) for t in tag_entries(templates, [str(r["occ_msg"] or "") for r in rows])]
    empty_why = diagnose_empty(db, lt, tr, f, cols) if total == 0 else []
    out = _render(
        lt, tr, f, text, tz, plan, fmt.Measured(float(total), True), rows, tags, total, order, empty_why,
        via=(ix.name, how), notes=[n for n in (missing, lookup_note) if n],
    )
    return out


def _occurrence_columns(lt: LogTable) -> list[str]:
    """The source columns an occurrence ID is made of."""
    k = occurrence.kind(lt)
    if k == "file":
        return list(HELPER_COLUMNS)
    return ["entry_id"] if k == "entry" else role_columns(lt.roles.order)


def _attach_occurrences(
    ctx: AppContext, lt: LogTable, rows: list[dict[str, Any]], cols: dict[str, str], confirmed_cost: str | None, what: str
) -> str | None:
    """Add the occurrence columns (`occ_file`, `occ_row`, ...) to rows found through the index, by finding
    the same entries in the source. The read is narrowed to the listed entries' timestamps (row groups
    outside them are skipped) and goes through the cost check; when it doesn't fit, the rows get no ID and
    the returned note says what it would cost. Entries that look identical get the IDs in turn."""
    if occurrence.kind(lt) is None or not rows:
        return None
    db = ctx.db
    stamps = list(dict.fromkeys(r["occ_ts"] for r in rows))
    moments = [t for t in stamps if isinstance(t, datetime)]
    narrowed = len(moments) == len(stamps)  # a missing or text timestamp can't bound the read
    hull = TimeRange(min(moments), max(moments) + timedelta(milliseconds=1)) if narrowed else TimeRange()
    columns = role_columns(lt.roles.timestamp) + role_columns(lt.roles.message) + _occurrence_columns(lt)
    stats, decision = cost.check(db, lt, hull, columns, confirmed_cost, index_hints=ctx.estimates.hints(lt))
    plan = decision.plan
    if decision.status == "ask" or not plan.exact:
        full = cost.exact_plan(stats, columns)  # the lookup must be exact: quote and confirm its full cost
        return (
            f"occurrence IDs were not looked up: finding the listed entries in the source would need "
            f"{cost.cost_text(full)}; repeat the same call with confirmed_cost={full.cost_token()} to include them"
        )
    timeout = cost.run_timeout(plan, ctx.settings.default_timeout_s, ctx.settings.max_timeout_s)
    found: dict[tuple[Any, str], list[dict[str, Any]]] = {}
    for start in range(0, len(stamps), 100):
        conds: list[str] = []
        params: dict[str, Any] = {}
        for i, ts in enumerate(stamps[start : start + 100]):
            if isinstance(ts, datetime):
                lo, p1 = ts_compare(lt, ">=", ts, f"lo{i}", cols)
                hi, p2 = ts_compare(lt, "<", ts + timedelta(milliseconds=1), f"hi{i}", cols)
                conds.append(f"({lo} AND {hi})")
                params.update(p1)
                params.update(p2)
            elif ts is None:
                conds.append(f"({role_sql(lt, 'timestamp')}) IS NULL")
            else:
                conds.append(f"({role_sql(lt, 'timestamp')})::varchar = %(s{i})s")
                params[f"s{i}"] = str(ts)
        for r in db.read(
            f"SELECT {ts_select(lt, cols)}, ({role_sql(lt, 'message')})::varchar AS occ_msg{occurrence.select_sql(lt)} "
            f"FROM {lt.relation} WHERE {' OR '.join(conds)}",
            params, timeout_s=timeout, what=what, how_to_narrow=NARROW,
        ).dicts():
            found.setdefault((r["occ_ts"], str(r["occ_msg"] or "")), []).append(r)
    for row in rows:
        candidates = found.get((row["occ_ts"], str(row["occ_msg"] or "")))
        if candidates:
            source = candidates.pop(0)
            row.update({k: v for k, v in source.items() if k.startswith("occ_") and k not in row})
    return None


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
    tags: list[str],
    total: int,
    order: str,
    empty_why: list[str],
    via: tuple[str, str] | None = None,
    notes: list[str] | None = None,
) -> str:
    if via:
        kind = f"exact search through the search index {via[0]}: every entry whose message {via[1]} was found" + (
            " (run as you confirmed)" if plan.confirmed else ""
        )
        sample = None
    elif plan.exact:
        kind = "exact search: every entry in scope was checked" + (" (run as you confirmed)" if plan.confirmed else "")
        sample = None
    else:
        kind = "estimated: whole blocks of entries were searched and the number of matching entries scaled up from them"
        upto = "" if plan.rows_exact else "up to "
        sample = (
            f"block sample of {plan.sample_rows or 0:,} of {upto}{plan.population_rows:,} entries "
            f"({len(plan.groups)} whole row group{'' if len(plan.groups) == 1 else 's'} overlapping the period; repeatable)"
        )
    out = [
        fmt.how_measured(
            kind,
            tr.describe() if tr.bounded else None,
            _scope_text(f, text, via[1] if via else "contains"),
            sample,
            index_used=via[0] if via else None,
            tz=tz,
        )
    ]
    out += [fmt.sentence(n) for n in plan.notes]
    if via:
        out.append(fmt.sentence(WHOLE_WORDS))
    out += [fmt.sentence(n) for n in notes or []]
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
    out += [_line(lt, r, tr, tags[i] if tags else "") for i, r in enumerate(rows)]
    return "\n".join(out)
