"""What a query over a log table's scope would read, from metadata only (spec section 6.2 step 1).

In-place Parquet: `parquet_metadata` gives per-row-group row counts, per-column compressed sizes
and timestamp min/max, so a time range is priced by the row groups it overlaps (SereneDB prunes
them when the literal is typed like the column; measured in #10, see the task report). In-place
JSON has no metadata: any query parses the whole file. Copied tables: the row count the catalog
recorded at setup (log_tables.row_count; our setup wrote them and they never change, so never a
count(*) per check, which is itself a full scan). In-place table sources can grow after setup: their
row count is the planner's live estimate (pg_class.reltuples, which SereneDB keeps current on insert;
measured: it does not drop on delete, so it is an upper bound), with count(*) only when the table has
no such estimate. Both take an average width per column from a few rows; a time range on them gives
an upper bound (every entry), marked `rows_exact=False`.

`collect` is remembered for the rest of a tool call inside `per_call()` (the server wraps every tool
call in it), so the several cost checks of one call read the metadata once.
"""

import re
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field

from serenedb_extractor.catalog.models import LogTable
from serenedb_extractor.db import Database, quote_ident
from serenedb_extractor.query.filters import TimeRange
from serenedb_extractor.setup.paths import resolve_source, source_sql, sql_literal
from serenedb_extractor.setup.roles import HELPER_COLUMNS, is_temporal, role_column
from serenedb_extractor.setup.sniff import relation_columns

WHOLE = "*"  # bytes_by_column key: read by every query whatever its columns (a JSON file is parsed whole)
JSON_BYTES_PER_ENTRY = 500  # a guess for remote JSON, whose size is unknown here
WIDTH_SAMPLE_ROWS = 1000
_LEAD_IDENT = re.compile(r'^"((?:[^"]|"")+)"')


@dataclass(frozen=True)
class GroupStat:
    """One Parquet row group that overlaps the time range: where its rows start and what it costs."""

    first_row: int  # its first file_row_number
    rows: int
    bytes_by_column: dict[str, int]


@dataclass(frozen=True)
class ScopeStats:
    total_rows: int
    rows_in_range: int  # whole row groups overlapping the range: an upper bound when the range cuts one
    bytes_by_column: dict[str, int]  # compressed bytes each column reads over the scope
    time_skippable: bool  # the time range skips row groups by their statistics
    remote: bool
    has_filter_index: bool
    has_search_index: bool
    # Block sampling needs a row-position column that SereneDB prunes on: `file_row_number` of a
    # single in-place Parquet file. With several files, `filename = … AND file_row_number …` does
    # not prune (measured in the #10 fix round), and copied tables, tables and JSON read every byte
    # anyway, so they never sample.
    can_sample: bool = False
    groups: tuple[GroupStat, ...] = field(default_factory=tuple)  # the in-range row groups, in file order
    rows_exact: bool = True  # False when rows_in_range is only the row-group upper bound

    def bytes_for(self, columns: list[str]) -> int:
        """Bytes read by a query that touches `columns`; a column listed twice (read by two scans)
        costs twice. Unknown names, like the helper columns, are free."""
        named = sum(self.bytes_by_column.get(c, 0) for c in columns if c != WHOLE)
        return named + self.bytes_by_column.get(WHOLE, 0)


def role_columns(expr: str | None) -> list[str]:
    """The column a stored role expression reads (`"col"` or `"col" ->> 'key'`)."""
    if not expr:
        return []
    col = role_column(expr)
    if col is not None:
        return [col]
    m = _LEAD_IDENT.match(expr.strip())
    return [m.group(1).replace('""', '"')] if m else []


_MEMO: ContextVar[dict[tuple[object, ...], "ScopeStats"] | None] = ContextVar("scope_stats_memo", default=None)
_LIVE_ROWS: ContextVar[dict[tuple[object, ...], int] | None] = ContextVar("live_row_count_memo", default=None)


