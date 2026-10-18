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
call in it), so the several cost checks of one call read the metadata once. So are a log table's
columns (`table_columns`): reading them costs two round trips (~0.14 s on remote TextBench).

An in-place Parquet log table's columns and metadata are also kept for the server process (they don't
depend on the time range: the per-row-group timestamp min/max are kept and the range is applied here),
and used again while the source's files keep their names, sizes and modification times (`_held`): one
file listing per call (~0.02 s) instead of the columns and metadata (~0.13 s on TextBench).
"""

import re
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from rcagent import evidence
from rcagent.catalog.models import LogTable
from rcagent.db import Database, quote_ident
from rcagent.query.filters import TimeRange
from rcagent.setup.paths import resolve_source, source_sql, sql_literal
from rcagent.setup.roles import HELPER_COLUMNS, is_temporal, role_column
from rcagent.setup.sniff import relation_columns

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
    # The timestamp column's min/max in this group from the Parquet statistics (None: no usable
    # statistic). Microsecond precision, so a nanosecond value may lie up to 1 µs either side.
    ts_min: datetime | None = None
    ts_max: datetime | None = None


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
_COLUMNS: ContextVar[dict[tuple[object, ...], dict[str, str]] | None] = ContextVar("table_columns_memo", default=None)


@contextmanager
def per_call() -> Iterator[None]:
    """Remember collected scope statistics until the block ends (one tool call)."""
    token, rows_token, cols_token = _MEMO.set({}), _LIVE_ROWS.set({}), _COLUMNS.set({})
    stamps_token = _STAMPS.set({})
    try:
        yield
    finally:
        _MEMO.reset(token)
        _LIVE_ROWS.reset(rows_token)
        _COLUMNS.reset(cols_token)
        _STAMPS.reset(stamps_token)


def table_columns(db: Database, lt: LogTable, remote: bool = False) -> dict[str, str]:
    """name -> type of a log table's relation, remembered for the rest of the tool call inside `per_call()`."""
    memo = _COLUMNS.get()
    key = (id(db), lt.relation, lt.source)
    if memo is None or key not in memo:
        held = _held(db, lt)
        if held is not None and held.columns is not None:
            cols = dict(held.columns)
            _cite(held.columns_from)
        else:
            start, at = evidence.mark(), datetime.now(UTC)
            cols = dict(relation_columns(db, lt.relation, lt.source, remote))
            if held is not None:
                held.columns = dict(cols)
                held.columns_from = (evidence.since(start), at)
        if memo is None:
            return cols
        memo[key] = cols
    return dict(memo[key])


# ---- the session copy of in-place Parquet columns and metadata -------------------------------------


@dataclass
class _Held:
    stamp: tuple[tuple[Any, ...], ...]  # (file, size, last modified) of every file of the source
    columns: dict[str, str] | None = None
    meta: tuple[tuple[Any, ...], ...] | None = None  # the rows of _read_meta
    # The queries that read them, and when: noted again in the evidence of a call that reuses them, so every
    # number planned from them is traced to the query that produced it.
    columns_from: tuple[list[evidence.Query], datetime] | None = None
    meta_from: tuple[list[evidence.Query], datetime] | None = None


def _cite(source: tuple[list[evidence.Query], datetime] | None) -> None:
    if source is not None:
        for q in source[0]:
            evidence.note_reused(q, source[1])


_SESSION: dict[tuple[object, ...], _Held] = {}
_SESSION_LOCK = threading.Lock()
_STAMPS: ContextVar[dict[tuple[object, ...], _Held | None] | None] = ContextVar("source_stamp_memo", default=None)
STAMP_SQL = (
    "SELECT filename, size, last_modified, last_modified < now() - INTERVAL '{settle} seconds' AS settled "
    "FROM read_blob({src}) ORDER BY 1"
)
# A file modified this recently is not kept: a modification time has whole-second precision on some
# file systems, so a rewrite of the same size within that second would look unchanged (the Parquet
# metadata cache of DuckDB, which SereneDB builds on, waits 10 s for the same reason).
SETTLE_S = 10


def _session_key(db: Database, lt: LogTable) -> tuple[object, ...] | None:
    if lt.mode != "in_place" or lt.source_format != "parquet":
        return None
    return (db.settings.reader_url, lt.name, lt.relation, lt.source, lt.roles.timestamp, lt.timezone)


def _held(db: Database, lt: LogTable) -> _Held | None:
    """The session copy of an in-place Parquet log table's columns and metadata, valid for this call:
    the source's files have the same names, sizes and modification times as when the copy was read
    (one listing, ~0.02 s on remote TextBench, once per tool call). A changed source starts an empty
    copy; None when the source can't be listed or was modified in the last SETTLE_S seconds (then
    nothing is kept)."""
    key = _session_key(db, lt)
    if key is None:
        return None
    memo = _STAMPS.get()
    if memo is not None and key in memo:
        return memo[key]
    rs = resolve_source(lt.source, db.settings, "parquet")
    try:
        rows = db.read(
            STAMP_SQL.format(src=source_sql(rs), settle=SETTLE_S), {}, what=f"checking the files of {lt.name}"
        ).rows
    except Exception:  # no listing for this source: read the columns and metadata every time
        rows = []
    stamp = tuple(tuple(r[:3]) for r in rows)
    held: _Held | None = None
    if rows and all(r[2] is not None and r[3] is True for r in rows):
        with _SESSION_LOCK:
            held = _SESSION.get(key)
            if held is None or held.stamp != stamp:
                held = _SESSION[key] = _Held(stamp)
    if memo is not None:
        memo[key] = held
    return held