@contextmanager
def per_call() -> Iterator[None]:
    """Remember collected scope statistics until the block ends (one tool call)."""
    token, rows_token = _MEMO.set({}), _LIVE_ROWS.set({})
    try:
        yield
    finally:
        _MEMO.reset(token)
        _LIVE_ROWS.reset(rows_token)


def _memo_key(db: Database, lt: LogTable, tr: TimeRange) -> tuple[object, ...]:
    return (
        id(db), lt.name, lt.mode, lt.source, lt.source_format, lt.relation, lt.row_count, lt.timezone,
        lt.roles.timestamp, lt.filter_index_name, lt.search_index_name, tr.start, tr.end,
    )


def collect(db: Database, lt: LogTable, tr: TimeRange) -> ScopeStats:
    memo = _MEMO.get()
    if memo is None:
        return _collect(db, lt, tr)
    key = _memo_key(db, lt, tr)
    if key not in memo:
        memo[key] = _collect(db, lt, tr)
    return memo[key]


def _collect(db: Database, lt: LogTable, tr: TimeRange) -> ScopeStats:
    has_f, has_s = lt.filter_index_name is not None, lt.search_index_name is not None
    if lt.mode == "in_place" and lt.source_format == "parquet":
        return _parquet(db, lt, tr, has_f, has_s)
    if lt.mode == "in_place" and lt.source_format == "json":
        rs = resolve_source(lt.source, db.settings, "json")
        rows = int(lt.row_count or 0)
        size = rs.size_bytes if rs.size_bytes is not None else rows * JSON_BYTES_PER_ENTRY
        return ScopeStats(rows, rows, {WHOLE: int(size)}, False, rs.remote, has_f, has_s)
    return _table(db, lt, tr, has_f, has_s)


def _parquet(db: Database, lt: LogTable, tr: TimeRange, has_f: bool, has_s: bool) -> ScopeStats:
    rs = resolve_source(lt.source, db.settings, "parquet")
    meta = f"parquet_metadata({source_sql(rs)})"
    ts_col = role_column(lt.roles.timestamp) if lt.roles.timestamp else None
    params: dict[str, object] = {"ts": ts_col or ""}
    what = f"reading the Parquet metadata of {lt.name}"
    skippable = False
    hit: dict[tuple[str, int], bool] = {}
    # One metadata read for both the row counts and the per-column sizes (each read of a remote
    # file's metadata costs ~0.15 s on TextBench).
    per_col = db.read(
        f"SELECT file_name, row_group_id, split_part(path_in_schema, ', ', 1) AS c, "
        f"sum(total_compressed_size)::bigint AS b, max(row_group_num_rows) AS n FROM {meta} GROUP BY 1, 2, 3",
        {},
        what=what,
    ).rows
    rows_of: dict[tuple[str, int], int] = {}
    for f, g, _, _, n in per_col:
        rows_of[(f, g)] = max(rows_of.get((f, g), 0), int(n or 0))
    groups = [(f, g, n) for (f, g), n in rows_of.items()]
    if tr.bounded and ts_col is not None:
        cols = dict(relation_columns(db, lt.relation, lt.source, rs.remote))
        typ = cols.get(ts_col, "").upper()
        if is_temporal(typ):
            skippable = True
            naive = "WITH TIME ZONE" not in typ and not typ.startswith("TIMESTAMPTZ")
            zone = sql_literal(lt.timezone)

            def bound(stat: str) -> str:  # try_cast: statistics are text and may be missing
                return f"try_cast({stat} AS timestamp) AT TIME ZONE {zone}" if naive else f"try_cast({stat} AS timestamptz)"

            bounds = []
            if tr.end is not None:
                bounds.append(f"{bound('stats_min')} < %(hi)s::timestamptz")
                params["hi"] = tr.end.isoformat()
            if tr.start is not None:
                bounds.append(f"{bound('stats_max')} >= %(lo)s::timestamptz")
                params["lo"] = tr.start.isoformat()
            # A group without usable statistics can't be skipped (coalesce to TRUE).
            ranges = db.read(
                f"SELECT file_name, row_group_id, coalesce({' AND '.join(bounds)}, TRUE) AS hit "
                f"FROM {meta} WHERE path_in_schema = %(ts)s",
                params,
                what=what,
            ).rows
            hit = {(r[0], r[1]): bool(r[2]) for r in ranges}
    by_col: dict[str, int] = {}
    group_cols: dict[tuple[str, int], dict[str, int]] = {}
    for f, g, c, b, _ in per_col:
        if hit.get((f, g), True):
            by_col[c] = by_col.get(c, 0) + int(b or 0)
            group_cols.setdefault((f, g), {})[c] = int(b or 0)
    for helper in HELPER_COLUMNS:
        by_col.setdefault(helper, 0)
    files = sorted({r[0] for r in groups})
    in_range_groups: list[GroupStat] = []
    first = 0
    for f, g, n in sorted(groups, key=lambda r: (r[0], r[1])):
        if f != files[0]:
            continue  # only a single file can be block-sampled; the others count via the totals below
        if hit.get((f, g), True):
            in_range_groups.append(GroupStat(first, int(n), group_cols.get((f, g), {})))
        first += int(n)
    total = sum(int(r[2]) for r in groups)
    in_range = sum(int(r[2]) for r in groups if hit.get((r[0], r[1]), True))
    single = len(files) == 1
    return ScopeStats(
        total_rows=total,
        rows_in_range=in_range,
        bytes_by_column=by_col,
        time_skippable=skippable,
        remote=rs.remote,
        has_filter_index=has_f,
        has_search_index=has_s,
        can_sample=single,
        groups=tuple(in_range_groups) if single else (),
        rows_exact=not tr.bounded,
    )