def forget_session() -> None:
    """Drop every session copy (tests)."""
    with _SESSION_LOCK:
        _SESSION.clear()


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


def _ts_bounds_sql(lt: LogTable, cols: dict[str, str]) -> tuple[str, str] | None:
    """SQL for the timestamp column's per-row-group (min, max) as timestamptz from the Parquet statistics,
    or None when the timestamp is not a plain time column (then no row group can be skipped by time)."""
    ts_col = role_column(lt.roles.timestamp) if lt.roles.timestamp else None
    if ts_col is None:
        return None
    typ = cols.get(ts_col, "").upper()
    if not is_temporal(typ):
        return None
    naive = "WITH TIME ZONE" not in typ and not typ.startswith("TIMESTAMPTZ")
    zone = sql_literal(lt.timezone)

    def bound(stat: str) -> str:  # try_cast: statistics are text and may be missing
        return f"try_cast({stat} AS timestamp) AT TIME ZONE {zone}" if naive else f"try_cast({stat} AS timestamptz)"

    return bound("stats_min"), bound("stats_max")


def _read_meta(db: Database, lt: LogTable, cols: dict[str, str]) -> tuple[tuple[Any, ...], ...]:
    """One metadata read for the row counts, the per-column sizes and the timestamp's min/max per row
    group (each read of a remote file's metadata costs ~0.15 s on TextBench). Rows: (file, row group,
    top-level column, compressed bytes, rows, timestamp min, timestamp max); the min/max only on the
    timestamp column's row."""
    rs = resolve_source(lt.source, db.settings, "parquet")
    ts_col = role_column(lt.roles.timestamp) if lt.roles.timestamp else None
    bounds = _ts_bounds_sql(lt, cols)
    lo, hi = bounds if bounds is not None else ("NULL::timestamptz", "NULL::timestamptz")
    rows = db.read(
        f"SELECT file_name, row_group_id, split_part(path_in_schema, ', ', 1) AS c, "
        f"sum(total_compressed_size)::bigint AS b, max(row_group_num_rows) AS n, "
        f"min(CASE WHEN path_in_schema = %(ts)s THEN {lo} END) AS tmin, "
        f"max(CASE WHEN path_in_schema = %(ts)s THEN {hi} END) AS tmax "
        f"FROM parquet_metadata({source_sql(rs)}) GROUP BY 1, 2, 3 ORDER BY 1, 2, 3",
        {"ts": ts_col or ""},
        what=f"reading the Parquet metadata of {lt.name}",
    ).rows
    return tuple(tuple(r) for r in rows)


def _overlaps(tmin: datetime | None, tmax: datetime | None, tr: TimeRange) -> bool:
    """Whether a row group may hold entries in the range, by its statistics: SQL's
    coalesce(min < end AND max >= start, TRUE), so a missing statistic never skips a group."""
    parts: list[bool | None] = []
    if tr.end is not None:
        parts.append(None if tmin is None else tmin < tr.end)
    if tr.start is not None:
        parts.append(None if tmax is None else tmax >= tr.start)
    return not any(p is False for p in parts)


def _parquet(db: Database, lt: LogTable, tr: TimeRange, has_f: bool, has_s: bool) -> ScopeStats:
    rs = resolve_source(lt.source, db.settings, "parquet")
    cols = table_columns(db, lt, rs.remote)
    held = _held(db, lt)
    if held is not None and held.meta is not None:
        per_col = held.meta
        _cite(held.meta_from)
    else:
        start, at = evidence.mark(), datetime.now(UTC)
        per_col = _read_meta(db, lt, cols)
        if held is not None:
            held.meta = per_col
            held.meta_from = (evidence.since(start), at)
    bounded = tr.bounded and _ts_bounds_sql(lt, cols) is not None
    rows_of: dict[tuple[str, int], int] = {}
    span: dict[tuple[str, int], tuple[datetime | None, datetime | None]] = {}
    for f, g, _, _, n, tmin, tmax in per_col:
        rows_of[(f, g)] = max(rows_of.get((f, g), 0), int(n or 0))
        if tmin is not None or tmax is not None:
            span[(f, g)] = (tmin, tmax)
    hit = {k: _overlaps(*span.get(k, (None, None)), tr) if bounded else True for k in rows_of}
    groups = [(f, g, n) for (f, g), n in rows_of.items()]
    by_col: dict[str, int] = {}
    group_cols: dict[tuple[str, int], dict[str, int]] = {}
    for f, g, c, b, _, _, _ in per_col:
        if hit[(f, g)]:
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
        if hit[(f, g)]:
            tmin, tmax = span.get((f, g), (None, None))
            in_range_groups.append(GroupStat(first, int(n), group_cols.get((f, g), {}), tmin, tmax))
        first += int(n)
    total = sum(int(r[2]) for r in groups)
    in_range = sum(int(r[2]) for r in groups if hit[(r[0], r[1])])
    single = len(files) == 1
    return ScopeStats(
        total_rows=total,
        rows_in_range=in_range,
        bytes_by_column=by_col,
        time_skippable=bounded,
        remote=rs.remote,
        has_filter_index=has_f,
        has_search_index=has_s,
        can_sample=single,
        groups=tuple(in_range_groups) if single else (),
        rows_exact=not tr.bounded,
    )


def _table(db: Database, lt: LogTable, tr: TimeRange, has_f: bool, has_s: bool) -> ScopeStats:
    cols = table_columns(db, lt)
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