def _table(db: Database, lt: LogTable, tr: TimeRange, has_f: bool, has_s: bool) -> ScopeStats:
    cols = dict(relation_columns(db, lt.relation, lt.source))
    if lt.mode == "in_place":
        total = _live_rows(db, lt)
    elif lt.row_count is not None:
        total = int(lt.row_count)
    else:  # an older catalog row without a count: count once (remembered for the tool call)
        total = _count(db, lt)
    # A time range is not counted (that would scan the timestamp column on every check): every entry
    # is the upper bound, and the pricing reads whole columns anyway.
    ranged = tr.bounded and lt.roles.timestamp is not None
    names = list(cols)
    widths: dict[str, int] = {}
    if names and total:
        avgs = ", ".join(f"avg(octet_length(({quote_ident(c)})::varchar))" for c in names)
        row = db.read(
            f"SELECT {avgs} FROM (SELECT * FROM {lt.relation} LIMIT {WIDTH_SAMPLE_ROWS})", {}, what=f"sizing {lt.name}"
        ).rows[0]
        widths = {c: int(round(float(w or 0) * total)) for c, w in zip(names, row, strict=True)}
    return ScopeStats(total, total, widths, False, False, has_f, has_s, rows_exact=not ranged)


def _count(db: Database, lt: LogTable) -> int:
    return int(db.read(f"SELECT count(*) FROM {lt.relation}", {}, what=f"counting {lt.name}").scalar() or 0)


def _live_rows(db: Database, lt: LogTable) -> int:
    """An in-place table source's current row count, read once per tool call: the planner's estimate
    (pg_class.reltuples), else a count(*) when the table has none (negative or missing)."""
    memo = _LIVE_ROWS.get()
    key = (id(db), lt.name, lt.source, lt.relation)
    if memo is not None and key in memo:
        return memo[key]
    schema, _, table = lt.source.strip().rpartition(".")
    est = db.read(
        "SELECT max(c.reltuples) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE c.relname = %(t)s AND n.nspname = COALESCE(NULLIF(%(s)s, ''), current_schema()) AND c.relkind = 'r'",
        {"t": table, "s": schema},
        what=f"reading the row count of {lt.name}",
    ).scalar()
    total = int(round(float(est))) if est is not None and float(est) >= 0 else _count(db, lt)
    if memo is not None:
        memo[key] = total
    return total
